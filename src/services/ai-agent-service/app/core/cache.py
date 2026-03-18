"""Redis cache client for idempotency and caching."""

import json
import logging
import secrets
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.domain.interfaces.i_cache import CacheLockLease

logger = logging.getLogger(__name__)

_LOCK_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisCache:
    """Async Redis client wrapper for caching and distributed locking."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    async def is_processed(self, message_id: str) -> bool:
        key = f"processed:event:{message_id}"
        return await self.client.exists(key) > 0

    async def mark_processed(self, message_id: str, ttl_seconds: int = 86400) -> None:
        key = f"processed:event:{message_id}"
        await self.client.set(key, "1", ex=ttl_seconds)

    async def acquire_lock(
        self, article_id: str, ttl_seconds: int = 300
    ) -> CacheLockLease | None:
        key = f"lock:article:{article_id}"
        token = secrets.token_urlsafe(32)
        result = await self.client.set(key, token, nx=True, ex=ttl_seconds)
        if result is None:
            return None
        return CacheLockLease(resource_id=article_id, token=token)

    async def release_lock(self, lease: CacheLockLease) -> bool:
        key = f"lock:article:{lease.resource_id}"
        try:
            deleted = await self.client.eval(_LOCK_RELEASE_SCRIPT, 1, key, lease.token)
        except Exception as exc:
            logger.warning("Legacy RedisCache lock release failed for %s: %s", lease.resource_id, exc)
            return False
        if int(deleted or 0) == 0:
            logger.warning("Legacy RedisCache skipped lock release for %s due to token mismatch", lease.resource_id)
            return False
        return True

    async def get(self, key: str) -> Optional[str]:
        return await self.client.get(key)

    async def set(
        self, key: str, value: str, ttl_seconds: Optional[int] = None
    ) -> None:
        if ttl_seconds:
            await self.client.set(key, value, ex=ttl_seconds)
        else:
            await self.client.set(key, value)

    async def get_json(self, key: str) -> Optional[Any]:
        data = await self.get(key)
        if data:
            return json.loads(data)
        return None

    async def set_json(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        await self.set(key, json.dumps(value), ttl_seconds)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        return await self.client.exists(key) > 0


cache = RedisCache()
