from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import time
import logging
from app.security.token_rate_limiter import UnifiedRateLimiter
from app.core.cache import cache

logger = logging.getLogger(__name__)

# Default rate limit: 50 requests per minute
DEFAULT_RATE_LIMIT = 50
DEFAULT_PERIOD = 60

limiter = None

async def get_redis_client():
    try:
        return cache.client
    except Exception as e:
        logger.warning("Redis client unavailable: %s", e)
        return None

async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware using UnifiedRateLimiter."""
    global limiter

    # Initialize limiter if needed
    if limiter is None:
        redis_client = await get_redis_client()
        limiter = UnifiedRateLimiter(redis_client=redis_client)

    # Identify user by client IP for rate limiting
    client_ip = request.client.host if request.client else "unknown"
    user_key = f"ip:{client_ip}"

    # Skip rate limiting for health checks or internal paths
    if request.url.path in ["/health", "/metrics", "/docs", "/openapi.json"]:
        return await call_next(request)

    # Check rate limit
    allowed = await limiter.check_limit(user_key, DEFAULT_RATE_LIMIT, DEFAULT_PERIOD)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "limit_type": "requests_per_minute",
                "retry_after": DEFAULT_PERIOD
            },
            headers={"Retry-After": str(DEFAULT_PERIOD)}
        )

    # Process request
    response = await call_next(request)

    # Add rate limit headers
    response.headers["X-RateLimit-Limit"] = str(DEFAULT_RATE_LIMIT)
    response.headers["X-RateLimit-Window"] = str(DEFAULT_PERIOD)

    return response
