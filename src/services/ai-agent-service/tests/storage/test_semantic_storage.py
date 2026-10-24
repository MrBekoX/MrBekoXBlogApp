"""Real PostgreSQL storage checks; no AI provider or fabricated embeddings."""

import asyncio
import os
import uuid

import asyncpg
import pytest

from agent_core.content.config import EmbeddingModelConfig
from agent_core.content.index import SearchQuery
from agent_core.content.postgres import PostgresContentIndex, PostgresEmbeddingCache
from agent_core.content.retrieval import SearchFilters
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import ArticleSnapshot, compute_content_hash
from datetime import datetime, timezone


DB_URL = os.environ.get("AGENT_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="Requires an isolated migrated PostgreSQL test database")
MODEL = EmbeddingModelConfig("text-embedding-3-small", 1536)


def test_removal_tombstone_survives_restart_and_blocks_old_snapshot():
    async def scenario():
        pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
        article_id = "storage-" + uuid.uuid4().hex
        try:
            index = PostgresContentIndex(pool)
            first = await index.remove_article(article_id, article_revision=8)
            assert first.removed
            assert not (await index.remove_article(article_id, article_revision=7)).removed
            restored = PostgresContentIndex(pool)
            content = "A removed article must not be embedded again."
            snapshot = ArticleSnapshot(article_id=article_id, article_revision=8, slug=article_id,
                title="Removal storage contract", content=content, content_hash=compute_content_hash(content),
                fetched_at=datetime.now(timezone.utc))
            with pytest.raises(PortError) as error:
                # None is intentional: stale snapshots must be rejected before
                # any provider is accessed. No fake provider participates.
                await restored.index_article(snapshot, embedding_provider=None, model_config=MODEL)
            assert error.value.code is AgentErrorCode.STALE_SNAPSHOT
            rows = await pool.fetch("SELECT revision,deleted FROM agent.content_articles WHERE article_id=$1", article_id)
            assert rows[0]["deleted"] and rows[0]["revision"] == 8
        finally:
            await pool.execute("DELETE FROM agent.content_articles WHERE article_id=$1", article_id)
            await pool.close()
    asyncio.run(scenario())


def test_scoped_empty_search_does_not_contact_a_provider():
    async def scenario():
        pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
        try:
            index = PostgresContentIndex(pool)
            query = SearchQuery("database", SearchFilters(article_ids=frozenset({uuid.uuid4().hex}), published=True))
            assert await index.search(query, embedding_provider=None, model_config=MODEL) == []
            with pytest.raises(PortError):
                await index.search(SearchQuery("database"), embedding_provider=None, model_config=MODEL)
        finally:
            await pool.close()
    asyncio.run(scenario())


def test_database_rejects_wrong_embedding_dimensions():
    async def scenario():
        connection = await asyncpg.connect(DB_URL)
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                # This invalid storage value exercises a database constraint,
                # rather than simulating a model response or semantic search.
                await connection.execute("INSERT INTO agent.embedding_cache (model_id,dimensions,input_hash,embedding) VALUES ($1,1536,$2,ARRAY[1.0]::real[])",
                    MODEL.model_id, uuid.uuid4().hex * 2)
        finally:
            await connection.close()
    asyncio.run(scenario())
