"""Shared content-index result and query contracts. Storage is PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import AgentErrorCode, PortError
from .retrieval import SearchFilters

__all__ = [
    "IndexResult",
    "RemovalResult",
    "SearchQuery",
    "build_canonical_url",
]


@dataclass(frozen=True)
class IndexResult:
    """``index_article`` sonucu; ``indexed=False`` idempotent atlamadır."""

    article_id: str
    article_revision: int
    chunk_count: int
    indexed: bool


@dataclass(frozen=True)
class RemovalResult:
    """``remove_article`` sonucu; stale kaldırma talebi ``removed=False`` döndürür."""

    article_id: str
    article_revision: int
    removed_chunks: int
    removed: bool


@dataclass(frozen=True)
class SearchQuery:
    """Tek arama çağrısının girdileri."""

    text: str
    filters: SearchFilters = SearchFilters()
    top_k: int = 8


def build_canonical_url(template: str, slug: str, anchor: str) -> str:
    """Makale URL şablonuna anchor fragment'ını ekler.

    Raises:
        PortError: ``validation_error`` — şablonda ``{slug}`` yer tutucusu yok.
    """

    if "{slug}" not in template:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "canonical URL şablonu {slug} yer tutucusu taşımalıdır",
            port="ContentIndex",
        )
    base = template.replace("{slug}", slug)
    if base.endswith("#") or not anchor:
        return base
    return f"{base}#{anchor}"
