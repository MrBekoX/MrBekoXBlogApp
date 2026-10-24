"""W5 bütünleştirme testi kurulumu: gerçek migration şeması + gerçek store çifti.

Ortam (L009 izolasyon kuralı — her faz kendi DB'sini kullanır):
- DB: ``blogdb_agent_w5int`` scratch veritabanı. Gerçek alembic zinciri
  (0001→0003) programatik ``upgrade head`` ile kurulur ve SONRASINDA sözleşme
  DDL'i UYGULANMAZ: ``fencing_token`` BIGINT (``agent.job_fencing_seq``) ve
  ``ck_jobs_status`` 'accepted' dahil GERÇEK şema geçerlidir (B7 scratch
  DDL'inin aksine — bulgusu 2'nin kapattığı uyumsuzluk).
- Store çifti: ``messaging.job_store.JobStore`` (accept/claim/complete/fail)
  ve ``messaging.control_store.ControlStore`` (record_cancel_intent/
  mark_cancelled_if_running) AYNI havuz üzerinde; üretimde olduğu gibi.
- Parola KODA GİRMEZ: docker/.env çalışma anında okunur (sır kuralı).
- Broker GEREKMEZ: senaryolar kalıcı iş + cancel intent yarışı üzerinedir.

pytest-asyncio varsayımı YOKTUR: senkron testler paylaşımlı loop üstünde
``run()``/``spawn()`` ile koşar (tests/worker deseni).
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from infra_environment import postgres_credentials, postgres_host, postgres_migration_url, postgres_port

from messaging import ControlStore, JobStore

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
SERVICE_ROOT = REPO_ROOT / "src" / "services" / "ai-agent-service"

#: W5 bütünleştirme testlerine ÖZEL scratch DB (L009: blogdb_agent_b7 ve
#: blogdb_agent_test_b6 PAYLAŞILMAZ).
AGENT_TEST_DB = "blogdb_agent_w5int"


def ensure_loop() -> asyncio.AbstractEventLoop:
    global _shared_loop
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_shared_loop)
    return _shared_loop


def run(coroutine: Any) -> Any:
    """Coroutine'i paylaşımlı loop'ta çalıştırır (pytest-asyncio'suz)."""

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.run_until_complete(coroutine)


def spawn(coroutine: Any) -> asyncio.Task[Any]:
    """Coroutine'i paylaşımlı loop'ta ARKA PLANDA başlatır (eşzamanlı yarış)."""

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.create_task(coroutine)


_shared_loop: asyncio.AbstractEventLoop | None = None


@pytest.fixture(scope="session", autouse=True)
def _close_shared_loop() -> Any:
    yield
    global _shared_loop
    if _shared_loop is not None and not _shared_loop.is_closed():
        _shared_loop.close()
    _shared_loop = None


# --------------------------------------------------------------------------
# Ortam: docker/.env'den DB kimlikleri (parola fixture'ya/koda girmez)
# --------------------------------------------------------------------------


def load_docker_env() -> dict[str, str]:
    return postgres_credentials(REPO_ROOT)


def db_conn_kwargs(database: str) -> dict[str, Any]:
    env = load_docker_env()
    return dict(
        host=postgres_host(),
        port=postgres_port(),
        user=env.get("POSTGRES_USER", "blogapp_user"),
        password=env.get("POSTGRES_PASSWORD", ""),
        database=database,
    )


def require_postgres() -> None:
    """Gerçek Postgres yoksa test oturumu AÇIK HATA ile durur (sahte başarı yok)."""

    try:
        conn = run(asyncpg.connect(**db_conn_kwargs("postgres")))
    except Exception as exc:
        pytest.fail(
            "Gerçek PostgreSQL erişilemiyor (docker compose -f docker/docker-compose.yml "
            f"up -d postgres ile kaldırın): {exc}"
        )
    run(conn.close())


def recreate_test_database() -> None:
    async def _recreate() -> None:
        conn = await asyncpg.connect(**db_conn_kwargs("postgres"))
        try:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                AGENT_TEST_DB,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{AGENT_TEST_DB}"')
            await conn.execute(f'CREATE DATABASE "{AGENT_TEST_DB}"')
        finally:
            await conn.close()

    run(_recreate())


def run_agent_migrations(database: str) -> None:
    """GERÇEK alembic zincirini programatik çalıştırır (0001→0003; sözleşme DDL'i yok)."""

    from alembic import command
    from alembic.config import Config

    env = load_docker_env()
    user = env.get("POSTGRES_USER", "blogapp_user")
    password = env.get("POSTGRES_PASSWORD", "")
    previous_url = os.environ.get("AGENT_DB_URL")
    os.environ["AGENT_DB_URL"] = postgres_migration_url(database, user, password)
    os.environ["AGENT_DB_SCHEMA"] = "agent"
    try:
        cfg = Config(str(SERVICE_ROOT / "migrations" / "alembic.ini"))
        cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        if previous_url is None:
            os.environ.pop("AGENT_DB_URL", None)
        else:
            os.environ["AGENT_DB_URL"] = previous_url


@pytest.fixture(scope="session", autouse=True)
def real_migration_environment() -> None:
    """GATE ön koşulu: gerçek Postgres + gerçek migration zinciri (0001→0003)."""

    require_postgres()
    recreate_test_database()
    run_agent_migrations(AGENT_TEST_DB)


@pytest.fixture()
def db_pool() -> Any:
    ensure_loop()
    pool = run(asyncpg.create_pool(**db_conn_kwargs(AGENT_TEST_DB), min_size=1, max_size=6))

    async def _reset() -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE agent.budget_reservations, agent.run_budgets, "
                "agent.inbox_messages, agent.jobs, agent.outbox_events, "
                "agent.run_event_sequences, agent.cancel_intents"
            )
            await conn.execute("ALTER SEQUENCE agent.job_fencing_seq RESTART WITH 1")

    run(_reset())

    async def _close() -> None:
        await pool.close()

    yield pool
    run(_close())


@pytest.fixture()
def job_store(db_pool: Any) -> JobStore:
    return JobStore(db_pool, schema="agent")


@pytest.fixture()
def control_store(db_pool: Any) -> ControlStore:
    return ControlStore(db_pool, schema="agent")
