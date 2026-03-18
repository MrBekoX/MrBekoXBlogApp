"""Logging utilities for secure credential handling and production debugging."""

import re
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlparse, urlunparse
from typing import Any, Optional
import json

# Context variable for request tracking (async-safe)
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_span_id_ctx: ContextVar[str] = ContextVar("span_id", default="")
_logger_configured = False


class RequestIdFilter(logging.Filter):
    """Inject correlation/request ID into all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id_ctx.get()
        span_id = _span_id_ctx.get()
        record.request_id = request_id if request_id else "-"
        record.span_id = span_id if span_id else "-"
        return True


def setup_logging(level: str = "INFO", service_name: str = "ai-agent-service") -> None:
    """
    Configure structured logging for production.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        service_name: Name of the service for log identification
    """
    global _logger_configured

    if _logger_configured:
        return

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - [corr=%(request_id)s span=%(span_id)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    request_id_filter = RequestIdFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(request_id_filter)

    # Configure JSON logging for production if environment variable is set
    import os
    if os.getenv("LOG_FORMAT", "text") == "json":
        # Setup JSON formatter (would need python-json-logger or custom)
        pass

    _logger_configured = True


def get_request_id() -> str:
    """Get or generate a request ID for tracing."""
    request_id = _request_id_ctx.get()
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        _request_id_ctx.set(request_id)
    return request_id


def set_request_id(request_id: str) -> None:
    """Set the request ID for tracing."""
    _request_id_ctx.set(request_id)


def clear_request_id() -> None:
    """Clear the request ID."""
    _request_id_ctx.set("")


def get_span_id() -> str:
    """Get the active span ID if available."""
    span_id = _span_id_ctx.get()
    return span_id or ""


def set_span_id(span_id: str) -> None:
    """Set the active span ID."""
    _span_id_ctx.set(span_id)


def clear_span_id() -> None:
    """Clear the active span ID."""
    _span_id_ctx.set("")


@contextmanager
def trace_span(name: str, **attributes: Any):
    """Lightweight span context for tracing in logs."""
    logger = logging.getLogger("app.trace")
    previous_span_id = _span_id_ctx.get()
    span_id = f"spn_{uuid.uuid4().hex[:12]}"
    _span_id_ctx.set(span_id)
    started_at = time.perf_counter()
    attrs = ", ".join(f"{k}={v}" for k, v in attributes.items()) if attributes else ""
    logger.info(f"[SPAN_START] {name}{' ' + attrs if attrs else ''}")
    try:
        yield span_id
        duration = time.perf_counter() - started_at
        logger.info(f"[SPAN_END] {name} duration_s={duration:.4f} status=ok")
    except Exception as exc:
        duration = time.perf_counter() - started_at
        # Enhanced error logging with type and repr for observability
        error_info = {
            "error_type": type(exc).__name__,
            "error_repr": repr(exc),
            "error_msg": str(exc),
        }
        logger.error(
            f"[SPAN_END] {name} duration_s={duration:.4f} status=error "
            f"error_type={error_info['error_type']} error={error_info['error_repr']}"
        )
        raise
    finally:
        _span_id_ctx.set(previous_span_id)


def log_structured(
    logger: logging.Logger,
    level: int,
    message: str,
    **kwargs: Any
) -> None:
    """
    Log a structured message with extra context for production debugging.

    Args:
        logger: Logger instance
        level: Logging level (logging.INFO, etc.)
        message: Log message
        **kwargs: Additional structured data to log
    """
    # Add request ID if available
    request_id = get_request_id()
    if request_id:
        kwargs["request_id"] = request_id

    # Add timestamp if not present
    if "timestamp" not in kwargs:
        import time
        kwargs["timestamp"] = time.time()

    # Sanitize sensitive data
    if "data" in kwargs and isinstance(kwargs["data"], dict):
        kwargs["data"] = sanitize_dict_urls(kwargs["data"])

    # Log with extra context
    logger.log(level, message, extra={"structured": kwargs})


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that automatically adds request ID and structured data.
    Usage:
        logger = StructuredLoggerAdapter(logging.getLogger(__name__), None)
        logger.info("Processing request", user_id="123", action="analyze")
    """

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Add request ID and structured data to log record."""
        request_id = get_request_id()
        if request_id:
            kwargs.setdefault("extra", {})["request_id"] = request_id

        # Handle structured data in extra
        if "extra" in kwargs and isinstance(kwargs["extra"], dict):
            structured = kwargs["extra"].get("structured", {})
            if structured:
                kwargs["extra"]["structured"] = sanitize_dict_urls(structured)

        return msg, kwargs


def get_logger(name: str) -> logging.LoggerAdapter:
    """
    Get a structured logger adapter for the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        StructuredLoggerAdapter instance
    """
    return StructuredLoggerAdapter(logging.getLogger(name), None)


def sanitize_url(url: str) -> str:
    """
    Remove credentials from a URL for safe logging.

    Examples:
        redis://:password@host:6379 -> redis://***@host:6379
        amqp://user:password@host:5672 -> amqp://***:***@host:5672
        postgresql://user:pass@host/db -> postgresql://***:***@host/db

    Args:
        url: URL that may contain credentials

    Returns:
        URL with credentials masked as ***
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # No credentials in URL
        if not parsed.username and not parsed.password:
            return url

        # Build masked netloc
        masked_parts = []

        if parsed.username:
            masked_parts.append("***")
        if parsed.password:
            masked_parts.append("***")

        masked_userinfo = ":".join(masked_parts) if masked_parts else ""

        # Reconstruct netloc with masked credentials
        if masked_userinfo:
            if parsed.port:
                masked_netloc = f"{masked_userinfo}@{parsed.hostname}:{parsed.port}"
            else:
                masked_netloc = f"{masked_userinfo}@{parsed.hostname}"
        else:
            masked_netloc = parsed.netloc

        # Reconstruct the full URL
        sanitized = urlunparse((
            parsed.scheme,
            masked_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))

        return sanitized

    except Exception:
        # If parsing fails, try regex fallback
        # Pattern: scheme://user:password@host or scheme://:password@host
        pattern = r'(://[^:]+:)[^@]+(@)'
        return re.sub(pattern, r'\1***\2', url)


def sanitize_dict_urls(data: dict, url_keys: list[str] | None = None) -> dict:
    """
    Sanitize URL fields in a dictionary for safe logging.

    Args:
        data: Dictionary that may contain URLs
        url_keys: List of keys to check for URLs (default: common URL key names)

    Returns:
        Dictionary with URL credentials masked
    """
    if url_keys is None:
        url_keys = [
            'url', 'redis_url', 'rabbitmq_url', 'database_url',
            'connection_string', 'dsn', 'uri', 'endpoint'
        ]

    result = data.copy()

    for key, value in result.items():
        if isinstance(value, str):
            # Check if key suggests it's a URL
            key_lower = key.lower()
            if any(url_key in key_lower for url_key in url_keys):
                result[key] = sanitize_url(value)
            # Also check if value looks like a URL
            elif '://' in value and '@' in value:
                result[key] = sanitize_url(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict_urls(value, url_keys)

    return result


def log_error_with_context(
    logger: logging.Logger,
    error: Exception,
    context: dict[str, Any],
    message: str = "Error occurred"
) -> None:
    """
    Log error with full context including exception type for observability.

    This ensures error logs are not empty and provide actionable debugging info.

    Args:
        logger: Logger instance to use
        error: The exception that occurred
        context: Additional context (operation, attempt, etc.)
        message: Custom message prefix

    Example:
        log_error_with_context(
            logger,
            timeout_error,
            {"operation": "rag_retrieve", "attempt": 2, "timeout_seconds": 15},
            "RAG retrieval failed"
        )
        # Logs: [ERROR] RAG retrieval failed: error_type=TimeoutError error_repr=TimeoutError() ...
    """
    error_info = {
        "error_type": type(error).__name__,
        "error_repr": repr(error),
        "error_msg": str(error)[:500],  # Truncate very long messages
    }

    # Sanitize any URLs in context
    safe_context = sanitize_dict_urls(context)

    # Build log message with structured info
    context_str = " ".join(f"{k}={v}" for k, v in safe_context.items())
    logger.error(
        f"{message}: error_type={error_info['error_type']} "
        f"error_repr={error_info['error_repr']} {context_str}"
    )
