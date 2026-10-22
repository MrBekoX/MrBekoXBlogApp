"""B9 test kurulumu: gerçek broker (ÖZEL vhost) + gerçek PostgreSQL (scratch DB).

Bu dizin B9 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez (L005:
``tests/collab`` __init__.py'li pakettir, conftest.py güvenlidir).

Ortam (L009 izolasyon kuralı — her faz kendi vhost/DB'sini kullanır):
- Broker: ``blogapp_w6_b9`` vhost'u; B2 izin modeli + agent rolüne retry
  exchange yazma izni. Topology KISA retry kademeleriyle (1s/2s/3s) declare
  edilir (kademeler parametrik; üretim kademeleri 10s/30s/2dk'dır).
- DB: ``blogdb_agent_b9`` scratch veritabanı. Alembic zinciri (0001→0003)
  programatik ``upgrade head`` ile kurulur; ardından ``agent.jobs`` B6 sözleşme
  DDL'i ile yaratılır (B7 conftest'iyle aynı şekil; gerçek migration B6'ya
  aittir, scratch sözleşme DDL'ini temsil eder).
- Parola KODA GİRMEZ: docker/.env çalışma anında okunur (sır kuralı).

pytest-asyncio kuruludur diye varsayım YOKTUR: senkron testler paylaşımlı
loop üstünde ``run()`` ile coroutine çalıştırır (B4/B7 deseni).
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
from urllib.parse import quote

import asyncpg
import pytest

from messaging import (
    BrokerPublisher,
    BrokerSettings,
    ControlStore,
    connect_broker,
    declare_topology,
)
from messaging.contracts import SCHEMA_VERSION, AgentEnvelope, Producer

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
SERVICE_ROOT = REPO_ROOT / "src" / "services" / "ai-agent-service"

MGMT = "http://127.0.0.1:15672/api"
#: B9 testlerine ÖZEL vhost (L009: paylaşılan vhost'ta eşzamanlı koşum çakışması).
VHOST = "blogapp_w6_b9"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")

#: B9 scratch DB: blogdb_dev'e ve diğer fazların DB'lerine DOKUNULMAZ.
AGENT_TEST_DB = "blogdb_agent_b9"

#: Test kademeleri: TTL akışını saniyeler içinde gözlemlemek için kısa set.
TEST_TIERS: tuple[int, ...] = (1, 2, 3)

EXECUTE_QUEUE = "agent.execute.q"
CONTROL_QUEUE = "agent.control.q"
BACKEND_EVENTS_QUEUE = "backend.agent.events.q"

PURGE_TARGETS: tuple[str, ...] = (
    EXECUTE_QUEUE,
    CONTROL_QUEUE,
    f"{EXECUTE_QUEUE}.dlq",
    f"{CONTROL_QUEUE}.dlq",
    BACKEND_EVENTS_QUEUE,
    *[f"{EXECUTE_QUEUE}.retry.{tier}s.q" for tier in TEST_TIERS],
    *[f"{CONTROL_QUEUE}.retry.{tier}s.q" for tier in TEST_TIERS],
)


def ensure_loop() -> asyncio.AbstractEventLoop:
    """Paylaşımlı loop'u döndürür ve current yapar (intake conftest açıklaması)."""

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
    env_path = REPO_ROOT / "docker" / ".env"
    if not env_path.exists():
        pytest.fail("docker/.env bulunamadı; Postgres kimlikleri okunamadı")
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def db_conn_kwargs(database: str) -> dict[str, Any]:
    env = load_docker_env()
    return dict(
        host="127.0.0.1",
        port=5432,
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
    """Alembic zincirini programatik çalıştırır (CLI ile aynı env.py)."""

    from alembic import command
    from alembic.config import Config

    env = load_docker_env()
    user = env.get("POSTGRES_USER", "blogapp_user")
    password = env.get("POSTGRES_PASSWORD", "")
    previous_url = os.environ.get("AGENT_DB_URL")
    os.environ["AGENT_DB_URL"] = (
        f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@127.0.0.1:5432/{database}"
    )
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


#: Ortak store sözleşmesinin B6 şekli (B7 conftest'iyle aynı DDL): gerçek şemadaki
#: jsonb kabul zarfı dahil — ControlStore reaper sorguları correlation_id'yi
#: zarftan okur. Gerçek alembic 0003 B6'ya aittir; scratch sözleşmeyi temsil eder.
B6_CONTRACT_DDL = """
DROP TABLE IF EXISTS agent.jobs;
CREATE TABLE agent.jobs (
    run_id uuid PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
    payload_hash text NOT NULL,
    queue_class text NOT NULL CHECK (queue_class IN ('fast','research')),
    lease_owner text,
    lease_until timestamptz,
    execution_attempt integer NOT NULL DEFAULT 0,
    fencing_token text,
    result_json jsonb,
    envelope jsonb NOT NULL DEFAULT '{}'::jsonb,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    deadline_at timestamptz NOT NULL,
    conversation_id uuid NOT NULL,
    correlation_id uuid NOT NULL,
    origin_message_id uuid,
    wire_version smallint NOT NULL DEFAULT 1 CHECK (wire_version IN (1, 2))
);
-- Migration 0005: claim/güncelleme izolasyonu scratch tabloya yeniden bağlanır
-- (DROP TABLE tetikleyiciyi düşürür; fonksiyon migration'dan gelir). outbox
-- sürüm tetikleyicisi jobs.wire_version'ı okuduğu için kolon zorunludur.
CREATE TRIGGER trg_jobs_wire_claim_guard BEFORE UPDATE ON agent.jobs
    FOR EACH ROW EXECUTE FUNCTION agent.jobs_wire_claim_guard();
CREATE TABLE IF NOT EXISTS agent.cancel_intents (
    run_id uuid PRIMARY KEY,
    requested_at timestamptz NOT NULL DEFAULT now(),
    requested_by text NOT NULL
);
"""


def apply_b6_contract_schema(database: str) -> None:
    async def _apply() -> None:
        conn = await asyncpg.connect(**db_conn_kwargs(database))
        try:
            await conn.execute(B6_CONTRACT_DDL)
        finally:
            await conn.close()

    run(_apply())


# --------------------------------------------------------------------------
# Broker yardımcıları
# --------------------------------------------------------------------------


def make_settings(
    username: str = AGENT_USER[0],
    password: str = AGENT_USER[1],
    **overrides: Any,
) -> BrokerSettings:
    defaults: dict[str, Any] = dict(
        host="127.0.0.1",
        username=username,
        password=password,
        virtualhost=VHOST,
        reconnect_interval_seconds=1.5,
        connection_timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return BrokerSettings(**defaults)


def mgmt_request(method: str, path: str, body: Any = None, auth: tuple[str, str] = ADMIN) -> Any:
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
            raise
        except (urllib.error.URLError, OSError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"management isteği {method} {path} başarısız: {last_error}")


def provision_vhost_and_users() -> None:
    """B2 izin modeli (B7 conftest'iyle aynı kurulum, B9 vhost'unda)."""

    mgmt_request("PUT", f"/vhosts/{VHOST}")
    for user, password in (BACKEND_USER, AGENT_USER):
        mgmt_request("PUT", f"/users/{user}", {"password": password, "tags": "none"})
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{BACKEND_USER[0]}",
        {
            "configure": r".*",
            "write": r"blog\.(agent\.commands|content\.events)",
            "read": r"backend\.agent\.events\.q(\.dlq)?|agent\.(execute|control|content)\.q",
        },
    )
    mgmt_request(
        "PUT",
        f"/permissions/{VHOST}/{AGENT_USER[0]}",
        {
            "configure": "",
            "write": r"blog\.(agent\.events|agent\.retry\.[0-9]+s)",
            "read": r"agent\.(execute|control|content)\.q(\.dlq)?",
        },
    )


def broker_management_healthy() -> bool:
    try:
        mgmt_request("GET", "/overview")
        return True
    except Exception:
        return False


def wait_for_management(timeout_seconds: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if broker_management_healthy():
            return
        time.sleep(2.0)
    raise TimeoutError(f"RabbitMQ management {timeout_seconds}s içinde hazır olmadı")


async def queue_depth_async(queue: str) -> int:
    """Kuyruk derinliği AMQP passive declare ile ölçülür."""

    if queue.startswith("backend."):
        user, password = BACKEND_USER
    else:
        user, password = AGENT_USER
    conn = _depth_connections.get(user)
    if conn is None or conn.is_closed:
        conn = await connect_broker(make_settings(user, password))
        _depth_connections[user] = conn
    channel = await conn.channel(publisher_confirms=False)
    try:
        q = await channel.declare_queue(queue, durable=True, passive=True)
        return int(q.declaration_result.message_count)
    except Exception:
        return 0
    finally:
        await channel.close()


_depth_connections: dict[str, Any] = {}


def queue_depth(queue: str) -> int:
    return run(queue_depth_async(queue))


def depth_is(queue: str, expected: int) -> Any:
    """``wait_until`` için async koşul (koşul içinde ``run()`` çağrılamaz)."""

    async def _condition() -> bool:
        return await queue_depth_async(queue) == expected

    return _condition


def purge_b9_queues() -> None:
    """B9 vhost'unun kuyruk ailesini boşaltır (AMQP purge; rol bazlı bağlantı)."""

    async def _purge_once() -> None:
        for queue in PURGE_TARGETS:
            if queue.startswith("backend."):
                user, password = BACKEND_USER
            else:
                user, password = AGENT_USER
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
    """Koşulu yoklar; koşul içi ``run()`` çağrısı yasak (nested loop hatası)."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = condition()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"koşul {timeout_seconds}s içinde sağlanmadı")


# --------------------------------------------------------------------------
# Zarf üreticileri (B9 kontrol komutları)
# --------------------------------------------------------------------------


def utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_action_result_payload(
    *,
    proposal_id: str,
    outcome: str = "accepted",
    reason: str | None = None,
    applied_article_revision: int | None = 3,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "proposal_id": proposal_id,
        "outcome": outcome,
        "validated_at": utcnow_str(),
    }
    if reason is not None:
        payload["reason"] = reason
    if applied_article_revision is not None and outcome == "accepted":
        payload["applied_article_revision"] = applied_article_revision
    return payload


def make_resume_payload(
    *,
    checkpoint_reference: str | None = None,
    user_ref: str = "u:b9-owner",
) -> dict[str, Any]:
    return {
        "checkpoint_reference": checkpoint_reference or f"agent-collab/{uuid.uuid4()}",
        "user_ref": user_ref,
    }


def make_envelope(
    *,
    message_type: str = "agent.action.result",
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
    producer: Producer = Producer.BACKEND_NET,
    delivery_attempt: int = 0,
    **overrides: Any,
) -> AgentEnvelope:
    defaults: dict[str, Any] = dict(
        message_id=message_id or str(uuid.uuid4()),
        message_type=message_type,
        schema_version=SCHEMA_VERSION,
        run_id=run_id or str(uuid.uuid4()),
        conversation_id=conversation_id or str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        occurred_at=utcnow_str(),
        producer=producer,
        delivery_attempt=delivery_attempt,
        payload=payload if payload is not None else {},
    )
    defaults.update(overrides)
    return AgentEnvelope(**defaults)


def envelope_bytes(envelope: AgentEnvelope) -> bytes:
    return envelope.model_dump_json(exclude_none=True).encode("utf-8")


async def publish_command(
    envelope: AgentEnvelope,
    raw: bytes | None = None,
    *,
    routing_key: str | None = None,
) -> None:
    """Komutu backend rolüyle broker'a yayınlar (confirm bekler)."""

    conn = await connect_broker(make_settings(*BACKEND_USER))
    publisher = BrokerPublisher(conn, ("blog.agent.commands",), make_settings(*BACKEND_USER))
    await publisher.start()
    try:
        result = await publisher.publish_raw(
            "blog.agent.commands",
            routing_key or f"{envelope.message_type}.v1",
            raw or envelope_bytes(envelope),
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            type_name=envelope.message_type,
        )
        assert result.confirmed, f"test yayını confirm almadı: {result.detail}"
    finally:
        await publisher.close()
        await conn.close()


async def fetch_message(
    queue_name: str,
    username: str = AGENT_USER[0],
    password: str = AGENT_USER[1],
) -> tuple[Any, Any, Any]:
    """Kuyruktan bir mesajı ACK'sız çeker: (connection, channel, message|None)."""

    conn = await connect_broker(make_settings(username, password))
    channel = await conn.channel(publisher_confirms=False)
    queue = await channel.declare_queue(queue_name, durable=True, passive=True)
    message = await queue.get(no_ack=False, fail=False)
    return conn, channel, message


async def close_fetch(connection: Any, channel: Any) -> None:
    await channel.close()
    await connection.close()


async def apply_decision(message: Any, decision: Any) -> None:
    """RetryAwareBrokerConsumer._on_message semantiğini testlerde birebir uygular."""

    from messaging.retry import RetryAction

    if decision.action == RetryAction.NACK:
        await message.nack(requeue=False)
    elif decision.action == RetryAction.HOLD:
        return
    else:
        await message.ack()


# --------------------------------------------------------------------------
# DB seed ve pytest fixture'ları
# --------------------------------------------------------------------------


async def seed_job(
    pool: asyncpg.Pool,
    *,
    run_id: str,
    status: str = "queued",
    queue_class: str = "fast",
    deadline_seconds: float = 600.0,
) -> str:
    """B6 sözleşme şeklinde iş satırı ekler; conversation/correlation türetir."""

    conversation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"conv:{run_id}"))
    correlation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:b9seed"))
    envelope_json = json.dumps(
        {
            "message_id": str(uuid.uuid4()),
            "message_type": "agent.execute.requested",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "correlation_id": correlation_id,
            "occurred_at": utcnow_str(),
            "producer": "backend-net",
            "payload": {"user_ref": "user-1", "question": "seed", "language": "tr"},
        },
        ensure_ascii=False,
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO agent.jobs (run_id, status, payload_hash, queue_class, execution_attempt, "
            "deadline_at, accepted_at, conversation_id, correlation_id, envelope) "
            "VALUES ($1, $2, $3, $4, 0, now() + make_interval(secs => $5), now(), $6, $7, $8::jsonb) "
            "ON CONFLICT (run_id) DO UPDATE SET status = EXCLUDED.status",
            uuid.UUID(run_id),
            status,
            "b9-seed-hash",
            queue_class,
            deadline_seconds,
            uuid.UUID(conversation_id),
            uuid.UUID(correlation_id),
            envelope_json,
        )
    return conversation_id


async def inbox_count(pool: asyncpg.Pool, message_id: str) -> int:
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM agent.inbox_messages WHERE message_id = $1",
                uuid.UUID(message_id),
            )
        )


@pytest.fixture(scope="session", autouse=True)
def real_environment() -> None:
    """GATE ön koşulu: gerçek broker + gerçek Postgres; yoksa açık hata."""

    wait_for_management()
    provision_vhost_and_users()

    async def _declare() -> None:
        conn = await connect_broker(make_settings(*ADMIN))
        channel = await conn.channel(publisher_confirms=False)
        from messaging.topology import build_topology

        await declare_topology(channel, build_topology(TEST_TIERS))
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
    apply_b6_contract_schema(AGENT_TEST_DB)


@pytest.fixture()
def clean_broker() -> Any:
    purge_b9_queues()

    async def _all_empty() -> bool:
        depths = [await queue_depth_async(q) for q in PURGE_TARGETS]
        return all(d == 0 for d in depths)

    run(wait_until(_all_empty))
    yield
    purge_b9_queues()


@pytest.fixture()
def db_pool() -> Any:
    ensure_loop()
    pool = run(asyncpg.create_pool(**db_conn_kwargs(AGENT_TEST_DB), min_size=1, max_size=4))

    async def _close() -> None:
        await pool.close()

    yield pool
    run(_close())


@pytest.fixture()
def store(db_pool: Any) -> Any:
    async def _truncate() -> None:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE agent.inbox_messages, agent.jobs, agent.cancel_intents, "
                "agent.outbox_events, agent.run_event_sequences"
            )

    run(_truncate())
    return ControlStore(db_pool, schema="agent")


@pytest.fixture()
def agent_publisher() -> Any:
    """Agent rolüyle confirm'lu publisher (retry kademelerine yayın için)."""

    async def _open() -> Any:
        conn = await connect_broker(make_settings(*AGENT_USER))
        publisher = BrokerPublisher(
            conn, tuple(f"blog.agent.retry.{tier}s" for tier in TEST_TIERS), make_settings(*AGENT_USER)
        )
        await publisher.start()
        return conn, publisher

    async def _close(resources: Any) -> None:
        conn, publisher = resources
        await publisher.close()
        await conn.close()

    resources = run(_open())
    yield resources[1]
    run(_close(resources))


def future_deadline(minutes: float = 10.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
