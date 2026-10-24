"""B6 worker test kurulumu: gerçek broker + gerçek PostgreSQL + gerçek checkpoint dosya deposu.

Bu dizin B6 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez (L005:
``tests/worker`` __init__.py'li pakettir, conftest.py güvenlidir).

Ortam (B4/B5 conftest deseninin B6'ya uyarlaması; L009 dispatch kuralı):
- Broker: ÖZEL vhost ``blogapp_w5_b6`` — B2/B3 (blogapp_dev), B4
  (blogapp_dev_b4), B5 (blogapp_dev_b5) paketleriyle kuyruk paylaşımı yok.
- DB: ``blogdb_agent_test_b6`` scratch veritabanı (blogdb_dev'e yazılmaz);
  Alembic zinciri 0001→0003 programatik ``upgrade head`` ile kurulur; her
  test tabloları truncate eder ve fencing dizisini 1'e sarar (deterministik
  token iddiaları için).
- Parola KODA GİRMEZ: docker/.env çalışma anında okunur (sır kuralı).

pytest-asyncio varsayımı YOKTUR: yardımcılar ``worker.helpers`` modülündedir
(conftest import edilmez); senkron testler ``run()``/``spawn()`` kullanır.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from infra_environment import broker_address, broker_management_url, postgres_credentials, postgres_host, postgres_migration_url, postgres_port

from worker.helpers import ensure_loop, run, wait_until  # worker.helpers: paket içi modül

from messaging import (
    AgentEventPublisher,
    BrokerPublisher,
    BrokerSettings,
    JobStore,
    connect_broker,
    declare_topology,
)
from messaging.topology import BACKEND_EVENTS_QUEUE, EXECUTE_QUEUE

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
SERVICE_ROOT = REPO_ROOT / "src" / "services" / "ai-agent-service"

MGMT = broker_management_url()
#: B6 testlerine ÖZEL vhost (L009: her faz kendi vhost'unu kullanır).
VHOST = "blogapp_w5_b6"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")

AGENT_TEST_DB = "blogdb_agent_test_b6"
QUEUE_PURGE_TARGETS = (
    EXECUTE_QUEUE,
    f"{EXECUTE_QUEUE}.dlq",
    BACKEND_EVENTS_QUEUE,
    f"{BACKEND_EVENTS_QUEUE}.dlq",
)

__all__ = [
    "VHOST",
    "AGENT_TEST_DB",
    "QUEUE_PURGE_TARGETS",
    "make_settings",
    "queue_depth_async",
    "queue_depth_is",
    "fetch_event_messages",
    "close_fetch",
]


@pytest.fixture(scope="session", autouse=True)
def _close_shared_loop() -> Any:
    yield

    async def _close_depth() -> None:
        for conn in _depth_connections.values():
            try:
                await conn.close()
            except Exception:
                pass
        _depth_connections.clear()

    import worker.helpers as helpers

    if helpers._shared_loop is not None and not helpers._shared_loop.is_closed():
        try:
            helpers._shared_loop.run_until_complete(_close_depth())
        except Exception:
            pass
        helpers._shared_loop.close()
    helpers._shared_loop = None


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
    """Gerçek Postgres yoksa test oturumu AÇIK HATA ile durur (skip = sahte başarı yok)."""

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
    """Alembic zincirini programatik çalıştırır (0001→0003; CLI ile aynı env.py)."""

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
# Broker yardımcıları (B4/B5 conftest deseninin B6'ya uyarlaması)
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
            raise
        except (urllib.error.URLError, OSError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"management isteği {method} {path} başarısız: {last_error}")


def provision_vhost_and_users() -> None:
    """B2 izin modeliyle ÖZEL vhost kurulumu (idempotent; declarer kimliği admin)."""

    mgmt_request("PUT", f"/vhosts/{VHOST}")
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


def purge_queues() -> None:
    """Test kuyruklarını AMQP purge ile boşaltır; kopmalara karşı sınırlı retry."""

    async def _purge_once() -> None:
        for queue in QUEUE_PURGE_TARGETS:
            user, password = BACKEND_USER if queue.startswith("backend.") else AGENT_USER
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


def queue_depth_is(queue: str, expected: int) -> Any:
    async def _condition() -> bool:
        return await queue_depth_async(queue) == expected

    return _condition


async def fetch_event_messages(limit: int = 32) -> list[tuple[Any, Any, Any]]:
    """backend.agent.events.q'dan mesajları ACK'sız çeker (bağlantı çağıranında)."""

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
    # Broker bu checkout'ta dış müdahaleyle restart edilebiliyor (B6-rapor F3:
    # management API AMQP dinleyicisinden önce açılır); declare penceresi bu
    # geçişe tahammül etsin diye 8 deneme x 5s ayrılır (B4/B5'teki 3x'ten geniş).
    for _ in range(8):
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
    pool = run(asyncpg.create_pool(**db_conn_kwargs(AGENT_TEST_DB), min_size=1, max_size=6))

    async def _reset() -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE agent.inbox_messages, agent.jobs, agent.outbox_events, "
                "agent.run_event_sequences, agent.cancel_intents"
            )
            await conn.execute("ALTER SEQUENCE agent.job_fencing_seq RESTART WITH 1")

    run(_reset())

    async def _close() -> None:
        await pool.close()

    yield pool
    run(_close())


@pytest.fixture()
def store(db_pool: Any) -> JobStore:
    return JobStore(db_pool, schema="agent")


@pytest.fixture()
def wire_v2_pool(db_pool: Any) -> Any:
    """Yeni worker havuzu: bağlantı başlangıcında ``agent.worker_wire_max=2`` bildirir.

    ``db_pool`` (ayar yok → tetikleyici 1 varsayar) eski worker oturumunu temsil
    eder; bu havuz v2 satırlarını claim/kapatabilen yeni worker'ı (migration 0005).
    ``db_pool``'a bağımlıdır: tablo sıfırlaması ondan gelir.
    """

    ensure_loop()
    pool = run(
        asyncpg.create_pool(
            **db_conn_kwargs(AGENT_TEST_DB),
            min_size=1,
            max_size=4,
            server_settings={"agent.worker_wire_max": "2"},
        )
    )

    async def _close() -> None:
        await pool.close()

    yield pool
    run(_close())


@pytest.fixture()
def relay_store(db_pool: Any) -> JobStore:
    """Relay testleri için ayrı JobStore örneği (aynı pool)."""

    return JobStore(db_pool, schema="agent")


@pytest.fixture()
def publisher(db_pool: Any) -> AgentEventPublisher:
    """Seyrekleştirme penceresi testlerde kısa (varsayılan 2s yerine 0.05s)."""

    return AgentEventPublisher(db_pool, schema="agent", min_progress_interval_seconds=0.05)


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


@pytest.fixture()
def checkpoint_dir(tmp_path: Path) -> str:
    return str(tmp_path / "checkpoints")
