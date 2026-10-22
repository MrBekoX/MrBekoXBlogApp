"""B4 migration smoke testi: test DB'si Alembic head'de ve tablolar beklenen yapıda.

Gerçek migration zinciri (``migrations/``) session kurulumunda
``blogdb_agent_test`` üzerinde çalıştırılır; bu test zincirin izini doğrular.
"""

from __future__ import annotations

from typing import Any

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
    # B5 zincir uzantısı (0002), B6 zincir uzantısı (0003 job lease/fencing +
    # cancel_intents) ve Who am I wire sürümü (0005; 0004 bilinçli boş) head'i
    # ilerletti; smoke testi güncel head'i doğrular.
    assert version == "0005"
    assert "wire_version" in job_columns
    assert set(tables) >= {
        "inbox_messages",
        "jobs",
        "outbox_events",
        "run_event_sequences",
        "cancel_intents",
    }
    # İdempotent kabul anahtarı: run_id UNIQUE (B4 adım 4) ve inbox PK consumer kapsamlı.
    assert "run_id" in job_columns


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
