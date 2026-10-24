"""Paid acceptance using real OpenAI embeddings and a real PostgreSQL database.

Explicit opt-in: AGENT_RUN_PAID_TESTS=1 and AGENT_TEST_DB_URL. This module never
loads a developer .env file, and normal pytest/CI cannot trigger a model call.
"""

import asyncio
from datetime import datetime, timezone
import os
import uuid

import asyncpg
import pytest

from agent_core.adapters import build_embedding_provider_from_env
from agent_core.content.index import SearchQuery
from agent_core.content.postgres import PostgresContentIndex, PostgresEmbeddingCache
from agent_core.content.retrieval import SearchFilters
from agent_core.models import ArticleSnapshot, compute_content_hash


pytestmark = pytest.mark.skipif(
    os.environ.get("AGENT_RUN_PAID_TESTS") != "1" or not os.environ.get("AGENT_TEST_DB_URL"),
    reason="Paid OpenAI acceptance requires explicit opt-in and an isolated migrated PostgreSQL database",
)


def test_real_embedding_index_persists_and_retrieves_turkish_content():
    async def scenario():
        provider = build_embedding_provider_from_env()
        pool = await asyncpg.create_pool(os.environ["AGENT_TEST_DB_URL"], min_size=1, max_size=2)
        article_id = "live-" + uuid.uuid4().hex
        content = "# Veritabanı\nPostgreSQL işlemleri ACID özelliklerini sağlar.\n\n# Önbellek\nRedis sık okunan verileri bellekte saklar."
        snapshot = ArticleSnapshot(article_id=article_id, article_revision=1, slug=article_id,
            title="Veri katmanı", content=content, content_hash=compute_content_hash(content),
            fetched_at=datetime.now(timezone.utc), language="tr")
        try:
            cache = PostgresEmbeddingCache(pool, provider, provider.index_config)
            index = PostgresContentIndex(pool)
            result = await index.index_article(snapshot, embedding_provider=cache, model_config=provider.index_config)
            assert result.indexed and result.chunk_count > 0
            # A new index instance must read the persisted manifest and vectors.
            restarted = PostgresContentIndex(pool)
            assert not (await restarted.index_article(snapshot, embedding_provider=cache, model_config=provider.index_config)).indexed
            hits = await restarted.search(SearchQuery("İşlemlerin ACID özelliklerini hangi sistem sağlar?",
                SearchFilters(article_ids=frozenset({article_id}), published=True), top_k=3),
                embedding_provider=cache, model_config=provider.index_config)
            assert hits and all(hit.record.article_id == article_id for hit in hits)
            assert any("PostgreSQL" in hit.record.chunk.content for hit in hits)
            await restarted.remove_article(article_id, article_revision=2)
            assert await restarted.search(SearchQuery("PostgreSQL", SearchFilters(article_ids=frozenset({article_id}))),
                embedding_provider=cache, model_config=provider.index_config) == []
        finally:
            await pool.execute("DELETE FROM agent.content_articles WHERE article_id=$1", article_id)
            await provider.aclose()
            await pool.close()
    asyncio.run(scenario())
