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
    assert version == "0001"
    assert set(tables) >= {"inbox_messages", "jobs", "outbox_events"}
    # İdempotent kabul anahtarı: run_id UNIQUE (B4 adım 4) ve inbox PK consumer kapsamlı.
    assert "run_id" in job_columns
