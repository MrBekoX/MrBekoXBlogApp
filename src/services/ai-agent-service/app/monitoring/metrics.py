"""Prometheus metrics and helpers for AI agent observability."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge

# ==================== Anomaly Metrics ====================

anomalies_detected = Counter(
    "anomalies_detected_total",
    "Total anomalies detected",
    ["type", "severity"],
)

anomaly_scores = Histogram(
    "anomaly_detection_score",
    "Anomaly detection scores",
    buckets=[0.1, 0.3, 0.5, 0.7, 0.9, 1.0],
)

active_investigations = Gauge(
    "active_security_investigations",
    "Number of active security investigations",
)

user_request_rate = Histogram(
    "user_request_rate",
    "User request rate per minute",
    buckets=[1, 5, 10, 25, 50, 100, 250],
)

# ==================== Tool Invocation Metrics ====================

tool_invocations_total = Counter(
    "ai_tool_invocations_total",
    "Total tool invocations by tool and operation",
    ["tool", "operation", "outcome"],
)

tool_failures_total = Counter(
    "ai_tool_failures_total",
    "Total tool failures by reason",
    ["tool", "operation", "reason"],
)

tool_invocation_duration_seconds = Histogram(
    "ai_tool_invocation_duration_seconds",
    "Duration of tool invocations in seconds",
    ["tool", "operation"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# ==================== Worker Metrics ====================

worker_messages_total = Counter(
    "ai_worker_messages_total",
    "Total worker message processing outcomes",
    ["message_type", "outcome", "reason"],
)

worker_message_duration_seconds = Histogram(
    "ai_worker_message_duration_seconds",
    "Worker message processing duration in seconds",
    ["message_type", "outcome"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

consumer_running = Gauge(
    "ai_consumer_running",
    "Whether RabbitMQ consumer loop is running (1/0)",
)

consumer_last_message_unix = Gauge(
    "ai_consumer_last_message_unix_seconds",
    "Unix timestamp of last consumed message",
)

broker_queue_depth = Gauge(
    "ai_broker_queue_depth",
    "Current main queue depth (ready messages)",
    ["queue"],
)

broker_queue_consumers = Gauge(
    "ai_broker_queue_consumers",
    "Current consumer count for queue",
    ["queue"],
)

broker_backlog_over_threshold = Gauge(
    "ai_broker_backlog_over_threshold",
    "Whether queue backlog exceeds configured threshold (1/0)",
    ["queue"],
)

poison_messages_total = Counter(
    "ai_poison_messages_total",
    "Total poison/quarantine message actions",
    ["taxonomy", "action"],
)

runbook_hooks_total = Counter(
    "ai_runbook_hooks_total",
    "Runbook hook invocation outcomes",
    ["hook", "outcome"],
)

# ==================== Idempotency Metrics ====================

idempotency_replays_total = Counter(
    "ai_idempotency_replays_total",
    "Total idempotency replays by source",
    ["source"],
)

stage_cache_operations_total = Counter(
    "ai_stage_cache_operations_total",
    "Stage cache hits, misses, and stores",
    ["stage", "outcome"],
)

stale_processing_total = Counter(
    "ai_stale_processing_total",
    "Total stale processing records reclaimed after lock expiry",
    ["consumer"],
)

# ==================== HTTP Metrics ====================
http_requests_total = Counter(
    "ai_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "ai_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


def classify_failure_reason(error: Exception | str | None) -> str:
    """Normalize exception/reason text to low-cardinality categories."""
    if error is None:
        return "none"

    text = str(error).lower()
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if "circuit" in text and "open" in text:
        return "circuit_open"
    if "connection" in text or "network" in text or "unavailable" in text:
        return "connection_error"
    if "permission" in text or "forbidden" in text or "unauthorized" in text or "denied" in text:
        return "permission_denied"
    if "validation" in text or "invalid" in text:
        return "validation_error"
    if "not found" in text:
        return "not_found"
    if "rate limit" in text or "too many requests" in text or "429" in text:
        return "rate_limited"
    return "unknown_error"


def normalize_worker_reason(reason: str | None) -> str:
    """Normalize worker reason string for metrics labels."""
    if not reason:
        return "unknown"

    reason_lower = reason.lower()
    if reason_lower == "success":
        return "success"
    if reason_lower == "duplicate":
        return "duplicate"
    if reason_lower == "locked":
        return "locked"
    if reason_lower.startswith("malformed"):
        return "malformed"
    if reason_lower.startswith("non_recoverable"):
        base = reason_lower.split(":", 1)[1] if ":" in reason_lower else "non_recoverable"
        return f"non_recoverable_{base}"
    if reason_lower.startswith("transient"):
        base = reason_lower.split(":", 1)[1] if ":" in reason_lower else "transient"
        return f"transient_{base}"
    return classify_failure_reason(reason_lower)


def _status_family(status_code: int) -> str:
    if status_code < 100:
        return "unknown"
    return f"{status_code // 100}xx"


def record_tool_invocation(
    tool: str,
    operation: str,
    duration_seconds: float,
    error: Exception | str | None = None,
) -> None:
    """Record tool invocation metrics."""
    safe_duration = max(duration_seconds, 0.0)
    outcome = "success" if error is None else "error"
    tool_invocations_total.labels(tool=tool, operation=operation, outcome=outcome).inc()
    tool_invocation_duration_seconds.labels(tool=tool, operation=operation).observe(safe_duration)
    if error is not None:
        reason = classify_failure_reason(error)
        tool_failures_total.labels(tool=tool, operation=operation, reason=reason).inc()


def record_worker_message(
    message_type: str,
    outcome: str,
    reason: str,
    duration_seconds: float,
) -> None:
    """Record worker processing metrics."""
    normalized_reason = normalize_worker_reason(reason)
    normalized_outcome = outcome if outcome in {"success", "failure", "duplicate", "retry"} else "failure"
    safe_duration = max(duration_seconds, 0.0)
    worker_messages_total.labels(
        message_type=message_type,
        outcome=normalized_outcome,
        reason=normalized_reason,
    ).inc()
    worker_message_duration_seconds.labels(
        message_type=message_type,
        outcome=normalized_outcome,
    ).observe(safe_duration)


def set_consumer_running(is_running: bool) -> None:
    """Set RabbitMQ consumer running state."""
    consumer_running.set(1 if is_running else 0)


def set_consumer_last_message(timestamp_unix: float) -> None:
    """Set timestamp for last consumed message."""
    if timestamp_unix > 0:
        consumer_last_message_unix.set(timestamp_unix)


def set_broker_queue_depth(
    queue: str,
    message_count: int | None,
    consumer_count: int | None = None,
) -> None:
    """Set broker queue depth and consumer count gauges."""
    safe_queue = queue or "unknown"
    depth = max(0, int(message_count)) if message_count is not None else 0
    consumers = max(0, int(consumer_count)) if consumer_count is not None else 0
    broker_queue_depth.labels(queue=safe_queue).set(depth)
    broker_queue_consumers.labels(queue=safe_queue).set(consumers)


def set_broker_backlog_over_threshold(queue: str, is_over: bool) -> None:
    """Set broker backlog threshold gauge."""
    safe_queue = queue or "unknown"
    broker_backlog_over_threshold.labels(queue=safe_queue).set(1 if is_over else 0)


def record_poison_message(taxonomy: str, action: str) -> None:
    """Record poison message handling action."""
    safe_taxonomy = taxonomy or "unknown"
    safe_action = action or "unknown"
    poison_messages_total.labels(taxonomy=safe_taxonomy, action=safe_action).inc()


def record_runbook_hook(hook: str, outcome: str) -> None:
    """Record runbook hook result."""
    safe_hook = hook or "unknown"
    safe_outcome = outcome or "unknown"
    runbook_hooks_total.labels(hook=safe_hook, outcome=safe_outcome).inc()


def record_http_request(
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record HTTP request metrics."""
    safe_duration = max(duration_seconds, 0.0)
    status = _status_family(status_code)
    http_requests_total.labels(method=method, path=path, status=status).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(safe_duration)

def record_idempotency_replay(source: str) -> None:
    """Record a replay of a previously stored idempotent response."""
    safe_source = source or "unknown"
    idempotency_replays_total.labels(source=safe_source).inc()


def record_stage_cache(stage: str, outcome: str) -> None:
    """Record stage cache hit, miss, or store events."""
    safe_stage = stage or "unknown"
    safe_outcome = outcome or "unknown"
    stage_cache_operations_total.labels(stage=safe_stage, outcome=safe_outcome).inc()


def record_stale_processing_reclaim(consumer: str) -> None:
    """Record a stale processing claim that had to be reclaimed."""
    safe_consumer = consumer or "unknown"
    stale_processing_total.labels(consumer=safe_consumer).inc()
