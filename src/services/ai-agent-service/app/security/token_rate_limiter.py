import asyncio
import time
import json
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)

@dataclass
class UserQuota:
    """Resource quota for a user."""
    tokens_per_minute: int = 10000
    requests_per_minute: int = 100
    concurrent_requests: int = 5
    cost_per_hour: float = 10.0
    max_execution_time: int = 120  # seconds

@dataclass
class UsageSnapshot:
    """Current usage snapshot."""
    tokens: int = 0
    requests: int = 0
    concurrent: int = 0
    execution_time: float = 0.0
    cost: float = 0.0
    window_start: float = field(default_factory=time.time)

class RateLimitError(Exception):
    """Rate limit exceeded error."""

    def __init__(self, message: str, limit_type: str, retry_after: int):
        super().__init__(message)
        self.message = message
        self.limit_type = limit_type
        self.retry_after = retry_after
    
    def __str__(self):
        return self.message

class TokenRateLimiter:
    """Multi-dimensional rate limiter."""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.memory_store: Dict[str, UsageSnapshot] = defaultdict(UsageSnapshot)
        self.active_requests: Dict[str, int] = defaultdict(int)
        self.lock = asyncio.Lock()

    async def check_limit(
        self,
        user_id: str,
        quota: Optional[UserQuota] = None
    ) -> bool:
        """Check if user is within quota limits."""
        if quota is None:
            quota = UserQuota()  # Default limits

        usage = await self._get_usage(user_id)
        concurrency = await self._get_concurrency(user_id)
        now = time.time()

        # Reset window if expired
        if now - usage.window_start > 60:
            await self._reset_window(user_id)
            # Re-fetch after reset
            usage = await self._get_usage(user_id)

        # Check all dimensions
        if usage.tokens >= quota.tokens_per_minute:
            logger.warning(f"User {user_id} exceeded token limit")
            raise RateLimitError(
                f"Token limit exceeded: {usage.tokens}/{quota.tokens_per_minute}",
                limit_type="tokens",
                retry_after=60
            )

        if usage.requests >= quota.requests_per_minute:
            logger.warning(f"User {user_id} exceeded request limit")
            raise RateLimitError(
                f"Request limit exceeded: {usage.requests}/{quota.requests_per_minute}",
                limit_type="requests",
                retry_after=60
            )

        if concurrency >= quota.concurrent_requests:
            logger.warning(f"User {user_id} has too many concurrent requests ({concurrency})")
            raise RateLimitError(
                f"Too many concurrent requests: {concurrency}/{quota.concurrent_requests}",
                limit_type="concurrent",
                retry_after=10
            )

        return True

    async def record_usage(
        self,
        user_id: str,
        tokens: int = 0,
        execution_time: float = 0.0
    ):
        """Record resource usage."""
        # Update Usage
        async with self.lock:
            # Memory update for fast local access / fallback
            usage = self.memory_store[user_id]
            usage.tokens += tokens
            usage.requests += 1
            usage.execution_time += execution_time
            
            # Redis update
            if self.redis:
                key = f"usage:{user_id}"
                # We need atomic increment here ideally, but for now simple get-set loop ok for this scale
                # Or we can use HINCRBY
                try:
                    pipeline = self.redis.pipeline()
                    pipeline.hincrby(key, "tokens", tokens)
                    pipeline.hincrby(key, "requests", 1)
                    # For float we fetch and set or store as scaled int. 
                    # Simplicity: just update structured object for now if complex.
                    # Using simplistic storage for this skill:
                    # Let's rely on _get_usage pulling logic or just update the object
                    
                    # Simplest robust way: update fields individually
                    await self.redis.hincrby(key, "tokens", tokens)
                    await self.redis.hincrby(key, "requests", 1)
                except Exception as e:
                    logger.error(f"Redis usage update failed: {e}")

        # Decrement concurrent count
        await self._decrement_concurrency(user_id)

    async def start_request(self, user_id: str):
        """Mark request as started (for concurrency tracking)."""
        async with self.lock:
            self.active_requests[user_id] += 1
            if self.redis:
                try:
                    await self.redis.incr(f"concurrency:{user_id}")
                except Exception as e:
                    logger.error(f"Redis concurrency incr failed: {e}")

    async def _decrement_concurrency(self, user_id: str):
        async with self.lock:
            self.active_requests[user_id] = max(0, self.active_requests[user_id] - 1)
            if self.redis:
                try:
                    val = await self.redis.decr(f"concurrency:{user_id}")
                    if val < 0:
                        await self.redis.set(f"concurrency:{user_id}", 0)
                except Exception as e:
                    logger.error(f"Redis concurrency decr failed: {e}")

    async def _get_concurrency(self, user_id: str) -> int:
        if self.redis:
            try:
                val = await self.redis.get(f"concurrency:{user_id}")
                return int(val) if val else 0
            except Exception:
                pass
        return self.active_requests[user_id]

    async def _get_usage(self, user_id: str) -> UsageSnapshot:
        """Get current usage for user."""
        if self.redis:
            try:
                data = await self.redis.hgetall(f"usage:{user_id}")
                if data:
                    window_str = data.get("window_start")
                    # If window is missing in Redis (expired key?), default to 0 (which triggers reset)
                    start = float(window_str) if window_str else 0.0
                    return UsageSnapshot(
                        tokens=int(data.get("tokens", 0)),
                        requests=int(data.get("requests", 0)),
                        window_start=start
                    )
            except Exception as e:
                logger.error(f"Redis get usage failed: {e}")
                
        return self.memory_store[user_id]

    async def _reset_window(self, user_id: str):
        """Reset usage window."""
        now = time.time()
        async with self.lock:
            self.memory_store[user_id] = UsageSnapshot(window_start=now)
            if self.redis:
                try:
                    pipe = self.redis.pipeline()
                    key = f"usage:{user_id}"
                    pipe.delete(key)
                    pipe.hset(key, mapping={
                        "tokens": 0, 
                        "requests": 0, 
                        "window_start": now
                    })
                    pipe.expire(key, 120) # Auto expire after 2 mins to be safe
                    await pipe.execute()
                except Exception as e:
                    logger.error(f"Redis reset window failed: {e}")
