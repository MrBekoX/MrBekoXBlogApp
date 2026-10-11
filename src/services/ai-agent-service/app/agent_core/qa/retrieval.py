"""Makale retrieval portu ve A3 indeksine dayalı gerçekleştirim (plan A4).

``ArticleRetriever`` QA akışının tek retrieval yüzeyidir: akış doğrudan
``InMemoryContentIndex``'e bağımlı değildir; üretimde B8 pgvector adaptörü
ve testlerde betimli double aynı portu doldurur. ``SnapshotRetriever``
bağlam doğrulamasından geçen snapshot'ı idempotent indeksler (aynı
revizyon + hash için embedding çağrısı yapılmaz) ve aramayı tek makaleyle
sınırlı filtrelerle koşar.

Web erişimi YOKTUR: bu port yalnız yerel/veritabanı içerik indeksini okur
(plan A4: "Bu aşamada web araçlarını çalıştırma").
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..content.config import EmbeddingModelConfig
from ..content.index import InMemoryContentIndex, IndexResult, SearchQuery
from ..content.models import IndexedChunk
from ..content.retrieval import SearchFilters
from ..models import ArticleSnapshot
from ..ports import CancellationToken, EmbeddingProvider

__all__ = ["ArticleRetriever", "SnapshotRetriever"]


@runtime_checkable
class ArticleRetriever(Protocol):
    """Makale bölüm araması portu; QA akışının tek retrieval yüzeyi."""

    async def ensure_indexed(
        self, snapshot: ArticleSnapshot, *, cancel: CancellationToken | None = None
    ) -> IndexResult:
        """Snapshot'ın akın indeksinde bulunmasını garanti eder (idempotent)."""
        ...

    async def retrieve(
        self,
        query: str,
        *,
        article_id: str,
        article_revision: int,
        top_k: int,
        cancel: CancellationToken | None = None,
    ) -> list[IndexedChunk]:
        """Sorguya en yakın bölümleri döndürür; sonuç yalnız istenen makaledendir."""
        ...


class SnapshotRetriever:
    """``InMemoryContentIndex`` üzerinde ``ArticleRetriever`` gerçekleştirim.

    Yalnız doğrulanmış snapshot indekslenir; arama filtreleri skorlamadan
    önce makale kimliğini ve yayın durumunu uygular (A3 kabul ölçütü).
    """

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        model_config: EmbeddingModelConfig,
        canonical_url_template: str | None = None,
        index: InMemoryContentIndex | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._model_config = model_config
        self._canonical_url_template = canonical_url_template
        self._index = index if index is not None else InMemoryContentIndex()

    @property
    def index(self) -> InMemoryContentIndex:
        return self._index

    async def ensure_indexed(
        self, snapshot: ArticleSnapshot, *, cancel: CancellationToken | None = None
    ) -> IndexResult:
        return await self._index.index_article(
            snapshot,
            embedding_provider=self._embedding_provider,
            model_config=self._model_config,
            canonical_url_template=self._canonical_url_template,
            cancel=cancel,
        )

    async def retrieve(
        self,
        query: str,
        *,
        article_id: str,
        article_revision: int,
        top_k: int,
        cancel: CancellationToken | None = None,
    ) -> list[IndexedChunk]:
        hits = await self._index.search(
            SearchQuery(
                text=query,
                filters=SearchFilters(article_ids=frozenset({article_id}), published=True),
                top_k=top_k,
            ),
            embedding_provider=self._embedding_provider,
            model_config=self._model_config,
            cancel=cancel,
        )
        return [hit.record for hit in hits]
