"""A3 içerik bölümleme ve hibrit retrieval paketi.

Genel akış: ``ArticleSnapshot`` → ``chunk_article`` (markdown hiyerarşi +
kod bloğu korumalı bölümleme, ortak anchor sözleşmesi) →
``InMemoryContentIndex.index_article`` (embedding + atomik yerleştirme,
idempotent) → ``InMemoryContentIndex.search`` (anlamsal + anahtar kelime
hibrit arama, filtreler skorlamadan önce) → ``remove_article`` (kaldırma iş
modeli, önbellek geçersizleme).

pgvector hedef sözleşmesi: ``pgvector.py`` + ``pgvector_schema.sql`` — B8'e
kadar çalıştırılmaz (görev sınır kararı).
"""

from .anchors import EMPTY_SLUG_FALLBACK, fold_text, heading_anchor, slugify_heading
from .chunking import PreparedChunk, chunk_article, embedded_text
from .config import INDEX_VERSION, ChunkingConfig, EmbeddingModelConfig
from .index import (
    InMemoryContentIndex,
    IndexResult,
    RemovalResult,
    SearchQuery,
    build_canonical_url,
)
from .models import AnchorSlug, IndexedChunk
from .pgvector import PgvectorContentIndex, PgvectorContentIndexStore
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
    "InMemoryContentIndex",
    "INDEX_VERSION",
    "IndexedChunk",
    "IndexResult",
    "PgvectorContentIndex",
    "PgvectorContentIndexStore",
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
