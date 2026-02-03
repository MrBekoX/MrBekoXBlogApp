---
name: Embedding Optimization
description: Batch embedding and caching wrapper for cost/performance.
---

# Embedding Optimization

This skill optimizes embedding generation to reduce latency and API costs (if using remote models).

## Strategies

1.  **Batching**: Process multiple texts in a single API call/model pass.
2.  **Caching**: Store embeddings for text chunks to avoid re-computation.

## Implementation Guide

Update `app/domain/interfaces/i_embedding_provider.py` or implementation.

### Code Pattern

```python
import hashlib
from typing import List

class OptimizedEmbeddingProvider:
    def __init__(self, base_provider, cache):
        self.provider = base_provider
        self.cache = cache

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # 1. Check Cache
        cached_embeddings = {}
        missing_texts = []
        missing_indices = []

        for i, text in enumerate(texts):
            text_hash = hashlib.md5(text.encode()).hexdigest()
            cache_key = f"emb:{text_hash}"
            cached = await self.cache.get(cache_key)
            if cached:
                cached_embeddings[i] = cached
            else:
                missing_texts.append(text)
                missing_indices.append(i)

        # 2. Compute Missing
        if missing_texts:
            new_embeddings = await self.provider.embed_batch(missing_texts)
            
            # 3. Store in Cache
            for i, emb in enumerate(new_embeddings):
                orig_index = missing_indices[i]
                cached_embeddings[orig_index] = emb
                
                text_hash = hashlib.md5(missing_texts[i].encode()).hexdigest()
                await self.cache.set(f"emb:{text_hash}", emb)

        # 4. Reconstruct Order
        return [cached_embeddings[i] for i in range(len(texts))]
```
