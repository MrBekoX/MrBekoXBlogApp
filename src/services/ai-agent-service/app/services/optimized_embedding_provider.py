"""Optimized embedding provider with caching and batching support."""

import hashlib
import logging
import json
from typing import List

from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.core.cache import RedisCache

logger = logging.getLogger(__name__)

class OptimizedEmbeddingProvider(IEmbeddingProvider):
    """
    Decorator for IEmbeddingProvider that adds:
    1. Caching (Redis) to avoid re-computing embeddings for same text.
    2. Batching optimizations (handled via smart cache lookup).
    """

    def __init__(self, base_provider: IEmbeddingProvider, cache: RedisCache):
        self.provider = base_provider
        self.cache = cache
        self._dimensions = base_provider.dimensions

    async def initialize(self) -> None:
        """Initialize base provider."""
        await self.provider.initialize()

    async def shutdown(self) -> None:
        """Shutdown base provider."""
        await self.provider.shutdown()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text hash."""
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return f"emb:{self.provider.__class__.__name__}:{text_hash}"

    async def embed(self, text: str) -> List[float]:
        """Get embedding with cache check."""
        cache_key = self._get_cache_key(text)
        
        # 1. Check Cache
        cached_json = await self.cache.get(cache_key)
        if cached_json:
            return json.loads(cached_json)
            
        # 2. Compute
        embedding = await self.provider.embed(text)
        
        # 3. Store (TTL 7 days for embeddings as they are expensive)
        await self.cache.set_json(cache_key, embedding, ttl_seconds=604800)
        
        return embedding

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts with partial cache hits."""
        if not texts:
            return []
            
        cached_embeddings = {}
        missing_texts = []
        missing_indices = []

        # 1. Check Cache for all items
        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            cached_json = await self.cache.get(cache_key)
            
            if cached_json:
                cached_embeddings[i] = json.loads(cached_json)
            else:
                missing_texts.append(text)
                missing_indices.append(i)

        # 2. Compute Missing items in one batch
        if missing_texts:
            logger.info(f"Computing embeddings for {len(missing_texts)}/{len(texts)} missing items")
            new_embeddings = await self.provider.embed_batch(missing_texts)
            
            # 3. Store new items in Cache
            for i, emb in enumerate(new_embeddings):
                orig_index = missing_indices[i]
                cached_embeddings[orig_index] = emb
                
                text_hash = hashlib.sha256(missing_texts[i].encode('utf-8')).hexdigest()
                cache_key = f"emb:{self.provider.__class__.__name__}:{text_hash}"
                await self.cache.set_json(cache_key, emb, ttl_seconds=604800)

        # 4. Reconstruct Order
        return [cached_embeddings[i] for i in range(len(texts))]
