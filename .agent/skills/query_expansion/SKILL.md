---
name: Query Expansion Strategy
description: Implement Query Expansion using a Terminology Mapper to bridge the vocabulary gap.
---

# Query Expansion Strategy

This skill implements a solution for the "Vocabulary Mismatch" problem (e.g., User says "Frontend Cache", Article says "Layer 1").

## Implementation Steps

### 1. Create `QueryExpansionService`

Create `app/services/query_expansion_service.py`:

```python
import logging

class QueryExpansionService:
    def __init__(self):
        # Static synonyms map (Domain Knowledge)
        self._synonyms = {
            "frontend cache": ["katman 1", "client-side cache", "browser cache"],
            "backend cache": ["katman 2", "server-side cache"],
            "redis": ["katman 3", "distributed cache"],
            "yavaş": ["performans sorunu", "latency", "gecikme"],
            # ... add more from analysis ...
        }

    def expand_query(self, query: str) -> list[str]:
        """
        Generate variations of the query using synonyms.
        """
        query_lower = query.lower()
        variations = {query} # Use set to avoid duplicates
        
        for term, synonyms in self._synonyms.items():
            if term in query_lower:
                for syn in synonyms:
                    # Create variation by replacing term with synonym
                    variations.add(query_lower.replace(term, syn))
                    
        return list(variations)
```

### 2. Update `RagService`

Modify `retrieve` pipeline to use expanded queries.

```python
async def retrieve_expanded(self, query: str, ...):
    # 1. Expand query
    queries = self._expansion_service.expand_query(query)
    
    # 2. Retrieve for ALL queries (Multi-query retrieval)
    all_results = []
    for q in queries:
        results = await self.retrieve(q, ...)
        all_results.extend(results)
        
    # 3. Deduplicate based on Chunk ID
    unique_results = {r.id: r for r in all_results}.values()
    
    # 4. (Optional) Re-rank based on how many queries matched the chunk
    return list(unique_results)[:k]
```

## Benefits
- Increases Recall (catch documents that use different terminology).
- Solves "False Negatives" where semantic similarity is low due to exact term mismatch.
