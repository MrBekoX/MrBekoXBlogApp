---
name: Hybrid Search Strategy
description: Implement Hybrid Search combining Dense (Vector) and Sparse (BM25) retrieval for better recall.
---

# Hybrid Search Strategy (Dense + Sparse)

This skill implements a Hybrid Search pipeline that combines:
1.  **Dense Retrieval**: Vector search using ChromaDB (good for semantic meaning).
2.  **Sparse Retrieval**: Keyword search using BM25 (good for exact matches).

## Dependencies

- `rank_bm25`
- `numpy`

## Implementation Steps

### 1. Create `BM25Index` Service

Create `app/services/bm25_index.py`:

```python
from rank_bm25 import BM25Okapi
import numpy as np
import logging

logger = logging.getLogger(__name__)

class BM25Index:
    """
    In-memory BM25 index for sparse retrieval.
    """
    def __init__(self):
        self._indices: dict[str, BM25Okapi] = {}  # post_id -> BM25
        self._lookups: dict[str, list[dict]] = {} # post_id -> list of chunks

    def index_document(self, post_id: str, chunks: list[dict]) -> None:
        """Create index for a document's chunks."""
        tokenized_corpus = [c['content'].lower().split() for c in chunks]
        self._indices[post_id] = BM25Okapi(tokenized_corpus)
        self._lookups[post_id] = chunks
        logger.info(f"Indexed {len(chunks)} chunks for post {post_id} in BM25")

    async def search(self, query: str, post_id: str, k: int = 10) -> list[dict]:
        """Search specific post using BM25."""
        if post_id not in self._indices:
            return []
            
        bm25 = self._indices[post_id]
        chunks = self._lookups[post_id]
        
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)
        
        # Get top-k indices
        top_n = np.argsort(scores)[::-1][:k]
        
        results = []
        for idx in top_n:
            if scores[idx] > 0:
                results.append({
                    **chunks[idx],
                    'score': float(scores[idx]),
                    'type': 'sparse'
                })
                
        return results
```

### 2. Implement Hybrid Fusion

In `RagService`, implement Reciprocal Rank Fusion (RRF) or Weighted Sum to combine results.

```python
def fuse_results(self, dense_results, sparse_results, alpha=0.5):
    """
    Combine dense and sparse results.
    alpha: Weight for dense score (0.0 to 1.0).
    """
    # Normalize scores first (Min-Max normalization)
    # ... implementation details ...
    
    # Merge by chunk ID
    merged = {}
    
    for r in dense_results:
        merged[r['id']] = {'chunk': r, 'dense_score': r['score'], 'sparse_score': 0}
        
    for r in sparse_results:
        if r['id'] in merged:
            merged[r['id']]['sparse_score'] = r['score']
        else:
            merged[r['id']] = {'chunk': r, 'dense_score': 0, 'sparse_score': r['score']}
            
    # Calculate final score
    final_results = []
    for id, data in merged.items():
        final_score = (alpha * data['dense_score']) + ((1-alpha) * data['sparse_score'])
        data['chunk']['final_score'] = final_score
        final_results.append(data['chunk'])
        
    return sorted(final_results, key=lambda x: x['final_score'], reverse=True)
```

## Usage

1.  When indexing chunks in `IndexingService`, also send them to `BM25Index`.
2.  In `RagService.retrieve`, call both `vector_store.search` and `bm25_index.search`.
3.  Fuse results and return top K.
