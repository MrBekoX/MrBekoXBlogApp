import time
import logging
import redis.asyncio as redis
from typing import Optional

logger = logging.getLogger(__name__)

class UnifiedRateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        
    async def check_limit(self, key: str, limit: int, period: int) -> bool:
        """
        Generic token bucket/sliding window check using Redis.
        key: Unique identifier (IP or UserID)
        limit: Max requests
        period: Time window in seconds
        
        Returns: True if allowed, False if limited
        """
        if not self.redis:
            # Fallback if Redis is not available (e.g. strict debug/local without redis)
            # ideally should fail open or closed depending on policy. 
            # For now, logging warning and allowing.
            logger.warning("Redis not available for rate limiting. Allowing request.")
            return True

        current_time = int(time.time())
        window_start = current_time - period
        redis_key = f"rate_limit:{key}"
        
        try:
            # Redis pipeline for atomicity
            async with self.redis.pipeline(transaction=True) as pipe:
                # 1. Clean old records outside the window
                pipe.zremrangebyscore(redis_key, 0, window_start)
                
                # 2. Count requests in the current window
                pipe.zcard(redis_key)
                
                # 3. Add current request
                # We add it tentatively, but if count > limit we might want to skip adding 
                # (or add it and fail, which counts as a failed attempt that consumes quota)
                # Standard pattern: check count first.
                
                # Let's execute the clean & count first to see if we can proceed
                results = await pipe.execute()
                
                current_count = results[1]
                
                if current_count < limit:
                    # Allow
                    # Add current timestamp
                    await self.redis.zadd(redis_key, {str(current_time): current_time})
                    # Set expire to clean up key eventually
                    await self.redis.expire(redis_key, period + 1)
                    return True
                else:
                    # Limited
                    logger.warning(f"Rate limit exceeded for {key}: {current_count}/{limit}")
                    return False
                    
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail open or closed? Usually fail open to prevent service outage if Redis trips
            return True
