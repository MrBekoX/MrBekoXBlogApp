---
name: Re-ranking Strategy
description: Implement Cross-Encoder Re-ranking to improve precision of retrieved results.
---

# Re-ranking Strategy (Cross-Encoder)

This skill implements a Two-Stage Retrieval pipeline:
1.  **Retriever**: Fast, high-recall retrieval (Vector + BM25) to get top 50 candidates.
2.  **Re-ranker**: Slow, high-precision sorting using a Cross-Encoder to get top 5.

## Dependencies

- `sentence-transformers`
- `torch` (usually comes with sentence-transformers)

## Implementation Steps

### 1. Create `RerankingService`

Create `app/services/reranking_service.py`:

```python
from sentence_transformers import CrossEncoder

class RerankingService:
    def __init__(self, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"):
        # This model indicates how relevant a passage is to a query
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
        if not chunks:
            return []
            
        # Prepare pairs: (Query, Document_Context)
        pairs = [[query, c['content']] for c in chunks]
        
        # Predict scores
        scores = self._model.predict(pairs)
        
        # Assign scores
        for i, chunk in enumerate(chunks):
            chunk['rerank_score'] = float(scores[i])
            
        # Sort by rerank_score descending
        ranked_chunks = sorted(chunks, key=lambda x: x['rerank_score'], reverse=True)
        
        return ranked_chunks[:top_k]
```

### 2. Integrate into `RagService`

```python
async def retrieve_pipeline(self, query: str, k: int = 5):
    # 1. Retrieve more candidates (e.g., 3x K)
    candidates = await self.retrieve(query, k=k*3)
    
    # 2. Re-rank
    final_results = self._reranking_service.rerank(query, candidates, top_k=k)
    
    return final_results
```

## Performance Note
- Cross-Encoders are slower than Bi-Encoders.
- Use `ms-marco-MiniLM-L-6-v2` for a good speed/accuracy balance on CPU.
