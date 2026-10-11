"""B8 pgvector adaptör sözleşmesi (A3'te ÇALIŞTIRILMAZ, yalnız belgelenir).

SINIR KARARI (görev kapsamı): bu modül gerçek veritabanı bağlantısı
kurmaz; psycopg/asyncpg + pgvector driver'ı bağımlılık olarak eklenmez
(``pyproject.toml`` A2 sahipliğindedir). ``PgvectorContentIndex`` iskeleti
yapılandırmada ``config_error`` üretir; gerçek implementasyon, bağlantı
havuzu, migration ve yeniden indeksleme stratejisi B8 içerik senkronunda
doğrulanır.

Sözleşme kuralları:

- Şema: ``pgvector_schema.sql`` (``agent`` şeması, D011; vektör mesafe ve
  HNSW [PGVECTOR#C1]; FTS + RRF füzyonu [PGVECTOR#C2]).
- Metodlar ``InMemoryContentIndex`` ile aynı davranış sözleşmesini taşır:
  idempotent indeksleme, stale revizyon reddi, atomik revizyon geçişi,
  kaldırmada önbellek düşürme, model manifest doğrulaması.
- Filtreler SQL WHERE içinde uygulanır; skorlama filtrelenmemiş satırda
  yapılmaz (A3 kabul ölçütü).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..errors import AgentErrorCode, PortError
from .config import INDEX_VERSION

if TYPE_CHECKING:
    from ..models import ArticleSnapshot
    from .index import IndexResult, RemovalResult, SearchQuery
    from .config import EmbeddingModelConfig
    from ..ports import CancellationToken, EmbeddingProvider
    from .retrieval import ScoredChunk

__all__ = ["PgvectorContentIndexStore", "PgvectorContentIndex"]

SCHEMA_SQL_PATH = "pgvector_schema.sql"


@runtime_checkable
class PgvectorContentIndexStore(Protocol):
    """Sürücüye bağımlı alt katmanın (B8'de yazılacak) minimum yüzeyi."""

    async def upsert_article_chunks(
        self, records: list[Any], vectors: list[list[float]]
    ) -> int:
        """Parçaları tek transaction'da yazar; dönen değer yazılan satır sayısıdır."""
        ...

    async def delete_article(self, article_id: str, *, article_revision: int) -> int:
        """``article_revision >= $2`` koşuluyla siler; silinen satır sayısını döndürür."""
        ...

    async def search_hybrid(
        self,
        query_embedding: list[float],
        query_tsv: str,
        *,
        article_ids: list[str] | None,
        language: str | None,
        published: bool | None,
        top_k: int,
    ) -> list[tuple[Any, float, int | None, int | None]]:
        """Cosine sıralaması + FTS sıralamasını RRF ile birleştirip döndürür."""
        ...


class PgvectorContentIndex:
    """B8 hedef sözleşmesinin iskeleti; sürücü yoksa config_error üretir.

    Amaç, in-memory gerçekleştirimle aynı davranış sınırını B8'e devretmek
    ve sürücü bağımlılığını A3'te eklememektir. Hiçbir metod bağlantı
    açmaz.
    """

    is_test_double = False
    index_version = INDEX_VERSION

    def __init__(self, dsn: str | None = None, **_options: Any) -> None:
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            "pgvector adaptörü B8 içerik senkronunda uygulanacaktır; A3 "
            "sınır kararı gereği sürücü bağımlılığı eklenmedi. In-memory "
            "gerçekleştirim: agent_core.content.InMemoryContentIndex. Şema "
            f"sözleşmesi: agent_core.content.{SCHEMA_SQL_PATH}",
            port="PgvectorContentIndex",
        )

    async def index_article(
        self,
        snapshot: "ArticleSnapshot",
        *,
        embedding_provider: "EmbeddingProvider",
        model_config: "EmbeddingModelConfig",
        cancel: "CancellationToken | None" = None,
    ) -> "IndexResult":
        """B8: upsert_article_chunks + manifest doğrulaması; A3'te çağrılamaz."""
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            "pgvector adaptörü B8'de uygulanacaktır",
            port="PgvectorContentIndex",
        )

    async def remove_article(
        self, article_id: str, *, article_revision: int, cancel: "CancellationToken | None" = None
    ) -> "RemovalResult":
        """B8: delete_article + önbellek düşürme; A3'te çağrılamaz."""
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            "pgvector adaptörü B8'de uygulanacaktır",
            port="PgvectorContentIndex",
        )

    async def search(
        self,
        query: "SearchQuery",
        *,
        embedding_provider: "EmbeddingProvider",
        model_config: "EmbeddingModelConfig",
        cancel: "CancellationToken | None" = None,
    ) -> "list[ScoredChunk]":
        """B8: search_hybrid + filtre zorlaması; A3'te çağrılamaz."""
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            "pgvector adaptörü B8'de uygulanacaktır",
            port="PgvectorContentIndex",
        )
