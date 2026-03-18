import logging
import time
import uuid

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class UnifiedRateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def check_limit(self, key: str, limit: int, period: int) -> bool:
        """Sliding-window rate limit backed by Redis. Fail closed when Redis is unavailable."""
        if not self.redis:
            logger.error("Redis not available for rate limiting; rejecting request")
            return False

        current_time_ms = int(time.time() * 1000)
        window_start_ms = current_time_ms - (period * 1000)
        redis_key = f"rate_limit:{key}"
        member = f"{current_time_ms}:{uuid.uuid4().hex}"

        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, 0, window_start_ms)
                pipe.zcard(redis_key)
                results = await pipe.execute()

            current_count = int(results[1])
            if current_count >= limit:
                logger.warning("Rate limit exceeded for %s: %s/%s", key, current_count, limit)
                return False

            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zadd(redis_key, {member: current_time_ms})
                pipe.expire(redis_key, period + 1)
                await pipe.execute()
            return True
        except Exception as exc:
            logger.error("Rate limiting error for %s: %s", key, exc)
            return False
