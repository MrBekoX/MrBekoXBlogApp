"""Multi-level cache implementation (L1 Memory + L2 Redis)."""

import time
import json
import logging
from typing import Any, Optional, Dict
from cachetools import TTLCache # We will implement a simple fallback if cachetools not available

from app.domain.interfaces.i_cache import ICache
from app.domain.interfaces.i_vector_store import IVectorStore

logger = logging.getLogger(__name__)

# Fallback basic LRU if cachetools is missing (though we'd prefer it)
class SimpleLRUCache:
    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: Dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        value, expire_time = self._cache[key]
        if time.time() > expire_time:
            del self._cache[key]
            return None
        return value

    def set(self, key: str, value: Any):
        if len(self._cache) >= self.maxsize:
            # Simple eviction: remove one arbitrary item (first key)
            # Real LRU would be better but this is a fallback for no deps
            del self._cache[next(iter(self._cache))]
        
        self._cache[key] = (value, time.time() + self.ttl)

    def delete(self, key: str):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()

class MultiLevelCache(ICache):
    """
    Coordinator for Multi-Level Caching.
    
    L1: In-Memory (Fastest, Local)
    L2: Redis (Distributed, Persistence)
    """

    async def connect(self) -> None:
        await self.l2.connect()
        # L3 (VectorStore) initialization is handled separately or we can trigger it here if needed
        # self.l3.initialize() happens in dependency container usually

    async def disconnect(self) -> None:
        await self.l2.disconnect()

    def __init__(self, redis_cache: ICache, vector_store: IVectorStore | None = None):
        self.l2 = redis_cache
        self.l3 = vector_store
        # L1 Configuration: 1000 items, 5 minutes default TTL
        self.l1 = SimpleLRUCache(maxsize=1000, ttl=300)

    # ==================== Basic Cache Operations ====================

    async def get(self, key: str) -> str | None:
        # Try L1
        val = self.l1.get(key)
        if val is not None:
            return val
        
        # Try L2
        val = await self.l2.get(key)
        if val is not None:
            # Populate L1
            self.l1.set(key, val)
        return val

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        # Set L1
        self.l1.set(key, value)
        # Set L2
        await self.l2.set(key, value, ttl_seconds)

    async def get_json(self, key: str) -> Any | None:
        # Try L1 (stores deserialized object)
        val = self.l1.get(key)
        if val is not None:
            return val
        
        # Try L2
        val = await self.l2.get_json(key)
        if val is not None:
            # Populate L1
            self.l1.set(key, val)
        return val

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        # Set L1 (store object)
        self.l1.set(key, value)
        # Set L2 (Redis requires serialization, handled by adapter)
        await self.l2.set_json(key, value, ttl_seconds)

    async def delete(self, key: str) -> None:
        self.l1.delete(key)
        await self.l2.delete(key)

    async def exists(self, key: str) -> bool:
        if self.l1.get(key) is not None:
            return True
        return await self.l2.exists(key)

    # ==================== L3 Semantic Cache Operations ====================

    async def get_semantic(self, query_embedding: list[float], threshold: float = 0.95) -> Any | None:
        """
        Get semantically similar cached response.
        
        Args:
            query_embedding: Embedding vector of the query
            threshold: Similarity threshold (0.0 to 1.0)
            
        Returns:
            Cached response object or None
        """
        if not self.l3:
            return None
            
        matches = self.l3.search_queries(query_embedding, k=1, threshold=threshold)
        if matches:
            logger.info(f"L3 Semantic Cache Hit (similarity={matches[0]['similarity']:.4f})")
            return matches[0]["response"]
            
        return None

    async def set_semantic(self, query: str, embedding: list[float], response: Any, metadata: dict | None = None) -> None:
        """
        Cache response semantically.
        
        Args:
            query: Original query text
            embedding: Embedding vector
            response: Response object to cache
            metadata: Optional metadata
        """
        if not self.l3:
            return
            
        self.l3.cache_query(query, embedding, response, metadata)
        logger.debug("L3 Semantic Cache Set")

    # ==================== Idempotency (Delegated to L2) ====================
    # Idempotency must be distributed

    async def is_processed(self, message_id: str) -> bool:
        return await self.l2.is_processed(message_id)

    async def mark_processed(self, message_id: str, ttl_seconds: int = 86400) -> None:
        await self.l2.mark_processed(message_id, ttl_seconds)

    # ==================== Distributed Locking (Delegated to L2) ====================
    # Locking must be distributed

    async def acquire_lock(self, resource_id: str, ttl_seconds: int = 300) -> bool:
        return await self.l2.acquire_lock(resource_id, ttl_seconds)

    async def release_lock(self, resource_id: str) -> None:
        await self.l2.release_lock(resource_id)
