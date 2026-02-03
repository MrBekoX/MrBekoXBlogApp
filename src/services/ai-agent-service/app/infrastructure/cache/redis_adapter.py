"""Redis cache adapter - Concrete implementation of ICache."""

import json
import logging
from typing import Any

import redis.asyncio as redis

from app.domain.interfaces.i_cache import ICache
from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisAdapter(ICache):
    """
    Redis implementation of cache interface.

    Supports:
    - Basic key-value caching with TTL
    - JSON serialization/deserialization
    - Distributed locking for concurrency control
    - Idempotency pattern for message processing
    """

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or settings.redis_url
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._client is None:
            logger.info(f"Connecting to Redis...")
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("Redis connection established")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis connection closed")

    @property
    def client(self) -> redis.Redis:
        """Get Redis client, raise if not connected."""
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    # ==================== Basic Cache Operations ====================

    async def get(self, key: str) -> str | None:
        """Get a string value from cache."""
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None = None
    ) -> None:
        """Set a string value in cache with optional TTL."""
        if ttl_seconds:
            await self.client.set(key, value, ex=ttl_seconds)
        else:
            await self.client.set(key, value)

    async def get_json(self, key: str) -> Any | None:
        """Get a JSON value from cache (deserialized)."""
        data = await self.get(key)
        if data:
            return json.loads(data)
        return None

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None
    ) -> None:
        """Set a JSON value in cache (serialized)."""
        await self.set(key, json.dumps(value), ttl_seconds)

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        return await self.client.exists(key) > 0

    # ==================== Idempotency Pattern ====================

    async def is_processed(self, message_id: str) -> bool:
        """Check if a message has already been processed."""
        key = f"processed:event:{message_id}"
        return await self.client.exists(key) > 0

    async def mark_processed(
        self,
        message_id: str,
        ttl_seconds: int = 86400
    ) -> None:
        """Mark a message as processed with TTL (default: 24 hours)."""
        key = f"processed:event:{message_id}"
        await self.client.set(key, "1", ex=ttl_seconds)

    # ==================== Distributed Locking ====================

    async def acquire_lock(
        self,
        resource_id: str,
        ttl_seconds: int = 300
    ) -> bool:
        """
        Try to acquire a distributed lock for a resource.

        Args:
            resource_id: The resource identifier to lock
            ttl_seconds: Lock timeout in seconds (default: 5 minutes)

        Returns:
            True if lock acquired, False if already locked
        """
        key = f"lock:resource:{resource_id}"
        # SETNX equivalent: set with nx=True
        result = await self.client.set(key, "locked", nx=True, ex=ttl_seconds)
        return result is not None

    async def release_lock(self, resource_id: str) -> None:
        """Release the distributed lock for a resource."""
        key = f"lock:resource:{resource_id}"
        await self.client.delete(key)
