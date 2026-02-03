"""Redis cache client for idempotency and caching."""

import json
from typing import Any, Optional
import redis.asyncio as redis
from app.core.config import settings


class RedisCache:
    """Async Redis client wrapper for caching and distributed locking."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._client is None:
            self._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client, raise if not connected."""
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    # ==================== Idempotency Methods ====================

    async def is_processed(self, message_id: str) -> bool:
        """Check if a message has already been processed."""
        key = f"processed:event:{message_id}"
        return await self.client.exists(key) > 0

    async def mark_processed(self, message_id: str, ttl_seconds: int = 86400) -> None:
        """Mark a message as processed with TTL (default: 24 hours)."""
        key = f"processed:event:{message_id}"
        await self.client.set(key, "1", ex=ttl_seconds)

    async def acquire_lock(
        self, article_id: str, ttl_seconds: int = 300
    ) -> bool:
        """
        Try to acquire a distributed lock for an article.

        Args:
            article_id: The article ID to lock
            ttl_seconds: Lock timeout in seconds (default: 5 minutes)

        Returns:
            True if lock acquired, False if already locked
        """
        key = f"lock:article:{article_id}"
        # SETNX equivalent: set with nx=True
        result = await self.client.set(key, "locked", nx=True, ex=ttl_seconds)
        return result is not None

    async def release_lock(self, article_id: str) -> None:
        """Release the distributed lock for an article."""
        key = f"lock:article:{article_id}"
        await self.client.delete(key)

    # ==================== Caching Methods ====================

    async def get(self, key: str) -> Optional[str]:
        """Get a value from cache."""
        return await self.client.get(key)

    async def set(
        self, key: str, value: str, ttl_seconds: Optional[int] = None
    ) -> None:
        """Set a value in cache with optional TTL."""
        if ttl_seconds:
            await self.client.set(key, value, ex=ttl_seconds)
        else:
            await self.client.set(key, value)

    async def get_json(self, key: str) -> Optional[Any]:
        """Get a JSON value from cache."""
        data = await self.get(key)
        if data:
            return json.loads(data)
        return None

    async def set_json(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        """Set a JSON value in cache."""
        await self.set(key, json.dumps(value), ttl_seconds)

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        return await self.client.exists(key) > 0


# Global cache instance
cache = RedisCache()
