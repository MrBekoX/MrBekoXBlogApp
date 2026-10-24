"""Markdown chunking, durable OpenAI vectors and hybrid article retrieval."""

from .anchors import EMPTY_SLUG_FALLBACK, fold_text, heading_anchor, slugify_heading
from .chunking import PreparedChunk, chunk_article, embedded_text
from .config import INDEX_VERSION, ChunkingConfig, EmbeddingModelConfig
from .index import (
    IndexResult,
    RemovalResult,
    SearchQuery,
    build_canonical_url,
)
from .models import AnchorSlug, IndexedChunk
from .postgres import PostgresContentIndex, PostgresEmbeddingCache
from .retrieval import (
    RRF_K,
    SearchCache,
    SearchFilters,
    ScoredChunk,
    cosine_similarity,
    rrf_fuse,
    tokenize,
)

__all__ = [
    "EMPTY_SLUG_FALLBACK",
    "AnchorSlug",
    "ChunkingConfig",
    "EmbeddingModelConfig",
    "INDEX_VERSION",
    "IndexedChunk",
    "IndexResult",
    "PostgresContentIndex",
    "PostgresEmbeddingCache",
    "PreparedChunk",
    "RRF_K",
    "RemovalResult",
    "ScoredChunk",
    "SearchCache",
    "SearchFilters",
    "SearchQuery",
    "build_canonical_url",
    "chunk_article",
    "cosine_similarity",
    "embedded_text",
    "fold_text",
    "heading_anchor",
    "rrf_fuse",
    "slugify_heading",
    "tokenize",
]
