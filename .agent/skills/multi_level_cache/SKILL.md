---
name: Multi-Level Cache Strategy
description: Implement L1 (Memory), L2 (Redis), and L3 (Semantic) caching.
---

# Multi-Level Cache Strategy

This skill defines a multi-level caching architecture to optimize performance and cost.

## Architecture

| Level | Type | Tech | Latency | Use Case |
|-------|------|------|---------|----------|
| **L1** | In-Memory | `cachetools` / Dict | <1ms | Frequently accessed, small data (e.g., configs, hot keys). |
| **L2** | Distributed | Redis | <100ms | Shared state, API responses, user sessions. |
| **L3** | Semantic | Vector Store | >100ms | Similar queries (Embeddings). Avoid re-running LLM for same intent. |

## Implementation Guide

Modify `app/core/cache.py` or create `app/core/multi_cache.py`.

### 1. `MultiLevelCache` Class

```python
from typing import Any, Optional
import json
from cachetools import TTLCache
from app.core.cache import RedisCache

class MultiLevelCache:
    def __init__(self, redis_cache: RedisCache):
        # L1: In-memory LRU Cache (max 1000 items, TTL 5 mins)
        self._l1_cache = TTLCache(maxsize=1000, ttl=300)
        self._l2_cache = redis_cache

    async def get(self, key: str) -> Optional[Any]:
        # Try L1
        if key in self._l1_cache:
            return self._l1_cache[key]
        
        # Try L2
        value = await self._l2_cache.get_json(key)
        if value:
            # Populate L1
            self._l1_cache[key] = value
        
        return value

    async def set(self, key: str, value: Any, ttl: int = 3600):
        # Set L1
        self._l1_cache[key] = value
        # Set L2
        await self._l2_cache.set_json(key, value, ttl_seconds=ttl)

    async def get_semantic(self, query_embedding: list[float], threshold: float = 0.95) -> Optional[Any]:
        # L3 Implementation
        # 1. Search vector store for cached_queries collection
        # 2. If similarity > threshold, return stored response
        pass
```

### 2. Semantic Cache (L3)

Requires a new collection in Vector Store specifically for queries.
```python
# In VectorStore
async def find_similar_query(self, embedding: list[float], threshold: float) -> Optional[dict]:
    # Search logic...
    pass
```
