---
name: Adaptive RAG Chunking
description: Implement content-aware chunking strategy for better RAG performance.
---

# Adaptive RAG Chunking Strategy

This skill implements an adaptive chunking strategy for the `IndexingService`. The goal is to preserve the semantic integrity of the content by respecting document structure.

## Strategy

1.  **Code Blocks**: Detect code blocks (```...```) and keep them as single chunks. Do NOT split code in the middle.
2.  **Paragraphs**: Use semantic splitting for text. Split by headers first, then by paragraphs.
3.  **Lists**: Keep list items together if possible. If a list is too long, split by items, not arbitrary characters.

## Implementation Guide

Modify `app/services/indexing_service.py`.

### 1. Create `AdaptiveChunker` Class

```python
import re
from dataclasses import dataclass
from typing import List

@dataclass
class TextChunk:
    content: str
    chunk_index: int
    section_title: str | None

class AdaptiveChunker:
    """
    Adaptive chunking strategy based on content type.
    """
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> List[TextChunk]:
        chunks = []
        # 1. Split by Code Blocks to protect them
        # (Regex to split but keep delimiters)
        parts = re.split(r'(```[\s\S]*?```)', text)
        
        current_chunk_index = 0
        
        for part in parts:
            if part.startswith('```'):
                # It's a code block - keep it whole if possible, or split carefully
                chunks.append(TextChunk(
                    content=part, 
                    chunk_index=current_chunk_index,
                    section_title="Code Block" # You might want to track actual section context
                ))
                current_chunk_index += 1
            else:
                # Text content - delegate to semantic splitter
                text_chunks = self._chunk_text(part, current_chunk_index)
                chunks.extend(text_chunks)
                current_chunk_index += len(text_chunks)
                
        return chunks

    def _chunk_text(self, text: str, start_index: int) -> List[TextChunk]:
        # Implement paragraph and list awareness here
        # ...
        pass
```

### 2. Integration

Update `IndexingService` to use `AdaptiveChunker` instead of `TextChunker`.

```python
# app/services/indexing_service.py

class IndexingService:
    def __init__(self, ..., chunker: AdaptiveChunker | None = None):
        self._chunker = chunker or AdaptiveChunker()
```
