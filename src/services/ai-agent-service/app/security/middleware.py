from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import time
import logging
from app.security.token_rate_limiter import TokenRateLimiter, UserQuota, RateLimitError
from app.core.cache import cache

logger = logging.getLogger(__name__)

# Initialize limiter with the Redis client from app.core.cache
# Note: cache.client property raises if not connected, so we should access it when needed or ensure connection.
# The limiter handles redis connection lazily/check in methods if passed.
# But cache.client is a property that returns the actual redis object.
# We will pass the cache instance wrapper or client. 
# TokenRateLimiter expects a redis-like object with get/set/hincrby.
# app.core.cache.RedisCache wraps it but methods mismatch.
# We will use cache.client but safeguard access.

limiter = TokenRateLimiter(redis_client=None) # We will inject the client in startup or assume global cache has it.

async def get_redis_client():
    try:
        return cache.client
    except:
        return None

# User tier configurations
USER_QUOTAS = {
    "free": UserQuota(
        tokens_per_minute=5000,
        requests_per_minute=50,
        concurrent_requests=3,
        cost_per_hour=5.0
    ),
    "premium": UserQuota(
        tokens_per_minute=20000,
        requests_per_minute=200,
        concurrent_requests=10,
        cost_per_hour=20.0
    ),
    "enterprise": UserQuota(
        tokens_per_minute=100000,
        requests_per_minute=1000,
        concurrent_requests=50,
        cost_per_hour=100.0
    ),
}

async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware."""
    # Ensure limiter has redis client if available
    if limiter.redis is None:
        try:
            limiter.redis = cache.client
        except:
            pass # Fallback to memory

    # Get user ID from JWT/header
    # For now, default to X-User-ID or generic IP/Anonymous
    user_id = request.headers.get("X-User-ID", "anonymous")
    user_tier = request.headers.get("X-User-Tier", "free")

    quota = USER_QUOTAS.get(user_tier, USER_QUOTAS["free"])

    try:
        # Check limits before processing
        await limiter.check_limit(user_id, quota)

        # Mark request started
        await limiter.start_request(user_id)

        # Process request
        start_time = time.time()
        response = await call_next(request)
        execution_time = time.time() - start_time

        # Estimate tokens (rough estimate: 4 chars per token)
        # Note: request.body() might be consumed already. 
        # In a real app we might need to inspect request state or use a hook.
        # For this implementation, we'll try to guess based on Content-Length header to avoid re-reading body stream issues.
        content_length_str = request.headers.get("content-length", "0")
        try:
            content_length = int(content_length_str)
        except:
            content_length = 0
            
        estimated_tokens = content_length // 4

        # Record usage
        await limiter.record_usage(user_id, estimated_tokens, execution_time)

        # Add rate limit headers
        try:
            usage = await limiter._get_usage(user_id)
            response.headers["X-RateLimit-Tokens-Remaining"] = str(
                max(0, quota.tokens_per_minute - usage.tokens)
            )
            response.headers["X-RateLimit-Requests-Remaining"] = str(
                max(0, quota.requests_per_minute - usage.requests)
            )
        except Exception:
            pass

        return response

    except RateLimitError as e:
        return JSONResponse(
            status_code=429,
            content={
                "error": e.message,
                "limit_type": e.limit_type,
                "retry_after": e.retry_after
            },
            headers={"Retry-After": str(e.retry_after)}
        )
