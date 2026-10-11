"""İçerik indeksi: bölümleme + embedding + hibrit arama (A3).

SINIR KARARI (görev kapsamı): gerçek veritabanı bağlantısı KURULMAZ. Bu
modül port arkasında in-memory gerçekleştirimdir; pgvector şeması ve B8
adaptör sözleşmesi ``pgvector.py`` + ``pgvector_schema.sql`` içinde
belgelenmiştir. Gerçek pgvector entegrasyonu ve yeniden indeksleme
stratejisinin üretimde doğrulanması B8 içerik senkronunun kapsamıdır.

Kabul ölçütlerinin karşılıkları:

- "Aynı içerik iki kez indekslenmiyor": aynı ``article_revision`` +
  ``content_hash`` ikinci ``index_article`` çağrısında embedding çağrısı
  yapılmadan atlanır.
- "Güncellenen makale yeni revizyonla bulunuyor": yeni revizyon, eski
  revizyonun parçalarını tek atamayla (atomik) değiştirir; okuyucular
  ya eski ya yeni durumu tam görür, karışık görünmez.
- "Bilinen kaldırma revizyonundan eski içerik getirilmiyor":
  ``remove_article`` bilinen revizyonu kaldırır ve önbelleği düşürür;
  daha eski revizyon için gelen kaldırma talebi stale sayılır.
- "İlgisiz parçalar ve farklı makalenin parçaları filtrelerden kaçamıyor":
  filtreler skorlamadan önce uygulanır (bkz. ``retrieval.SearchFilters``).
- Embedding modeli değişimi manifest karşılaştırmasıyla ``config_error``
  üretir; ``reindex`` tüm indeksi atomik yeniden kurar.

Mesaj eşlemesi: ``content.article.changed`` action=updated →
``index_article``; action=unpublished → ``remove_article``
(``src/contracts/agent/v1`` B1 sözleşmesi).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..errors import AgentErrorCode, PortError
from ..models import ArticleSnapshot
from ..ports import CancellationToken, EmbeddingProvider
from .anchors import fold_text
from .chunking import ChunkingConfig, PreparedChunk, chunk_article, embedded_text
from .config import INDEX_VERSION, EmbeddingModelConfig
from .models import IndexedChunk
from .retrieval import (
    SearchCache,
    SearchFilters,
    ScoredChunk,
    bm25_scores,
    cosine_similarity,
    rank_by_score,
    rrf_fuse,
    tokenize,
)

__all__ = [
    "IndexResult",
    "RemovalResult",
    "SearchQuery",
    "build_canonical_url",
    "InMemoryContentIndex",
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


@dataclass
class _ArticleEntry:
    """Tek makalenin indeks durumu; parça + vektör dizileri paraleldir."""

    revision: int
    content_hash: str
    published: bool
    chunks: list[IndexedChunk]
    vectors: list[list[float]]

    @property
    def article_id(self) -> str:
        return self.chunks[0].article_id


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


class InMemoryContentIndex:
    """Bölümleme + embedding + hibrit aramayı tek sınıfta birleştiren indeks.

    Aynı anda tek yazıcı varsayılır (B8 senkron sırası); okuyucular atomik
    sözlük ataması sayesinde kısmi makale durumu görmez.
    """

    def __init__(self, *, cache_capacity: int = 128) -> None:
        self._articles: dict[str, _ArticleEntry] = {}
        self._model_id: str | None = None
        self._dimensions: int | None = None
        self._cache = SearchCache(capacity=cache_capacity)

    # -- durum -----------------------------------------------------------

    @property
    def model_id(self) -> str | None:
        return self._model_id

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def index_version(self) -> int:
        return INDEX_VERSION

    def article_ids(self) -> list[str]:
        return sorted(self._articles)

    def chunk_count(self, article_id: str | None = None) -> int:
        if article_id is None:
            return sum(len(entry.chunks) for entry in self._articles.values())
        entry = self._articles.get(article_id)
        return len(entry.chunks) if entry else 0

    # -- yazma -----------------------------------------------------------

    async def index_article(
        self,
        snapshot: ArticleSnapshot,
        *,
        embedding_provider: EmbeddingProvider,
        model_config: EmbeddingModelConfig,
        chunk_config: ChunkingConfig | None = None,
        canonical_url_template: str | None = None,
        published: bool = True,
        cancel: CancellationToken | None = None,
    ) -> IndexResult:
        """Makaleyi böl, göm ve atomik olarak yerleştir (idempotent).

        Aynı revision + content_hash → atlama; aynı revision farklı hash
        veya daha eski revision → ``stale_snapshot``; daha yeni revision →
        eski parçaların tamamının değişimi (tek atama).

        Raises:
            PortError: ``validation_error`` (URL şablonu), ``stale_snapshot``,
                ``config_error`` (embedding modeli değişti),
                ``provider_error`` (embed sözleşme ihlali), ``cancelled``.
        """

        if cancel is not None:
            cancel.raise_if_cancelled()
        self._ensure_model(model_config)
        existing = self._articles.get(snapshot.article_id)
        if existing is not None and snapshot.article_revision == existing.revision:
            if existing.content_hash == snapshot.content_hash:
                return IndexResult(
                    article_id=snapshot.article_id,
                    article_revision=existing.revision,
                    chunk_count=len(existing.chunks),
                    indexed=False,
                )
            raise PortError(
                AgentErrorCode.STALE_SNAPSHOT,
                "aynı article_revision farklı content_hash ile gelemez; "
                "revizyon yayın anı kimliğidir (W0 §1.4)",
                port="ContentIndex",
            )
        if existing is not None and snapshot.article_revision < existing.revision:
            raise PortError(
                AgentErrorCode.STALE_SNAPSHOT,
                (
                    f"geç gelen eski revizyon: mevcut {existing.revision}, "
                    f"gelen {snapshot.article_revision}"
                ),
                port="ContentIndex",
            )
        prepared = chunk_article(
            snapshot, chunk_config or ChunkingConfig.for_model(model_config)
        )
        texts = [embedded_text(p.heading_path, p.chunk.content) for p in prepared]
        vectors = await self._embed_checked(
            embedding_provider, texts, model_config.dimensions, cancel
        )
        records = self._build_records(
            snapshot, prepared, canonical_url_template, published
        )
        self._articles[snapshot.article_id] = _ArticleEntry(
            revision=snapshot.article_revision,
            content_hash=snapshot.content_hash,
            published=published,
            chunks=records,
            vectors=vectors,
        )
        self._cache.invalidate_article(snapshot.article_id)
        return IndexResult(
            article_id=snapshot.article_id,
            article_revision=snapshot.article_revision,
            chunk_count=len(records),
            indexed=True,
        )

    async def remove_article(
        self,
        article_id: str,
        *,
        article_revision: int,
        cancel: CancellationToken | None = None,
    ) -> RemovalResult:
        """Kaldırma iş modelini işler: parçaları ve ilgili önbelleği düşürür.

        ``article_revision``, kaldırma olayının taşıdığı bilinen revizyondur
        (B1 ``content.article.changed`` action=unpublished). Daha eski
        revizyon için gelen kaldırma stale sayılır ve içerik dokunulmaz;
        makale yoksa idempotent ``removed=False`` döndürülür (senkron tekrar
        teslim güvenli olur).
        """

        if cancel is not None:
            cancel.raise_if_cancelled()
        existing = self._articles.get(article_id)
        if existing is None or article_revision < existing.revision:
            return RemovalResult(
                article_id=article_id,
                article_revision=article_revision,
                removed_chunks=0,
                removed=False,
            )
        del self._articles[article_id]
        self._cache.invalidate_article(article_id)
        return RemovalResult(
            article_id=article_id,
            article_revision=article_revision,
            removed_chunks=len(existing.chunks),
            removed=True,
        )

    async def reindex(
        self,
        snapshots: Sequence[ArticleSnapshot],
        *,
        embedding_provider: EmbeddingProvider,
        model_config: EmbeddingModelConfig,
        canonical_url_template: str | None = None,
        cancel: CancellationToken | None = None,
    ) -> list[IndexResult]:
        """Embedding modeli değiştiğinde indeksi sıfırdan atomik kurar.

        Yeni durum önce yan yapıda kurulur; hata durumunda mevcut indeks
        dokunulmaz. Başarıda tek atamayla değiştirilir ve önbellek boşalır.
        """

        if cancel is not None:
            cancel.raise_if_cancelled()
        chunk_config = ChunkingConfig.for_model(model_config)
        new_articles: dict[str, _ArticleEntry] = {}
        results: list[IndexResult] = []
        for snapshot in snapshots:
            prepared = chunk_article(snapshot, chunk_config)
            texts = [embedded_text(p.heading_path, p.chunk.content) for p in prepared]
            vectors = await self._embed_checked(
                embedding_provider, texts, model_config.dimensions, cancel
            )
            records = self._build_records(snapshot, prepared, canonical_url_template, True)
            new_articles[snapshot.article_id] = _ArticleEntry(
                revision=snapshot.article_revision,
                content_hash=snapshot.content_hash,
                published=True,
                chunks=records,
                vectors=vectors,
            )
            results.append(
                IndexResult(
                    article_id=snapshot.article_id,
                    article_revision=snapshot.article_revision,
                    chunk_count=len(records),
                    indexed=True,
                )
            )
        self._articles = new_articles
        self._model_id = model_config.model_id
        self._dimensions = model_config.dimensions
        self._cache.clear()
        return results

    # -- okuma -----------------------------------------------------------

    async def search(
        self,
        query: SearchQuery,
        *,
        embedding_provider: EmbeddingProvider,
        model_config: EmbeddingModelConfig,
        cancel: CancellationToken | None = None,
    ) -> list[ScoredChunk]:
        """Hibrit arama: filtrele → anlamsal + BM25 sırala → RRF füzyonu.

        Raises:
            PortError: ``validation_error`` — boş sorgu veya ``top_k < 1``;
                ``config_error`` — embedding modeli indeksten farklı;
                ``cancelled``.
        """

        if cancel is not None:
            cancel.raise_if_cancelled()
        if not query.text.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "sorgu metni boş olamaz",
                port="ContentIndex",
            )
        if query.top_k < 1:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "top_k en az 1 olmalıdır",
                port="ContentIndex",
            )
        self._ensure_model(model_config)
        cache_key = (
            fold_text(query.text.strip()),
            query.filters.cache_key(),
            query.top_k,
            model_config.model_id,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            resolved_hits: list[ScoredChunk] = []
            for hit in cached:
                current = self._resolve(
                    hit.record.article_id, hit.record.article_revision, hit.record.chunk_index
                )
                if current is None:
                    resolved_hits = []
                    break
                resolved_hits.append(
                    ScoredChunk(
                        record=current, score=hit.score,
                        semantic_rank=hit.semantic_rank, keyword_rank=hit.keyword_rank,
                    )
                )
            if resolved_hits:
                return resolved_hits
        candidates = self._filtered_records(query.filters)
        if not candidates:
            return []
        query_vector = (
            await self._embed_checked(
                embedding_provider, [query.text.strip()], model_config.dimensions, cancel
            )
        )[0]
        semantic_scores = [
            cosine_similarity(query_vector, vector)
            for vector in (self._vector_of(record) for record in candidates)
        ]
        query_tokens = tokenize(query.text)
        keyword_scores = bm25_scores(
            query_tokens, [self._document_tokens(record) for record in candidates]
        )
        semantic_ranked = rank_by_score(semantic_scores, candidates)
        keyword_ranked = rank_by_score(keyword_scores, candidates)
        fused = rrf_fuse(semantic_ranked, keyword_ranked)
        ordered = sorted(fused.items(), key=lambda item: (-item[1][0], item[0]))
        results: list[ScoredChunk] = []
        for (article_id, revision, chunk_index), (score, sem_rank, kw_rank) in ordered[
            : query.top_k
        ]:
            record = self._resolve(article_id, revision, chunk_index)
            if record is None:
                continue
            results.append(
                ScoredChunk(record=record, score=score, semantic_rank=sem_rank, keyword_rank=kw_rank)
            )
        article_ids = frozenset(result.record.article_id for result in results)
        self._cache.put(cache_key, article_ids, results)
        return results

    # -- iç yardımcılar --------------------------------------------------

    def _ensure_model(self, model_config: EmbeddingModelConfig) -> None:
        if self._model_id is None:
            self._model_id = model_config.model_id
            self._dimensions = model_config.dimensions
            return
        if self._model_id != model_config.model_id or self._dimensions != model_config.dimensions:
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                (
                    f"embedding modeli değişti: indeks {self._model_id!r}"
                    f"({self._dimensions} boyut), istek {model_config.model_id!r}"
                    f"({model_config.dimensions} boyut). reindex() ile indeksi "
                    "yeniden kurun."
                ),
                port="ContentIndex",
            )

    def _build_records(
        self,
        snapshot: ArticleSnapshot,
        prepared: list[PreparedChunk],
        canonical_url_template: str | None,
        published: bool,
    ) -> list[IndexedChunk]:
        records: list[IndexedChunk] = []
        for item in prepared:
            url = (
                build_canonical_url(canonical_url_template, snapshot.slug, item.anchor)
                if canonical_url_template is not None
                else None
            )
            records.append(
                IndexedChunk(
                    chunk=item.chunk,
                    content_hash=snapshot.content_hash,
                    heading_path=list(item.heading_path),
                    anchor=item.anchor,
                    language=snapshot.language,
                    published=published,
                    canonical_url=url,
                )
            )
        return records

    async def _embed_checked(
        self,
        provider: EmbeddingProvider,
        texts: list[str],
        dimensions: int,
        cancel: CancellationToken | None,
    ) -> list[list[float]]:
        if not texts:
            return []
        vectors = await provider.embed(texts, cancel=cancel)
        if len(vectors) != len(texts):
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "embed girdi sırasını korumadı: girdi ve çıktı sayısı farklı",
                port="ContentIndex",
            )
        for vector in vectors:
            if len(vector) != dimensions:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"embed boyutu beklenmedik: {len(vector)} != {dimensions}",
                    port="ContentIndex",
                )
        return [list(vector) for vector in vectors]

    def _filtered_records(self, filters: SearchFilters) -> list[IndexedChunk]:
        return [
            record
            for entry in self._articles.values()
            for record in entry.chunks
            if filters.allows(record)
        ]

    def _resolve(
        self, article_id: str, revision: int, chunk_index: int
    ) -> IndexedChunk | None:
        entry = self._articles.get(article_id)
        if entry is None or entry.revision != revision:
            return None
        if 0 <= chunk_index < len(entry.chunks):
            record = entry.chunks[chunk_index]
            if record.chunk.chunk_index == chunk_index:
                return record
        return None

    def _vector_of(self, record: IndexedChunk) -> list[float]:
        entry = self._articles[record.article_id]
        return entry.vectors[record.chunk.chunk_index]

    def _document_tokens(self, record: IndexedChunk) -> list[str]:
        context = " ".join(record.heading_path)
        return tokenize(f"{context}\n{record.chunk.content}")
