---
name: Semantic Chunking Strategy
description: Implement Semantic Chunking using sentence similarity to preserve context.
---

# Semantic Chunking Strategy

This skill implements a "Smart" chunker that groups sentences based on their semantic similarity, rather than arbitrary character counts. This prevents splitting a cohesive thought in half.

## Dependencies

- `sentence-transformers`
- `numpy`
- `scikit-learn` (for cosine similarity efficient calc if needed)

## Implementation Steps

### 1. Create `SemanticChunker`

Create `app/services/semantic_chunker.py`:

```python
import re
import numpy as np
from sentence_transformers import SentenceTransformer

class SemanticChunker:
    def __init__(self, model_name="all-MiniLM-L6-v2", threshold_percentile=90):
        self._model = SentenceTransformer(model_name)
        self._threshold_percentile = threshold_percentile

    def chunk(self, text: str) -> list[str]:
        # 1. Split into sentences
        sentences = re.split(r'(?<=[.?!])\s+', text)
        if not sentences:
            return []
            
        # 2. Combine sentences with context (slide window) for embedding? 
        # Or just embed pure sentences.
        embeddings = self._model.encode(sentences)
        
        # 3. Calculate cosine distances between adjacent sentences
        distances = []
        for i in range(len(embeddings) - 1):
            sim = np.dot(embeddings[i], embeddings[i+1]) / (np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[i+1]))
            distance = 1 - sim
            distances.append(distance)
            
        # 4. Determine Threshold
        # Split where distance is high (similarity is low)
        threshold = np.percentile(distances, self._threshold_percentile)
        
        # 5. Group sentences
        chunks = []
        current_chunk = [sentences[0]]
        
        for i, dist in enumerate(distances):
            if dist > threshold:
                # Break point
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentences[i+1]]
            else:
                current_chunk.append(sentences[i+1])
                
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks
```

### 2. Update `IndexingService`

Replace the default `TextChunker` or `AdaptiveChunker` with `SemanticChunker`.

**Note:** This strategy requires re-indexing all documents.

## Benefits
- Context Integrity: Keeps related sentences together.
- Better Retrieval: Chunks are semantically "complete".
