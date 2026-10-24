"""B4 migration smoke testi: test DB'si Alembic head'de ve tablolar beklenen yapıda.

Gerçek migration zinciri (``migrations/``) session kurulumunda
``blogdb_agent_test`` üzerinde çalıştırılır; bu test zincirin izini doğrular.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from alembic.config import Config
from alembic.script import ScriptDirectory
import asyncpg
import pytest

from .conftest import run

pytestmark = pytest.mark.usefixtures("truncated_db")


def test_agent_schema_is_at_alembic_head(db_pool: Any) -> None:
    async def _check() -> Any:
        async with db_pool.acquire() as conn:
            version = await conn.fetchval("SELECT version_num FROM agent.alembic_version_agent")
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'agent' ORDER BY table_name"
            )
            job_columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'agent' AND table_name = 'jobs' ORDER BY ordinal_position"
            )
            return version, [r["table_name"] for r in tables], [r["column_name"] for r in job_columns]

    version, tables, job_columns = run(_check())
    # Resolve the real migration chain, including the semantic-storage upgrade,
    # instead of pinning this acceptance test to an obsolete revision number.
    service = Path(__file__).resolve().parents[2]
    config = Config(str(service / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(service / "migrations"))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    assert expected_head is not None
    assert version == expected_head
    assert "wire_version" in job_columns
    assert set(tables) >= {
        "run_budgets",
        "budget_reservations",
        "inbox_messages",
        "jobs",
        "outbox_events",
        "run_event_sequences",
        "cancel_intents",
        "embedding_cache",
        "content_articles",
        "content_chunks",
    }
    # İdempotent kabul anahtarı: run_id UNIQUE (B4 adım 4) ve inbox PK consumer kapsamlı.
    assert "run_id" in job_columns


def test_semantic_storage_shapes_and_dimension_guards(db_pool: Any) -> None:
    """Real database constraints protect cached vectors, chunks and tombstones."""

    async def _check() -> None:
        async with db_pool.acquire() as conn:
            columns = await conn.fetch(
                "SELECT table_name,column_name,data_type,udt_name,is_nullable "
                "FROM information_schema.columns WHERE table_schema='agent' "
                "AND table_name=ANY($1::text[])",
                ["embedding_cache", "content_articles", "content_chunks"],
            )
            by_column = {(row["table_name"], row["column_name"]): row for row in columns}
            for table in ("embedding_cache", "content_chunks"):
                embedding = by_column[(table, "embedding")]
                assert embedding["data_type"] == "ARRAY" and embedding["udt_name"] == "_float4"
                assert embedding["is_nullable"] == "NO"
            assert by_column[("content_articles", "revision")]["data_type"] == "bigint"
            assert by_column[("content_articles", "deleted")]["data_type"] == "boolean"
            assert by_column[("content_articles", "deleted")]["is_nullable"] == "NO"
            assert by_column[("content_articles", "url_template")]["data_type"] == "text"
            assert by_column[("content_articles", "published")]["data_type"] == "boolean"

            constraints = await conn.fetch(
                "SELECT conrelid::regclass::text AS table_name,contype,convalidated,"
                "pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                "WHERE conrelid=ANY(ARRAY['agent.embedding_cache'::regclass,'agent.content_chunks'::regclass])"
            )
            definitions = {
                (row["table_name"], "".join(row["definition"].lower().split()))
                for row in constraints if row["convalidated"]
            }
            assert ("agent.embedding_cache", "primarykey(model_id,dimensions,input_hash)") in definitions
            assert ("agent.content_chunks", "primarykey(article_id,chunk_index)") in definitions
            assert any(table == "agent.embedding_cache" and "cardinality(embedding)=dimensions" in definition
                       for table, definition in definitions)
            assert any(table == "agent.content_chunks" and "cardinality(embedding)=1536" in definition
                       for table, definition in definitions)
            assert await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='agent.content_chunks'::regclass "
                "AND confrelid='agent.content_articles'::regclass AND contype='f' AND confdeltype='c' AND convalidated)"
            )

            # Exercise the guards with invalid storage values, without an AI
            # provider or pretending these values are semantic embeddings.
            article_id = "migration-smoke-" + uuid.uuid4().hex
            transaction = conn.transaction()
            await transaction.start()
            try:
                await conn.execute(
                    "INSERT INTO agent.content_articles(article_id,revision,deleted) VALUES($1,1,true)", article_id
                )
                with pytest.raises(asyncpg.CheckViolationError):
                    async with conn.transaction():
                        await conn.execute(
                            "INSERT INTO agent.embedding_cache(model_id,dimensions,input_hash,embedding) "
                            "VALUES('text-embedding-3-small',1536,$1,ARRAY[1.0]::real[])", uuid.uuid4().hex * 2,
                        )
                with pytest.raises(asyncpg.CheckViolationError):
                    async with conn.transaction():
                        await conn.execute(
                            "INSERT INTO agent.content_chunks(article_id,chunk_index,content,char_start,char_end,"
                            "heading_path,anchor,published,embedding) "
                            "VALUES($1,0,'dimension guard',0,15,ARRAY['guard']::text[],'guard',true,ARRAY[1.0]::real[])",
                            article_id,
                        )
            finally:
                await transaction.rollback()

    run(_check())


def test_wire_version_triggers_and_constraint_exist(db_pool: Any) -> None:
    """0005: claim izolasyon + outbox sürüm tetikleyicileri ve 1|2 kısıtı kurulu."""

    async def _check() -> Any:
        async with db_pool.acquire() as conn:
            triggers = await conn.fetch(
                "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'agent' AND NOT t.tgisinternal"
            )
            default = await conn.fetchval(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_schema = 'agent' AND table_name = 'jobs' AND column_name = 'wire_version'"
            )
            constraint = await conn.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_jobs_wire_version'"
            )
            return {r["tgname"] for r in triggers}, default, constraint

    triggers, default, constraint = run(_check())
    assert {"trg_jobs_wire_claim_guard", "trg_outbox_wire_version_guard"} <= triggers
    assert default is not None and "1" in default  # eksik sürüm = v1 (eski satırlar)
    assert constraint is not None and "1" in constraint and "2" in constraint
