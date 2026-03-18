"""Rate limiting configuration with thread-safe implementation."""

from typing import Tuple, Optional
import threading
import time
import logging

logger = logging.getLogger(__name__)

# Fix: Add thread-safe rate limiter with Lock
_rate_limiter_lock = threading.RLock()  # RLock for reentrant safety
_request_counts: dict[str, list[float]] = {}
_last_cleanup: float = 0
_cleanup_interval: float = 300  # Cleanup every 5 minutes

# Thread-safe rate limiter statistics
_stats_lock = threading.Lock()
_rate_limit_stats: dict[str, int] = {
    "total_checks": 0,
    "allowed": 0,
    "blocked": 0
}

RATE_LIMITS = {
    # Default limit if not specified
    "default": "20/minute",
    
    # High cost endpoints (LLM + RAG + Web Search)
    "/api/analyze": "10/minute",
    
    # Medium cost endpoints
    "/api/summarize": "20/minute",
    "/api/seo-description": "20/minute",
    "/api/keywords": "30/minute",
    "/api/sentiment": "30/minute",
    
    # Low cost endpoints
    "/api/reading-time": "60/minute", 
    "/api/geo-optimize": "15/minute", # Slightly higher cost than reading time
    "/api/collect-sources": "20/minute",
    
    # System endpoints
    "/health": "100/minute"
}

def parse_rate_limit(limit_str: str) -> Tuple[int, int]:
    """
    Parse a rate limit string (e.g. '10/minute') into (limit, period_in_seconds).

    Args:
        limit_str: String format like "10/minute", "5/second", "100/hour"

    Returns:
        Tuple of (limit_count, period_seconds)
    """
    try:
        count_str, period_str = limit_str.split("/")
        limit = int(count_str)

        period_str = period_str.lower()
        if period_str.startswith("second"):
            period = 1
        elif period_str.startswith("minute"):
            period = 60
        elif period_str.startswith("hour"):
            period = 3600
        elif period_str.startswith("day"):
            period = 86400
        else:
            period = 60 # Default to minute if unknown

        return limit, period
    except Exception:
        # Fallback
        return 10, 60


def check_rate_limit(identifier: str, limit_str: str, current_time: Optional[float] = None) -> bool:
    """
    Thread-safe rate limit check with automatic cleanup.

    Args:
        identifier: Unique identifier for the rate limit (e.g., user_id or IP)
        limit_str: Rate limit string (e.g. "10/minute")
        current_time: Current timestamp (uses time.time() if not provided)

    Returns:
        True if within rate limit, False if exceeded
    """
    global _last_cleanup

    if current_time is None:
        current_time = time.time()

    limit, period = parse_rate_limit(limit_str)
    key = f"{identifier}:{limit_str}"

    # Update statistics
    with _stats_lock:
        _rate_limit_stats["total_checks"] += 1

    with _rate_limiter_lock:
        # Periodic cleanup of old entries to prevent memory leaks
        if current_time - _last_cleanup > _cleanup_interval:
            _cleanup_old_entries(current_time)
            _last_cleanup = current_time

        # Clean up old requests outside the time window for this key
        if key in _request_counts:
            _request_counts[key] = [
                req_time for req_time in _request_counts[key]
                if current_time - req_time < period
            ]
        else:
            _request_counts[key] = []

        # Check if limit exceeded
        if len(_request_counts[key]) >= limit:
            with _stats_lock:
                _rate_limit_stats["blocked"] += 1
            return False

        # Add current request
        _request_counts[key].append(current_time)

        with _stats_lock:
            _rate_limit_stats["allowed"] += 1

        return True


def _cleanup_old_entries(current_time: float) -> None:
    """
    Clean up old entries from request counts to prevent memory leaks.
    This is called automatically during rate limit checks.
    """
    global _request_counts

    entries_before = len(_request_counts)
    _request_counts = {
        key: [
            req_time for req_time in times
            # Keep entries that are within the maximum period (1 day = 86400 seconds)
            if current_time - req_time < 86400
        ]
        for key, times in _request_counts.items()
        # Remove keys with no entries
        if times
    }
    entries_after = len(_request_counts)

    if entries_before > entries_after:
        logger.debug(f"Rate limiter cleanup: removed {entries_before - entries_after} stale entries")


def reset_rate_limit(identifier: str, limit_str: str) -> None:
    """
    Reset the rate limit for a specific identifier.
    Useful for testing or admin operations.

    Args:
        identifier: Unique identifier for the rate limit
        limit_str: Rate limit string (e.g. "10/minute")
    """
    key = f"{identifier}:{limit_str}"
    with _rate_limiter_lock:
        _request_counts.pop(key, None)


def get_rate_limit_stats() -> dict[str, int]:
    """
    Get rate limiting statistics for monitoring.

    Returns:
        Dictionary with stats: total_checks, allowed, blocked
    """
    with _stats_lock:
        return _rate_limit_stats.copy()


def get_active_keys_count() -> int:
    """
    Get the number of active rate limit keys being tracked.

    Returns:
        Number of unique keys in the rate limiter
    """
    with _rate_limiter_lock:
        return len(_request_counts)
