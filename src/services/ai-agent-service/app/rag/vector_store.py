"""Compatibility shim — delegates to infrastructure.vector_store.chroma_adapter.

All new code should import directly from:
    app.infrastructure.vector_store.chroma_adapter (ChromaAdapter)
    app.domain.interfaces.i_vector_store          (VectorChunk, TextChunk)
"""

import warnings

from app.infrastructure.vector_store.chroma_adapter import ChromaAdapter
from app.domain.interfaces.i_vector_store import VectorChunk, TextChunk

warnings.warn(
    "app.rag.vector_store is deprecated. "
    "Use app.infrastructure.vector_store.chroma_adapter.ChromaAdapter instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Backward-compatible aliases
VectorStore = ChromaAdapter
StoredChunk = VectorChunk

# Global singleton instance (matches old module API)
vector_store = ChromaAdapter()
