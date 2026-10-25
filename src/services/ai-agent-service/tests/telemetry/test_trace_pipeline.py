"""Real OTLP transport to a local test collector; not full service acceptance."""

from contextlib import contextmanager
import asyncio
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from types import SimpleNamespace

import pytest
import httpx

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

from agent_core.errors import AgentErrorCode, PortError
from agent_core.telemetry import configure_telemetry, current_traceparent, set_span_attributes, trace_operation

from messaging.wire import compose_run_envelope


def compose_progress():
    return compose_run_envelope(schema_version=1, message_type="agent.run.progressed",
        run_id="11111111-1111-4111-8111-111111111111", conversation_id="22222222-2222-4222-8222-222222222222",
        correlation_id="33333333-3333-4333-8333-333333333333",
        payload={"event_sequence": 1, "kind": "retrieval_started", "message": "Working", "detail": {}})


def test_run_envelopes_preserve_active_w3c_parent_for_backend_projection():
    provider = TracerProvider(shutdown_on_exit=False)
    try:
        with provider.get_tracer("test").start_as_current_span("worker") as span:
            envelope = compose_progress()
            context = span.get_span_context()
            assert envelope.trace_context == f"00-{context.trace_id:032x}-{context.span_id:016x}-{int(context.trace_flags) & 255:02x}"
    finally:
        provider.shutdown()


@contextmanager
def collector(*, status=200, delay=0):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            self.server.payloads.append((self.path, self.headers.get("Content-Type"), payload))
            if delay:
                time.sleep(delay)
            try:
                self.send_response(status)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.payloads = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/v1/traces"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def traces(server):
    result = []
    for path, content_type, payload in server.payloads:
        assert content_type == "application/x-protobuf"
        if path == "/v1/traces":
            parsed = ExportTraceServiceRequest.FromString(payload)
            result.extend(span for resource in parsed.resource_spans for scope in resource.scope_spans for span in scope.spans)
    return result


def metrics(server):
    result = []
    for path, _, payload in server.payloads:
        if path == "/v1/metrics":
            parsed = ExportMetricsServiceRequest.FromString(payload)
            result.extend(metric for resource in parsed.resource_metrics for scope in resource.scope_metrics for metric in scope.metrics)
    return result


def test_real_otlp_exporter_preserves_parentage_and_only_exports_approved_metadata():
    parent = "00-11111111111111111111111111111111-2222222222222222-01"
    private = "PRIVATE_PROMPT_PROFILE_ANSWER_AUTH_SHOULD_NOT_EXPORT"
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            with trace_operation("agent.execute", parent=parent, attributes={
                "messaging.system": "rabbitmq", "messaging.message.queue_time_ms": 20,
                "blogapp.execution.attempt": 2, "raw_prompt": private, "run_id": private,
            }) as worker:
                carrier = current_traceparent()
                assert compose_progress().trace_context == carrier
                with trace_operation("chat", kind="client", attributes={
                    "gen_ai.provider.name": "openai_compatible", "gen_ai.request.model": "test-model",
                    "prompt": private, "authorization": private,
                }) as model:
                    set_span_attributes(model, {"gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 4,
                                                "blogapp.usage.basis": "reported", "answer": private})
                set_span_attributes(worker, {"blogapp.run.status": "completed"})
            assert runtime.force_flush()
            exported = {span.name: span for span in traces(server)}
            assert set(exported) == {"agent.execute", "chat"}
            assert exported["agent.execute"].trace_id.hex() == "1" * 32
            assert exported["agent.execute"].parent_span_id.hex() == "2" * 16
            assert exported["chat"].trace_id == exported["agent.execute"].trace_id
            assert exported["chat"].parent_span_id == exported["agent.execute"].span_id
            assert all(not span.events for span in exported.values())
            assert private.encode() not in b"".join(payload for _, _, payload in server.payloads)
            observed = metrics(server)
            assert {metric.name for metric in observed} >= {
                "blogapp.agent.operation.duration", "blogapp.agent.execution.attempts", "blogapp.agent.tokens",
                "blogapp.agent.queue.wait", "blogapp.agent.run.outcomes"}
            for metric in observed:
                data = getattr(metric, metric.WhichOneof("data"))
                for point in data.data_points:
                    assert {attr.key for attr in point.attributes} <= {"operation", "status", "recovered", "direction", "basis"}
        finally:
            runtime.shutdown()


def test_exception_message_and_stack_never_become_trace_events():
    private = "PRIVATE_EXCEPTION_WITH_PROMPT_OR_URL"
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            with pytest.raises(PortError):
                with trace_operation("tool"):
                    raise PortError(AgentErrorCode.PROVIDER_ERROR, private)
            assert runtime.force_flush()
            exported = traces(server)
            assert len(exported) == 1 and exported[0].status.code == 2
            assert not exported[0].events
            assert private.encode() not in b"".join(payload for _, _, payload in server.payloads)
        finally:
            runtime.shutdown()


def test_unsampled_remote_parent_keeps_aggregate_metrics_without_forcing_trace_sampling():
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            with trace_operation("agent.execute", parent="00-11111111111111111111111111111111-2222222222222222-00") as worker:
                with trace_operation("chat") as model:
                    set_span_attributes(model, {"gen_ai.usage.input_tokens": 5, "blogapp.usage.basis": "estimated"})
                set_span_attributes(worker, {"blogapp.run.status": "completed"})
            assert runtime.force_flush()
            assert traces(server) == []
            assert {metric.name for metric in metrics(server)} >= {"blogapp.agent.tokens", "blogapp.agent.run.outcomes"}
        finally:
            runtime.shutdown()


@pytest.mark.parametrize("action,expected_status", [("completed", "completed"), ("partially_completed", "partial")])
def test_public_worker_dispatch_connects_incoming_trace_to_model_and_event_carrier(action, expected_status):
    from messaging.worker import CycleResult, ExecutionWorker

    # The worker's public dispatch is real. Only the inner business operation
    # is a transport fixture: this test makes no model or database claim.
    parent = "00-11111111111111111111111111111111-2222222222222222-01"
    now = datetime.now(timezone.utc)
    claimed = SimpleNamespace(run_id="11111111-1111-4111-8111-111111111111", envelope=SimpleNamespace(trace_context=parent),
                              execution_attempt=1, fencing_token=1, recovered=False,
                              accepted_at=now - timedelta(seconds=2), started_at=now)
    worker = ExecutionWorker.__new__(ExecutionWorker)
    carriers = []

    async def execute_inner(*args, **kwargs):
        with trace_operation("chat", kind="client"):
            carriers.append(compose_progress().trace_context)
        return CycleResult(run_id=claimed.run_id, action=action, execution_attempt=1, fencing_token=1)

    worker._execute_claimed = execute_inner
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            assert asyncio.run(worker.execute_claimed(claimed)).action == action
            assert runtime.force_flush()
            exported = {span.name: span for span in traces(server)}
            assert "agent.execute" in exported
            assert exported["agent.execute"].trace_id.hex() == "1" * 32
            status = next(attribute.value.string_value for attribute in exported["agent.execute"].attributes
                          if attribute.key == "blogapp.run.status")
            assert status == expected_status
            assert exported["chat"].parent_span_id == exported["agent.execute"].span_id
            assert carriers[0].split("-")[1] == "1" * 32
        finally:
            runtime.shutdown()


@pytest.mark.parametrize("delay", [0, .5])
def test_collector_failure_or_timeout_does_not_change_operation_result(delay):
    with collector(status=503, delay=delay) as (_, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint, "AGENT_OTEL_TIMEOUT_SECONDS": ".1"})
        try:
            started = time.monotonic()
            with trace_operation("agent.execute") as span:
                set_span_attributes(span, {"blogapp.run.status": "completed"})
                result = "completed"
            assert result == "completed"
            assert time.monotonic() - started < .5  # Export is off the run thread.
            runtime.force_flush(timeout_millis=500)
        finally:
            before = time.monotonic()
            runtime.shutdown()
            assert time.monotonic() - before < 1.5


def test_disabled_telemetry_creates_no_exporter_and_does_not_import_baggage():
    runtime = configure_telemetry({})
    assert runtime.provider is None
    with trace_operation("agent.execute", parent="untrusted-parent-with-private-data") as span:
        assert span is None
    assert current_traceparent() is None
    runtime.shutdown()


@pytest.mark.parametrize("endpoint", ["http://user:secret@localhost/v1/traces", "https://example.invalid/v1/traces?secret=private", "ftp://localhost/v1/traces"])
def test_explicit_collector_settings_reject_credentials_and_invalid_protocol_without_echo(endpoint):
    with pytest.raises(PortError) as raised:
        configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
    assert raised.value.code is AgentErrorCode.CONFIG_ERROR
    assert "secret" not in str(raised.value)


def test_real_tool_guard_and_article_retrieval_boundaries_export_nested_content_free_spans():
    from agent_core.budget.guard import BudgetGuard, CallResult
    from agent_core.budget.policy import BudgetPolicy
    from agent_core.budget.store import PolicyBudgetStore
    from agent_core.content.config import EmbeddingModelConfig
    from agent_core.ports import BudgetKind
    from agent_core.qa.retrieval import SnapshotRetriever

    private_query = "PRIVATE_QUERY_MUST_NOT_EXPORT"
    class EmptyIndex:
        async def search(self, *args, **kwargs):
            return []

    async def scenario():
        policy = BudgetPolicy()
        guard = BudgetGuard(PolicyBudgetStore(policy), policy, "trace-test")
        retriever = SnapshotRetriever(index=EmptyIndex(), embedding_provider=None,
                                      model_config=EmbeddingModelConfig("text-embedding-3-small", 1536))
        async def retrieve(_attempt):
            hits = await retriever.retrieve(private_query, article_id="article-1", article_revision=1, top_k=3)
            return CallResult(value=hits)
        with trace_operation("agent.execute"):
            result = await guard.guarded(action_id="retrieve", kind=BudgetKind.TOOL_CALL, call=retrieve)
        assert result.value == []

    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            asyncio.run(scenario())
            assert runtime.force_flush()
            exported = {span.name: span for span in traces(server)}
            assert {"agent.execute", "tool", "retrieval"} <= set(exported)
            assert exported["retrieval"].parent_span_id == exported["tool"].span_id
            assert exported["tool"].parent_span_id == exported["agent.execute"].span_id
            assert all(private_query.encode() not in payload for _, _, payload in server.payloads)
        finally:
            runtime.shutdown()


def test_profile_retrieval_wrapper_exports_a_span_without_profile_or_query_content(monkeypatch):
    from agent_core.profile.retrieval import ProfileRetriever, RetrievalBudget

    retriever = ProfileRetriever()
    # Protocol fixture: the test covers instrumentation, not semantic retrieval.
    monkeypatch.setattr(retriever, "retrieve", lambda *args, **kwargs: "retrieved")
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            result = asyncio.run(retriever.retrieve_async(
                None, "PRIVATE_PROFILE_QUERY", language="en", budget=RetrievalBudget(top_k=4, max_context_tokens=1800),
            ))
            assert result == "retrieved"
            assert runtime.force_flush()
            assert "retrieval" in {span.name for span in traces(server)}
            assert all(b"PRIVATE_PROFILE_QUERY" not in payload for _, _, payload in server.payloads)
        finally:
            runtime.shutdown()


def counter_points(server, name):
    """OTLP counters are cumulative; repeated exports are not new events."""
    result = {}
    for metric in metrics(server):
        if metric.name != name:
            continue
        for point in metric.sum.data_points:
            labels = tuple(sorted((item.key, item.value.string_value) for item in point.attributes))
            assert {key for key, _ in labels} <= {"operation", "status"}
            result[labels] = max(result.get(labels, 0), point.as_int)
    return result


async def guarded_chat(*, model_cap=2, token_cap=256, token_estimate=64, first_failure="429"):
    from agent_core.adapters.config import LlmProviderSettings
    from agent_core.adapters.openai_provider import OpenAiModelProvider
    from agent_core.budget.guard import BudgetGuard, CallResult
    from agent_core.budget.policy import BudgetPolicy
    from agent_core.budget.store import PolicyBudgetStore
    from agent_core.ports import BudgetKind, ModelRequest

    requests = []
    def transport(request):
        requests.append(request)
        if len(requests) == 1:
            if first_failure == "timeout":
                raise httpx.ReadTimeout("PRIVATE_TRANSPORT_ERROR", request=request)
            return httpx.Response(429, json={"error": "PRIVATE_PROVIDER_BODY"})
        stream = (
            'data: {"choices":[{"delta":{"content":"Public answer"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=stream.encode())

    policy = BudgetPolicy(max_model_calls=model_cap, max_total_tokens=token_cap, max_attempts_per_action=2)
    guard = BudgetGuard(PolicyBudgetStore(policy), policy, "public-retry-test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        provider = OpenAiModelProvider(LlmProviderSettings(api_key="test-only-never-sent", model="test-model"), client=client)
        request = ModelRequest(prompt="Public transport fixture", max_output_tokens=8)
        async def call(_attempt):
            response = await provider.complete(request)
            return CallResult(value=response, request=request)
        try:
            outcome = await guard.guarded(action_id="public-action", kind=BudgetKind.MODEL_CALL,
                                          token_estimate=token_estimate, call=call)
            return requests, outcome.value.text, None
        except PortError as error:
            return requests, None, error.code


def test_real_model_guard_retry_exports_admitted_retry_and_provider_error_separately():
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            requests, answer, error = asyncio.run(guarded_chat())
            assert len(requests) == 2 and answer == "Public answer" and error is None
            assert runtime.force_flush()
            assert counter_points(server, "blogapp.agent.call.retries") == {
                (("operation", "chat"), ("status", "provider_error")): 1}
            assert counter_points(server, "blogapp.agent.operation.errors") == {
                (("operation", "chat"), ("status", "provider_error")): 1}
            assert not counter_points(server, "blogapp.agent.call.admission.rejections")
            assert all(b"PRIVATE_PROVIDER_BODY" not in payload for _, _, payload in server.payloads)
        finally:
            runtime.shutdown()


@pytest.mark.parametrize("denial,expected_provider_status", [("model", "provider_error"), ("tokens", "timeout")])
def test_retry_admission_denial_does_not_count_a_callback_that_never_started(denial, expected_provider_status):
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            options = {"model_cap": 1} if denial == "model" else {"token_cap": 64, "first_failure": "timeout"}
            requests, answer, error = asyncio.run(guarded_chat(**options))
            assert len(requests) == 1 and answer is None and error is AgentErrorCode.BUDGET_EXHAUSTED
            assert runtime.force_flush()
            assert not counter_points(server, "blogapp.agent.call.retries")
            assert counter_points(server, "blogapp.agent.call.admission.rejections") == {
                (("operation", "chat"), ("status", "budget_exhausted")): 1}
            assert counter_points(server, "blogapp.agent.operation.errors") == {
                (("operation", "chat"), ("status", expected_provider_status)): 1}
            assert len([span for span in traces(server) if span.name == "chat"]) == 1
        finally:
            runtime.shutdown()


def test_model_admission_rejection_is_observable_without_creating_a_provider_span():
    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            requests, _, error = asyncio.run(guarded_chat(token_cap=64, token_estimate=65))
            assert not requests and error is AgentErrorCode.BUDGET_EXHAUSTED
            assert runtime.force_flush()
            assert traces(server) == []
            assert not counter_points(server, "blogapp.agent.operation.errors")
            assert not counter_points(server, "blogapp.agent.call.retries")
            assert counter_points(server, "blogapp.agent.call.admission.rejections") == {
                (("operation", "chat"), ("status", "budget_exhausted")): 1}
        finally:
            runtime.shutdown()


def test_real_tool_guard_retry_counter_counts_admitted_callbacks_not_unique_failures():
    from agent_core.budget.guard import BudgetGuard, CallResult
    from agent_core.budget.policy import BudgetPolicy
    from agent_core.budget.store import PolicyBudgetStore
    from agent_core.ports import BudgetKind

    async def scenario():
        calls = []
        policy = BudgetPolicy(max_tool_attempts=2, max_attempts_per_action=2)
        guard = BudgetGuard(PolicyBudgetStore(policy), policy, "public-tool-retry")
        async def call(attempt):
            calls.append(attempt)
            if attempt == 1:
                raise PortError(AgentErrorCode.PROVIDER_ERROR, "PRIVATE_TOOL_FAILURE", retryable=True)
            return CallResult(value="done")
        outcome = await guard.guarded(action_id="private-action-must-not-export", kind=BudgetKind.TOOL_CALL, call=call)
        assert outcome.value == "done" and calls == [1, 2]

    with collector() as (server, endpoint):
        runtime = configure_telemetry({"AGENT_OTEL_ENDPOINT": endpoint})
        try:
            asyncio.run(scenario())
            assert runtime.force_flush()
            assert counter_points(server, "blogapp.agent.call.retries") == {
                (("operation", "tool"), ("status", "provider_error")): 1}
            assert all(b"PRIVATE_TOOL_FAILURE" not in payload and b"private-action-must-not-export" not in payload
                       for _, _, payload in server.payloads)
        finally:
            runtime.shutdown()
