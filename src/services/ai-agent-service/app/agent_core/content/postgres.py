"""Durable, article-scoped semantic retrieval on PostgreSQL.

Vectors are real OpenAI embeddings stored as PostgreSQL real[] values. Searches
load only the requested articles and use cosine/BM25 reciprocal rank fusion.
This deliberately avoids a second database or a PostgreSQL extension on the
small EC2 host. Unscoped scans are rejected instead of loading the whole corpus.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import wraps
from typing import Any

import asyncpg

from ..errors import AgentErrorCode, PortError
from ..models import ArticleChunk, ArticleSnapshot, compute_content_hash
from ..ports import CancellationToken, EmbeddingProvider
from .chunking import chunk_article, embedded_text
from .config import INDEX_VERSION, ChunkingConfig, EmbeddingModelConfig
from .index import IndexResult, RemovalResult, SearchQuery, build_canonical_url
from .models import IndexedChunk
from .retrieval import ScoredChunk, bm25_scores, cosine_similarity, rank_by_score, rrf_fuse, tokenize


def _schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Invalid agent database schema")
    return f'"{value}"'


def _cancel(token: CancellationToken | None) -> None:
    if token is not None:
        token.raise_if_cancelled()


def validate_vectors(vectors: list[list[float]], count: int, dimensions: int) -> None:
    if len(vectors) != count or any(
        len(vector) != dimensions or any(type(value) not in (float, int) or not math.isfinite(value) for value in vector)
        or not any(vector) for vector in vectors
    ):
        raise PortError(AgentErrorCode.PROVIDER_ERROR, "Invalid embedding response", port="ContentIndex")


def _database_errors(method):
    @wraps(method)
    async def guarded(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except (asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError,
                asyncpg.SerializationError, asyncpg.DeadlockDetectedError, OSError, TimeoutError):
            raise PortError(AgentErrorCode.PROVIDER_ERROR, "Semantic storage is temporarily unavailable",
                            port="ContentIndex", retryable=True) from None
    return guarded


class PostgresEmbeddingCache:
    """Content-addressed, durable cache around the real embedding provider.

    Cache keys include model, dimensions and the exact input hash. Text itself is
    not stored here. No generated/hash vectors or provider fallback exists.
    """

    is_test_double = False

    def __init__(self, pool: Any, provider: EmbeddingProvider, model: EmbeddingModelConfig, *, schema: str = "agent") -> None:
        self.pool, self.provider, self.model = pool, provider, model
        self.schema = _schema_name(schema)

    @_database_errors
    async def embed(self, texts: list[str], *, cancel: CancellationToken | None = None) -> list[list[float]]:
        _cancel(cancel)
        if not texts:
            return []
        keys = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        rows = await self.pool.fetch(
            f"SELECT input_hash, embedding FROM {self.schema}.embedding_cache "
            "WHERE model_id=$1 AND dimensions=$2 AND input_hash=ANY($3::text[])",
            self.model.model_id, self.model.dimensions, list(set(keys)),
        )
        cached = {row["input_hash"]: list(row["embedding"]) for row in rows}
        missing = list(dict.fromkeys(key for key in keys if key not in cached))
        if missing:
            sources = dict(zip(keys, texts, strict=True))
            vectors = await self.provider.embed([sources[key] for key in missing], cancel=cancel)
            validate_vectors(vectors, len(missing), self.model.dimensions)
            _cancel(cancel)
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    await connection.executemany(
                        f"INSERT INTO {self.schema}.embedding_cache (model_id, dimensions, input_hash, embedding) "
                        "VALUES ($1,$2,$3,$4::real[]) ON CONFLICT DO NOTHING",
                        [(self.model.model_id, self.model.dimensions, key, vector) for key, vector in zip(missing, vectors, strict=True)],
                    )
            cached.update(zip(missing, vectors, strict=True))
        result = [cached[key] for key in keys]
        validate_vectors(result, len(texts), self.model.dimensions)
        return result

    async def aclose(self) -> None:
        await self.provider.aclose()


class PostgresContentIndex:
    """Atomic revision replacement and persistent removal tombstones."""

    is_test_double = False
    index_version = INDEX_VERSION

    def __init__(self, pool: Any, *, schema: str = "agent", max_chunks_per_article: int = 512) -> None:
        self.pool, self.schema = pool, _schema_name(schema)
        self.max_chunks = max_chunks_per_article

    @staticmethod
    def _existing(row: Any, snapshot: ArticleSnapshot, model: EmbeddingModelConfig, chunk_chars: int) -> bool:
        if row is None:
            return False
        if snapshot.article_revision < row["revision"] or (row["deleted"] and snapshot.article_revision <= row["revision"]):
            raise PortError(AgentErrorCode.STALE_SNAPSHOT, "Article revision is no longer published", port="ContentIndex")
        if snapshot.article_revision == row["revision"] and snapshot.content_hash != row["content_hash"]:
            raise PortError(AgentErrorCode.STALE_SNAPSHOT, "Revision hash mismatch", port="ContentIndex")
        return (snapshot.article_revision == row["revision"] and not row["deleted"]
                and row["model_id"] == model.model_id and row["dimensions"] == model.dimensions
                and row["index_version"] == INDEX_VERSION and row["chunk_chars"] == chunk_chars)

    @_database_errors
    async def index_article(self, snapshot: ArticleSnapshot, *, embedding_provider: EmbeddingProvider,
                            model_config: EmbeddingModelConfig, chunk_config: ChunkingConfig | None = None,
                            canonical_url_template: str | None = None, published: bool = True,
                            cancel: CancellationToken | None = None) -> IndexResult:
        _cancel(cancel)
        if compute_content_hash(snapshot.content) != snapshot.content_hash:
            raise PortError(AgentErrorCode.STALE_SNAPSHOT, "Article content hash mismatch", port="ContentIndex")
        config = chunk_config or ChunkingConfig.for_model(model_config)
        row = await self.pool.fetchrow(f"SELECT * FROM {self.schema}.content_articles WHERE article_id=$1", snapshot.article_id)
        if self._existing(row, snapshot, model_config, config.max_chars) and row["url_template"] == canonical_url_template and row["published"] == published:
            return IndexResult(snapshot.article_id, snapshot.article_revision, row["chunk_count"], False)
        prepared = chunk_article(snapshot, config)
        if len(prepared) > self.max_chunks:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Article exceeds configured chunk budget", port="ContentIndex")
        texts = [embedded_text(item.heading_path, item.chunk.content) for item in prepared]
        vectors = await embedding_provider.embed(texts, cancel=cancel) if texts else []
        validate_vectors(vectors, len(texts), model_config.dimensions)
        _cancel(cancel)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Serializes publish/remove writers, including first publication.
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "content:" + snapshot.article_id)
                row = await connection.fetchrow(f"SELECT * FROM {self.schema}.content_articles WHERE article_id=$1 FOR UPDATE", snapshot.article_id)
                if self._existing(row, snapshot, model_config, config.max_chars) and row["url_template"] == canonical_url_template and row["published"] == published:
                    return IndexResult(snapshot.article_id, snapshot.article_revision, row["chunk_count"], False)
                await connection.execute(
                    f"INSERT INTO {self.schema}.content_articles "
                    "(article_id,revision,content_hash,deleted,model_id,dimensions,index_version,chunk_chars,chunk_count,url_template,published) "
                    "VALUES ($1,$2,$3,false,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(article_id) DO UPDATE SET "
                    "revision=EXCLUDED.revision,content_hash=EXCLUDED.content_hash,deleted=false,model_id=EXCLUDED.model_id,"
                    "dimensions=EXCLUDED.dimensions,index_version=EXCLUDED.index_version,chunk_chars=EXCLUDED.chunk_chars,chunk_count=EXCLUDED.chunk_count,"
                    "url_template=EXCLUDED.url_template,published=EXCLUDED.published",
                    snapshot.article_id, snapshot.article_revision, snapshot.content_hash, model_config.model_id,
                    model_config.dimensions, INDEX_VERSION, config.max_chars, len(prepared), canonical_url_template, published,
                )
                await connection.execute(f"DELETE FROM {self.schema}.content_chunks WHERE article_id=$1", snapshot.article_id)
                await connection.executemany(
                    f"INSERT INTO {self.schema}.content_chunks "
                    "(article_id,chunk_index,content,heading,char_start,char_end,heading_path,anchor,language,published,canonical_url,embedding) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::real[])",
                    [(snapshot.article_id, item.chunk.chunk_index, item.chunk.content, item.chunk.heading,
                      item.chunk.char_start, item.chunk.char_end, list(item.heading_path), item.anchor,
                      snapshot.language, published,
                      build_canonical_url(canonical_url_template, snapshot.slug, item.anchor) if canonical_url_template else None,
                      vector) for item, vector in zip(prepared, vectors, strict=True)],
                )
        return IndexResult(snapshot.article_id, snapshot.article_revision, len(prepared), True)

    @_database_errors
    async def remove_article(self, article_id: str, *, article_revision: int, cancel: CancellationToken | None = None) -> RemovalResult:
        _cancel(cancel)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "content:" + article_id)
                row = await connection.fetchrow(f"SELECT revision,chunk_count,deleted FROM {self.schema}.content_articles WHERE article_id=$1 FOR UPDATE", article_id)
                if row and row["revision"] > article_revision:
                    return RemovalResult(article_id, article_revision, 0, False)
                await connection.execute(
                    f"INSERT INTO {self.schema}.content_articles (article_id,revision,deleted) VALUES ($1,$2,true) "
                    "ON CONFLICT(article_id) DO UPDATE SET revision=EXCLUDED.revision,deleted=true,chunk_count=0",
                    article_id, article_revision,
                )
                await connection.execute(f"DELETE FROM {self.schema}.content_chunks WHERE article_id=$1", article_id)
        return RemovalResult(article_id, article_revision, row["chunk_count"] if row else 0, not row or not row["deleted"])

    @_database_errors
    async def search(self, query: SearchQuery, *, embedding_provider: EmbeddingProvider,
                     model_config: EmbeddingModelConfig, cancel: CancellationToken | None = None) -> list[ScoredChunk]:
        _cancel(cancel)
        if not query.text.strip() or not 1 <= query.top_k <= 100:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Invalid search query or top_k", port="ContentIndex")
        if not query.filters.article_ids or len(query.filters.article_ids) > 16:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Search requires 1-16 explicit article IDs", port="ContentIndex")
        rows = await self.pool.fetch(
            f"SELECT c.*,a.revision,a.content_hash,a.model_id,a.dimensions,a.index_version FROM {self.schema}.content_chunks c "
            f"JOIN {self.schema}.content_articles a USING(article_id) WHERE c.article_id=ANY($1::text[]) AND NOT a.deleted "
            "AND ($2::text IS NULL OR c.language=$2) AND ($3::boolean IS NULL OR c.published=$3) ORDER BY c.article_id,c.chunk_index LIMIT 513",
            sorted(query.filters.article_ids), query.filters.language, query.filters.published,
        )
        if not rows:
            return []
        if len(rows) > 512:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Search exceeds the 512-chunk memory budget; narrow article scope", port="ContentIndex")
        if any(row["model_id"] != model_config.model_id or row["dimensions"] != model_config.dimensions
               or row["index_version"] != INDEX_VERSION for row in rows):
            raise PortError(AgentErrorCode.CONFIG_ERROR, "Embedding index requires reindexing", port="ContentIndex")
        vectors = await embedding_provider.embed([query.text.strip()], cancel=cancel)
        validate_vectors(vectors, 1, model_config.dimensions)
        records = [IndexedChunk(
            chunk=ArticleChunk(article_id=row["article_id"], article_revision=row["revision"], chunk_index=row["chunk_index"],
                               content=row["content"], heading=row["heading"], char_start=row["char_start"], char_end=row["char_end"]),
            content_hash=row["content_hash"], heading_path=list(row["heading_path"]), anchor=row["anchor"],
            language=row["language"], published=row["published"], canonical_url=row["canonical_url"],
        ) for row in rows]
        semantic = [cosine_similarity(vectors[0], list(row["embedding"])) for row in rows]
        keyword = bm25_scores(tokenize(query.text), [tokenize(" ".join(record.heading_path) + "\n" + record.chunk.content) for record in records])
        fused = rrf_fuse(rank_by_score(semantic, records), rank_by_score(keyword, records))
        lookup = {(record.article_id, record.article_revision, record.chunk_index): record for record in records}
        _cancel(cancel)
        return [ScoredChunk(lookup[key], score, sem_rank, kw_rank)
                for key, (score, sem_rank, kw_rank) in sorted(fused.items(), key=lambda item: (-item[1][0], item[0]))[:query.top_k]]
