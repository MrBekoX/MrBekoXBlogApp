"""B5 agent olay yayını test kurulumu: gerçek broker + gerçek PostgreSQL.

Bu dizin B5 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez (L005:
``tests/events`` __init__.py'li pakettir, conftest.py güvenlidir).

Ortam (B4 intake deseninin B5'e uyarlaması):
- Broker: ayrı vhost ``blogapp_dev_b5`` — B2/B3 (blogapp_dev) ve B4
  (blogapp_dev_b4) paketleriyle kuyruk paylaşımı yok; paralel agent'ların
  purge/drain işlemleri bu paketin mesajlarını yutmasın (intake conftest'teki
  2026-10-11 gözlemi).
- DB: ``blogdb_agent_b5tests`` scratch veritabanı; AYNI Alembic zinciri
  programatik ``upgrade head`` ile uygulanır (B5 migration 0002 dahil).
- Parola KODA GİRMEZ: docker/.env çalışma anında okunur (sır kuralı).

pytest-asyncio varsayımı YOKTUR: senkron testler ``run()`` ile coroutine çalıştırır.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from infra_environment import broker_address, broker_management_url, postgres_credentials, postgres_host, postgres_migration_url, postgres_port

from messaging import (
    AgentEventPublisher,
    AgentOutcome,
    BrokerPublisher,
    BrokerSettings,
    JobStore,
    connect_broker,
    declare_topology,
)
from messaging.contracts import SCHEMA_VERSION, AgentEnvelope, Producer
from messaging.topology import BACKEND_EVENTS_QUEUE

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
SERVICE_ROOT = REPO_ROOT / "src" / "services" / "ai-agent-service"

MGMT = broker_management_url()
#: B5 testlerine ÖZEL vhost: plan B2 kuralı ("ortam ön eki veya ayrı vhost ile
#: ayırma") — B4'ün blogapp_dev_b4 vhost'unu paylaşmayız.
VHOST = "blogapp_dev_b5"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")

AGENT_TEST_DB = "blogdb_agent_b5tests"
QUEUE_PURGE_TARGETS = (BACKEND_EVENTS_QUEUE, f"{BACKEND_EVENTS_QUEUE}.dlq")


def ensure_loop() -> asyncio.AbstractEventLoop:
    """Paylaşımlı loop'u döndürür ve current yapar (B4 conftest'teki gerekçe)."""

    global _shared_loop
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_shared_loop)
    return _shared_loop


def run(coroutine: Any) -> Any:
    """Coroutine'i paylaşımlı oturum loop'unda çalıştırır (pytest-asyncio'suz)."""

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.run_until_complete(coroutine)


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
    """Gerçek Postgres yoksa test oturumu AÇIK HATA ile durur (skip ile sahte
    başarı üretilmez; GATE gerçek broker + gerçek Postgres ister)."""

    try:
        conn = run(asyncpg.connect(**db_conn_kwargs("postgres")))
    except Exception as exc:  # bağlantı hatası: açık engel
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
    """Alembic zincirini programatik çalıştırır (CLI ile aynı env.py)."""

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


# --------------------------------------------------------------------------
# Broker yardımcıları
# --------------------------------------------------------------------------


def make_settings(
    username: str = AGENT_USER[0],
    password: str = AGENT_USER[1],
    **overrides: Any,
) -> BrokerSettings:
    defaults: dict[str, Any] = dict(
        **broker_address(),
        username=username,
        password=password,
        virtualhost=VHOST,
        reconnect_interval_seconds=1.5,
        connection_timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return BrokerSettings(**defaults)


def mgmt_request(method: str, path: str, body: Any = None, auth: tuple[str, str] = ADMIN) -> Any:
    """Management API isteği; yüklü brokerda kopan bağlantılara sınırlı retry."""

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            req = urllib.request.Request(
                MGMT + path,
                method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": "Basic " + token, "content-type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError:
            raise  # 4xx/5x: anlamlı yanıt — tekrar yok
        except (urllib.error.URLError, OSError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"management isteği {method} {path} başarısız: {last_error}")


def provision_vhost_and_users() -> None:
    """B4 ile aynı izin modeli; yalnız vhost farklı (idempotent)."""

    mgmt_request("PUT", f"/vhosts/{VHOST}")
    mgmt_request("PUT", f"/permissions/{VHOST}/{ADMIN[0]}",
                 {"configure": ".*", "write": ".*", "read": ".*"})
    for user, password in (BACKEND_USER, AGENT_USER):
        mgmt_request("PUT", f"/users/{user}", {"password": password, "tags": "none"})
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{BACKEND_USER[0]}",
        {
            "configure": r".*",
            "write": r"blog\.(agent\.commands|content\.events)",
            "read": r"backend\.agent\.events\.q(\.dlq)?|agent\.(execute|control|content)(\.v2)?\.q",
        },
    )
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{AGENT_USER[0]}",
        {
            "configure": "",
            "write": r"blog\.agent\.events",
            "read": r"agent\.(execute|control|content)(\.v2)?\.q(\.dlq)?",
        },
    )


def wait_for_management(timeout_seconds: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            mgmt_request("GET", "/overview")
            return
        except Exception:
            time.sleep(2.0)
    raise TimeoutError(f"RabbitMQ management {timeout_seconds}s içinde hazır olmadı")


async def queue_depth_async(queue: str) -> int:
    """Kuyruk derinliği AMQP passive declare ile ölçülür (B4 conftest gerekçesi)."""

    if queue.startswith("backend."):
        user, password = BACKEND_USER
    else:
        user, password = AGENT_USER
    conn = await connect_broker(make_settings(user, password))
    try:
        channel = await conn.channel(publisher_confirms=False)
        try:
            q = await channel.declare_queue(queue, durable=True, passive=True)
            return int(q.declaration_result.message_count)
        except Exception:
            return 0
        finally:
            await channel.close()
    finally:
        await conn.close()


def queue_depth(queue: str) -> int:
    return run(queue_depth_async(queue))


def purge_queues() -> None:
    """Test kuyruklarını AMQP purge ile boşaltır; kopmalara karşı sınırlı retry."""

    async def _purge_once() -> None:
        for queue in QUEUE_PURGE_TARGETS:
            user, password = BACKEND_USER
            conn = await connect_broker(make_settings(user, password))
            try:
                channel = await conn.channel(publisher_confirms=False)
                q = await channel.declare_queue(queue, durable=True, passive=True)
                await q.purge()
                await channel.close()
            finally:
                await conn.close()

    last_error: Exception | None = None
    for attempt in range(4):
        try:
            run(_purge_once())
            return
        except (OSError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"kuyruk purge başarısız: {last_error}")


async def wait_until(condition: Any, timeout_seconds: float = 20.0, interval: float = 0.2) -> None:
    """Koşulu yoklar; koşul içinde ``run()`` ÇAĞRILMAZ (nested loop hatası)."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = condition()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"koşul {timeout_seconds}s içinde sağlanmadı")


def queue_depth_is(queue: str, expected: int) -> Any:
    async def _condition() -> bool:
        return await queue_depth_async(queue) == expected

    return _condition


# --------------------------------------------------------------------------
# Run/yayın yardımcıları
# --------------------------------------------------------------------------


def make_run_ids() -> tuple[str, str, str]:
    """(run_id, conversation_id, correlation_id) üçlüsü."""

    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


async def seed_accepted_job(
    pool: Any, run_id: str, conversation_id: str, correlation_id: str, *, wire_version: int = 1
) -> None:
    """Kabul edilmiş iş kaydını doğrudan yazar (B4 kabul transaction'ının sonucu).

    ``wire_version`` (K4, migration 0005): iş satırının run wire sürümü ve kabul
    zarfının ``schema_version``'ı birlikte yazılır.
    """

    deadline_dt = datetime.now(timezone.utc) + timedelta(minutes=10)
    deadline = deadline_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO agent.jobs (job_id, run_id, conversation_id, origin_message_id, "
            "payload_hash, payload, envelope, status, deadline_at, accepted_at, wire_version) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11)",
            uuid.uuid4(),
            uuid.UUID(run_id),
            uuid.UUID(conversation_id),
            uuid.uuid4(),
            "seed-hash",
            json.dumps({"seed": True}),
            json.dumps(
                {
                    "message_id": str(uuid.uuid4()),
                    "message_type": "agent.execute.requested",
                    "schema_version": wire_version,
                    "run_id": run_id,
                    "conversation_id": conversation_id,
                    "correlation_id": correlation_id,
                    "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "deadline_at": deadline,
                    "producer": Producer.BACKEND_NET,
                    "payload": {"seed": True},
                }
            ),
            "accepted",
            deadline_dt,
            datetime.now(timezone.utc),
            wire_version,
        )


def article_citation(run_id: str) -> Any:
    from messaging.contracts.payloads import AgentSourceReference

    return AgentSourceReference(
        kind="article",
        article_id=str(uuid.uuid4()),
        article_revision=1,
        chunk_index=0,
    )


def web_citation() -> Any:
    from messaging.contracts.payloads import AgentSourceReference

    return AgentSourceReference(
        kind="web",
        url="https://example.com/source",
        title="Sample",
        accessed_at="2026-10-12T10:00:00Z",
    )


def usage_record(run_id: str) -> Any:
    from messaging.contracts.payloads import AgentUsageRecord

    return AgentUsageRecord(run_id=run_id, total_tokens=42, recorded_at="2026-10-12T10:00:00Z")


# --------------------------------------------------------------------------
# pytest fixture'ları (senkron — pytest-asyncio yok)
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def real_environment() -> None:
    """GATE ön koşulu: gerçek broker ve gerçek Postgres; yoksa açık hata."""

    wait_for_management()
    provision_vhost_and_users()

    async def _declare() -> None:
        conn = await connect_broker(make_settings(*ADMIN))
        channel = await conn.channel(publisher_confirms=False)
        await declare_topology(channel)
        await channel.close()
        await conn.close()

    last_error: Exception | None = None
    for _ in range(3):
        try:
            run(_declare())
            break
        except Exception as exc:
            last_error = exc
            time.sleep(5.0)
    else:
        raise AssertionError(f"topology kurulamadı: {last_error}")

    require_postgres()
    recreate_test_database()
    run_agent_migrations(AGENT_TEST_DB)


@pytest.fixture()
def clean_environment() -> Any:
    purge_queues()
    run(wait_until(queue_depth_is(BACKEND_EVENTS_QUEUE, 0)))
    yield
    purge_queues()


@pytest.fixture()
def db_pool() -> Any:
    ensure_loop()
    pool = run(asyncpg.create_pool(**db_conn_kwargs(AGENT_TEST_DB), min_size=1, max_size=4))

    async def _truncate() -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE agent.job_checkpoints, agent.budget_reservations, agent.run_budgets, "
                "agent.inbox_messages, agent.jobs, agent.outbox_events, "
                "agent.run_event_sequences"
            )

    run(_truncate())

    async def _close() -> None:
        await pool.close()

    yield pool
    run(_close())


@pytest.fixture()
def publisher(db_pool: Any) -> AgentEventPublisher:
    """Seyrekleştirme penceresi testlerde kısa: varsayılan 2s yerine 0.05s.

    Throttle testi kendi yayıncısını 60s pencereyle kurar.
    """

    return AgentEventPublisher(db_pool, schema="agent", min_progress_interval_seconds=0.05)


@pytest.fixture()
def slow_publisher(db_pool: Any) -> AgentEventPublisher:
    """Throttle davranışını gözlemlenebilir kılmak için uzun pencere."""

    return AgentEventPublisher(db_pool, schema="agent", min_progress_interval_seconds=60.0)


@pytest.fixture()
def store(db_pool: Any) -> JobStore:
    return JobStore(db_pool, schema="agent")


@pytest.fixture()
def agent_publisher() -> Any:
    """Relay testleri için agent rolüyle confirm'lu publisher (blog.agent.events)."""

    async def _open() -> Any:
        conn = await connect_broker(make_settings(*AGENT_USER))
        publisher = BrokerPublisher(conn, ("blog.agent.events",), make_settings(*AGENT_USER))
        await publisher.start()
        return conn, publisher

    async def _close(resources: Any) -> None:
        conn, publisher = resources
        await publisher.close()
        await conn.close()

    resources = run(_open())
    yield resources[1]
    run(_close(resources))


async def fetch_event_messages(limit: int = 16) -> list[tuple[Any, Any, Any]]:
    """backend.agent.events.q'dan mesajları ACK'sız çeker (connexion, kanal, mesaj)."""

    conn = await connect_broker(make_settings(*BACKEND_USER))
    channel = await conn.channel(publisher_confirms=False)
    queue = await channel.declare_queue(BACKEND_EVENTS_QUEUE, durable=True, passive=True)
    fetched: list[tuple[Any, Any, Any]] = []
    for _ in range(limit):
        message = await queue.get(no_ack=False, fail=False)
        if message is None:
            break
        fetched.append((conn, channel, message))
    return fetched


def close_fetch(connection: Any, channel: Any) -> None:
    async def _close() -> None:
        await channel.close()
        await connection.close()

    run(_close())
