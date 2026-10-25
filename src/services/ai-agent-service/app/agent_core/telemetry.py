"""Optional bounded OTLP telemetry with an explicit content-free attribute policy.

The SDK/exporters are standard OpenTelemetry 1.45.1. Adopted GenAI attributes
are Development conventions (reviewed 2026-10-25), not a stable external API.
No prompt, result, profile, exception message, URL, auth value or baggage is
captured. Application IDs are not metric labels. Export runs off the run thread.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
import threading
import time
from urllib.parse import urlsplit

from opentelemetry import context as otel_context, trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .errors import AgentErrorCode, PortError


_OPERATIONS = {"agent.execute", "chat", "embeddings", "retrieval", "tool"}
_TEXT_FIELDS = {"gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model", "blogapp.run.intent",
                "blogapp.run.status", "messaging.system", "messaging.operation.name", "blogapp.usage.basis"}
_COUNT_FIELDS = {"gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "blogapp.execution.attempt",
                 "blogapp.embedding.requests", "blogapp.embedding.reported_tokens", "blogapp.embedding.estimated_tokens",
                 "blogapp.embedding.uncertain_tokens"}
_RUN_STATUSES = {"completed", "failed", "partial", "needs_input", "cancelled", "deferred", "aborted_lease_lost", "aborted_cancel", "error_transient"}
_PARENT = re.compile(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}\Z")
_runtime = None


class _OperationSpan:
    """Keep aggregate metadata available even for an unsampled trace parent."""
    def __init__(self, inner, attributes):
        self.inner = inner
        self.attributes = dict(attributes)

    def set_attributes(self, attributes):
        safe = _safe_attributes(attributes)
        self.attributes.update(safe)
        self.inner.set_attributes(safe)


def _safe_attributes(attributes):
    safe = {}
    for key, value in (attributes or {}).items():
        if key in _TEXT_FIELDS and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value):
            safe[key] = value
        elif key in _COUNT_FIELDS and type(value) is int and 0 <= value <= 2**53:
            safe[key] = value
        elif key == "messaging.message.queue_time_ms" and type(value) in (int, float) and math.isfinite(value) and value >= 0:
            safe[key] = min(value, 86400000.0)
    return safe


def set_span_attributes(span, attributes):
    if span is not None:
        try:
            span.set_attributes(_safe_attributes(attributes))
        except Exception:
            pass  # Telemetry cannot change an application result.


def current_traceparent():
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"00-{context.trace_id:032x}-{context.span_id:016x}-{int(context.trace_flags) & 255:02x}"


def _error_status(error):
    code = error.code if isinstance(error, PortError) else error
    return code.value if isinstance(code, AgentErrorCode) else "internal_error"


def _record_counter(name, operation, error):
    runtime = _runtime
    if runtime is None or operation not in _OPERATIONS:
        return
    try:
        counter = getattr(runtime, name, None)
        if counter is not None:
            counter.add(1, {"operation": operation, "status": _error_status(error)})
    except Exception:
        pass  # Observation must not change admission, retry or run results.


def record_call_retry(operation, reason):
    """An admitted callback retry, not proof of a paid HTTP request."""
    if operation in {"chat", "tool"}:
        _record_counter("retries", operation, reason)


def record_admission_rejection(operation, error):
    """A pre-call rejection, separate from failures inside provider spans."""
    if operation in {"chat", "tool"}:
        _record_counter("admissions", operation, error)


@dataclass
class TelemetryRuntime:
    provider: object | None = None
    metrics: object | None = None
    duration: object | None = None
    queue_wait: object | None = None
    attempts: object | None = None
    terminals: object | None = None
    tokens: object | None = None
    retries: object | None = None
    errors: object | None = None
    admissions: object | None = None
    timeout: float = 1.0

    def force_flush(self, timeout_millis=2000):
        """Explicit test/operations drain; never called on the execution path."""
        try:
            trace_ok = self.provider is None or self.provider.force_flush(timeout_millis=timeout_millis)
            metric_ok = self.metrics is None or self.metrics.force_flush(timeout_millis=timeout_millis)
            return bool(trace_ok and metric_ok)
        except Exception:
            return False

    def shutdown(self):
        global _runtime
        if _runtime is self:
            _runtime = None
        provider, metrics = self.provider, self.metrics
        self.provider, self.metrics = None, None

        def close():
            for resource in (provider, metrics):
                if resource is not None:
                    try:
                        resource.shutdown()
                    except Exception:
                        pass

        # SDK shutdown can wait for an exporter thread. Bound service shutdown
        # even when a collector disappears; no unbounded atexit hooks are used.
        if provider is not None or metrics is not None:
            thread = threading.Thread(target=close, name="agent-telemetry-shutdown", daemon=True)
            thread.start()
            thread.join(timeout=self.timeout + 1)


def configure_telemetry(environ):
    """Enable only an explicitly configured OTLP/HTTP endpoint; default is off."""
    global _runtime
    endpoint = environ.get("AGENT_OTEL_ENDPOINT", "").strip()
    if not endpoint:
        return TelemetryRuntime()
    try:
        parsed = urlsplit(endpoint)
        timeout = float(environ.get("AGENT_OTEL_TIMEOUT_SECONDS", "1"))
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname and parsed.path.endswith("/v1/traces")
                 and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                 and math.isfinite(timeout) and .1 <= timeout <= 10)
        parsed.port
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise PortError(AgentErrorCode.CONFIG_ERROR, "Invalid explicit OTLP endpoint or timeout", port="telemetry")
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource(...) intentionally bypasses automatic environment/resource
    # detectors: only the fixed public service name is exported by this module.
    resource = Resource({"service.name": "blogapp-ai-agent"})
    provider = TracerProvider(resource=resource, shutdown_on_exit=False)
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint, timeout=timeout, headers={}, max_request_size=262144),
        max_queue_size=256, max_export_batch_size=32, schedule_delay_millis=1000,
        export_timeout_millis=timeout * 1000))
    metrics_endpoint = endpoint.removesuffix("/v1/traces") + "/v1/metrics"
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=metrics_endpoint, timeout=timeout, headers={}),
                                           export_interval_millis=15000, export_timeout_millis=timeout * 1000)
    metrics = MeterProvider(resource=resource, metric_readers=[reader], shutdown_on_exit=False)
    meter = metrics.get_meter("blogapp.agent", "1")
    runtime = TelemetryRuntime(provider=provider, metrics=metrics, timeout=timeout,
        duration=meter.create_histogram("blogapp.agent.operation.duration", unit="s"),
        queue_wait=meter.create_histogram("blogapp.agent.queue.wait", unit="s"),
        attempts=meter.create_counter("blogapp.agent.execution.attempts"),
        terminals=meter.create_counter("blogapp.agent.run.outcomes"),
        tokens=meter.create_counter("blogapp.agent.tokens", unit="{token}"),
        retries=meter.create_counter("blogapp.agent.call.retries"),
        errors=meter.create_counter("blogapp.agent.operation.errors"),
        admissions=meter.create_counter("blogapp.agent.call.admission.rejections"))
    _runtime = runtime
    return runtime


@contextmanager
def trace_operation(operation, *, parent=None, attributes=None, kind="internal"):
    """Trace an operation without recording raw exception messages or content."""
    runtime = _runtime
    if runtime is None or runtime.provider is None or operation not in _OPERATIONS:
        yield None
        return
    safe = _safe_attributes(attributes)
    if operation in {"chat", "embeddings"}:
        safe["gen_ai.operation.name"] = operation
    try:
        parent_context = None
        if isinstance(parent, str) and _PARENT.fullmatch(parent):
            # Extract traceparent only. Tracestate and baggage are not imported.
            parent_context = TraceContextTextMapPropagator().extract({"traceparent": parent})
        span = runtime.provider.get_tracer("blogapp.agent", "1").start_span(
            operation, context=parent_context, attributes=safe,
            kind=trace.SpanKind.CLIENT if kind == "client" else trace.SpanKind.INTERNAL)
        token = otel_context.attach(trace.set_span_in_context(span))
    except Exception:
        yield None
        return
    started = time.monotonic()
    status = "ok"
    operation_span = _OperationSpan(span, safe)
    try:
        yield operation_span
    except BaseException as error:
        status = "error"
        code = _error_status(error)
        _record_counter("errors", operation, error)
        try:
            span.set_attribute("error.type", code)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
        except Exception:
            pass
        raise
    finally:
        try:
            duration = max(0, time.monotonic() - started)
            runtime.duration.record(duration, {"operation": operation, "status": status})
            if operation == "agent.execute":
                if "messaging.message.queue_time_ms" in safe:
                    runtime.queue_wait.record(safe["messaging.message.queue_time_ms"] / 1000, {})
                runtime.attempts.add(1, {"recovered": safe.get("blogapp.execution.attempt", 1) > 1})
                final_status = operation_span.attributes.get("blogapp.run.status")
                if final_status in _RUN_STATUSES:
                    runtime.terminals.add(1, {"status": final_status})
            if operation in {"chat", "embeddings"}:
                attrs = operation_span.attributes
                basis = attrs.get("blogapp.usage.basis", "unknown")
                basis = basis if basis in {"reported", "estimated", "uncertain"} else "unknown"
                for key, direction in (("gen_ai.usage.input_tokens", "input"), ("gen_ai.usage.output_tokens", "output")):
                    if key in attrs:
                        runtime.tokens.add(attrs[key], {"operation": operation, "direction": direction, "basis": basis})
            span.end()
        except Exception:
            pass
        finally:
            try:
                otel_context.detach(token)
            except Exception:
                pass
