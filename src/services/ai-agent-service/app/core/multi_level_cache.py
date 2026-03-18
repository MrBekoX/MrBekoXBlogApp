"""Multi-level cache implementation (L1 Memory + L2 Redis)."""

import asyncio
import logging
import time
from typing import Any, Optional, Dict

from app.domain.interfaces.i_cache import ICache, CacheLockLease
from app.domain.interfaces.i_vector_store import IVectorStore

logger = logging.getLogger(__name__)


class SimpleLRUCache:
    """Thread-safe in-memory LRU cache backed by asyncio.Lock."""

    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: Dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._cache:
                return None
            value, expire_time = self._cache[key]
            if time.time() > expire_time:
                del self._cache[key]
                return None
            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            if len(self._cache) >= self.maxsize:
                del self._cache[next(iter(self._cache))]
            self._cache[key] = (value, time.time() + self.ttl)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()


class MultiLevelCache(ICache):
    """Coordinator for multi-level caching."""

    def __init__(self, redis_cache: ICache, vector_store: IVectorStore | None = None):
        self.l2 = redis_cache
        self.l3 = vector_store
        self.l1 = SimpleLRUCache(maxsize=1000, ttl=300)

    async def connect(self) -> None:
        await self.l2.connect()

    async def disconnect(self) -> None:
        await self.l2.disconnect()

    def is_connected(self) -> bool:
        attr = getattr(self.l2, "is_connected", False)
        return bool(attr() if callable(attr) else attr)

    async def get(self, key: str) -> str | None:
        val = await self.l1.get(key)
        if val is not None:
            return val
        val = await self.l2.get(key)
        if val is not None:
            await self.l1.set(key, val)
        return val

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        await self.l1.set(key, value)
        await self.l2.set(key, value, ttl_seconds)

    async def get_json(self, key: str) -> Any | None:
        val = await self.l1.get(key)
        if val is not None:
            return val
        val = await self.l2.get_json(key)
        if val is not None:
            await self.l1.set(key, val)
        return val

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        await self.l1.set(key, value)
        await self.l2.set_json(key, value, ttl_seconds)

    async def delete(self, key: str) -> None:
        # Invalidate L1 first so subsequent reads fall through to L2 immediately
        await self.l1.delete(key)
        await self.l2.delete(key)

    async def exists(self, key: str) -> bool:
        if await self.l1.get(key) is not None:
            return True
        return await self.l2.exists(key)

    async def get_semantic(self, query_embedding: list[float], threshold: float = 0.95) -> Any | None:
        if not self.l3:
            return None
        matches = self.l3.search_queries(query_embedding, k=1, threshold=threshold)
        if matches:
            logger.info("L3 Semantic Cache Hit (similarity=%.4f)", matches[0]["similarity"])
            return matches[0]["response"]
        return None

    async def set_semantic(self, query: str, embedding: list[float], response: Any, metadata: dict | None = None) -> None:
        if not self.l3:
            return
        self.l3.cache_query(query, embedding, response, metadata)
        logger.debug("L3 Semantic Cache Set")

    async def is_processed(self, message_id: str) -> bool:
        return await self.l2.is_processed(message_id)

    async def mark_processed(self, message_id: str, ttl_seconds: int = 86400) -> None:
        await self.l2.mark_processed(message_id, ttl_seconds)

    async def acquire_lock(self, resource_id: str, ttl_seconds: int = 300) -> CacheLockLease | None:
        return await self.l2.acquire_lock(resource_id, ttl_seconds)

    async def release_lock(self, lease: CacheLockLease) -> bool:
        return await self.l2.release_lock(lease)

    async def claim_operation(
        self,
        consumer_name: str,
        operation_id: str,
        message_id: str,
        correlation_id: str | None = None,
        lock_ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        return await self.l2.claim_operation(
            consumer_name,
            operation_id,
            message_id,
            correlation_id,
            lock_ttl_seconds,
        )

    async def get_operation(self, consumer_name: str, operation_id: str) -> dict[str, Any] | None:
        return await self.l2.get_operation(consumer_name, operation_id)

    async def store_operation_response(
        self,
        consumer_name: str,
        operation_id: str,
        response_payload: dict[str, Any],
        routing_key: str,
    ) -> None:
        await self.l2.store_operation_response(consumer_name, operation_id, response_payload, routing_key)

    async def mark_operation_completed(self, consumer_name: str, operation_id: str) -> None:
        await self.l2.mark_operation_completed(consumer_name, operation_id)

    async def mark_operation_retryable(self, consumer_name: str, operation_id: str, error: str) -> None:
        await self.l2.mark_operation_retryable(consumer_name, operation_id, error)

    async def mark_operation_failed(self, consumer_name: str, operation_id: str, error: str) -> None:
        await self.l2.mark_operation_failed(consumer_name, operation_id, error)
