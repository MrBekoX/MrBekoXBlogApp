---
name: Content Quality Scoring
description: Score RAG retrieval results for relevance and quality.
---

# Content Quality Scoring

This skill adds a scoring mechanism to evaluate the quality of retrieved RAG chunks before generating a response.

## Strategy

Calculate a weighted score based on:
1.  **Relevance**: Cosine similarity (from Vector Store).
2.  **Freshness**: If article dates are available.
3.  **Diversity**: Ensure chunks cover different parts of the document.

## Implementation Guide

```python
from dataclasses import dataclass
from typing import List
from app.domain.interfaces.i_vector_store import VectorChunk

@dataclass
class ScoredChunk:
    chunk: VectorChunk
    final_score: float

class RetrievalQualityScorer:
    def __init__(self, alpha: float = 0.7, beta: float = 0.3):
        self.alpha = alpha # Weight for Similarity
        self.beta = beta   # Weight for Diversity/Other

    def score(self, query: str, chunks: List[VectorChunk]) -> List[ScoredChunk]:
        scored = []
        for chunk in chunks:
            # Base score = Cosine Similarity
            relevance = chunk.similarity_score
            
            # Penalize very short chunks (low information density)
            density_penalty = 1.0
            if len(chunk.content) < 50:
                density_penalty = 0.5
            
            final_score = (relevance * self.alpha) * density_penalty
            
            scored.append(ScoredChunk(chunk, final_score))
            
        # Re-sort by final score
        return sorted(scored, key=lambda x: x.final_score, reverse=True)
```
