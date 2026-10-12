"""B11 E2E test kurulumu: gerçek broker + gerçek PostgreSQL + gerçek worker hattı.

Bu conftest yalnız ``tests/e2e`` paketini etkiler (L005). Diğer fazların
conftest'lerinden kopyalanan provizyon/DB deseninin B11'e uyarlanmasıdır;
tek-KAYNAK davranış farkı yoktur (izin regex'leri D013 modeliyle aynı).

Model yolu: GERÇEK model sağlayıcısı YOK (ortam kuralı). ``FakeModelProvider``
``is_test_double=True`` işaretli test sağlayıcısıdır; suite sonuçları gerçek
model davranışı olarak RAPORLANMAZ (rapor §sınırlamalar).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg
import pytest

from e2e.harness import ensure_loop, run, wait_until  # paket içi modül (L005 deseni)

from messaging import (
    AgentEventPublisher,
    BrokerPublisher,
    BrokerSettings,
    JobStore,
    OutboxRelay,
    connect_broker,
    declare_topology,
)
from messaging.topology import BACKEND_EVENTS_QUEUE, CONTENT_QUEUE, CONTROL_QUEUE, EXECUTE_QUEUE

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
SERVICE_ROOT = REPO_ROOT / "src" / "services" / "ai-agent-service"

MGMT = "http://127.0.0.1:15672/api"
#: B11 E2E'ye ÖZEL vhost (L009; .NET B11 suite'i blogapp_w7_b11net kullanır).
VHOST = "blogapp_w7_b11"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")
RABBITMQ_CONTAINER = "blogapp-rabbitmq"

#: B11 E2E'ye ÖZEL scratch DB.
AGENT_TEST_DB = "blogdb_agent_b11_e2e"

QUEUE_PURGE_TARGETS = (
    EXECUTE_QUEUE,
    f"{EXECUTE_QUEUE}.dlq",
    CONTROL_QUEUE,
    f"{CONTROL_QUEUE}.dlq",
    CONTENT_QUEUE,
    f"{CONTENT_QUEUE}.dlq",
    BACKEND_EVENTS_QUEUE,
    f"{BACKEND_EVENTS_QUEUE}.dlq",
)

__all__ = [
    "VHOST",
    "AGENT_TEST_DB",
    "ADMIN",
    "BACKEND_USER",
    "AGENT_USER",
    "QUEUE_PURGE_TARGETS",
    "make_settings",
    "mgmt_request",
    "run_broker_down",
    "run_broker_up",
    "queue_depth_async",
    "fetch_event_envelopes",
]


# --------------------------------------------------------------------------
# Loop (B4/B6 deseni: pytest-asyncio'suz paylaşımlı loop)
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
    """GERÇEK alembic zincirini programatik çalıştırır (0001→0003)."""

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


# --------------------------------------------------------------------------
# Broker management (stdlib): provizyon + purge + gerçek kesinti
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


def provision_vhost_and_users() -> None:
    """vhost + servis kullanıcıları (D013 izin modeli; B2 conftest ile aynı regex'ler)."""

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
            "write": r"blog\.agent\.events",
            "read": r"agent\.(execute|control|content)\.q(\.dlq)?",
        },
    )


def purge_queues() -> None:
    """Ana kuyruk ve DLQ'ları boşaltır (management /contents uç noktası; 405 atlanmaz)."""

    vhost = urllib.parse.quote(VHOST, safe="")
    for queue in QUEUE_PURGE_TARGETS:
        try:
            mgmt_request("DELETE", f"/queues/{vhost}/{queue}/contents")
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 405):  # 404: kuyruk henüz yok (geçerli)
                raise


def run_broker_down() -> None:
    """GERÇEK broker kesintisi: rabbitmqctl stop_app (docker exec)."""

    if shutil.which("docker") is None:
        pytest.fail("docker CLI yok: gerçek broker kesintisi koşulamaz (sahte benzetim YAPILMAZ)")
    subprocess.run(
        ["docker", "exec", RABBITMQ_CONTAINER, "rabbitmqctl", "stop_app"],
        check=True,
        timeout=120,
        capture_output=True,
    )


def run_broker_up() -> None:
    subprocess.run(
        ["docker", "exec", RABBITMQ_CONTAINER, "rabbitmqctl", "start_app"],
        check=True,
        timeout=120,
        capture_output=True,
    )
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if broker_management_healthy():
            return
        time.sleep(1.0)
    raise TimeoutError("broker 120s içinde ayakta gelmedi")


async def queue_depth_async(queue: str) -> int:
    vhost = urllib.parse.quote(VHOST, safe="")
    try:
        info = mgmt_request("GET", f"/queues/{vhost}/{queue}")
        return int(info.get("messages", 0))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 0
        raise


async def fetch_event_envelopes(limit: int = 32) -> list[Any]:
    """backend.agent.events.q'daki olayları ACK'sız çeker; zarf listesi döner.

    Bağlantı kanal kapanışıyla brokerca geri konur; testler ACK'sız okumayı
    yalnız doğrulama için yapar (backend projection gerçek .NET suite'indedir).
    """

    from messaging.contracts import parse_envelope

    conn = await connect_broker(make_settings(*BACKEND_USER))
    channel = await conn.channel(publisher_confirms=False)
    queue = await channel.declare_queue(BACKEND_EVENTS_QUEUE, durable=True, passive=True)
    envelopes: list[Any] = []
    for _ in range(limit):
        message = await queue.get(no_ack=False, fail=False)
        if message is None:
            break
        envelopes.append(parse_envelope(message.body))
    await channel.close()
    await conn.close()
    return envelopes


async def fetch_control_message() -> tuple[Any, Any, Any] | None:
    """agent.control.q'dan bir mesajı ACK'sız çeker: (conn, channel, message)|None."""

    conn = await connect_broker(make_settings(*AGENT_USER))
    channel = await conn.channel(publisher_confirms=False)
    queue = await channel.declare_queue(CONTROL_QUEUE, durable=True, passive=True)
    message = await queue.get(no_ack=False, fail=False)
    if message is None:
        await channel.close()
        await conn.close()
        return None
    return conn, channel, message



# --------------------------------------------------------------------------
# pytest fixture'ları
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def real_environment() -> None:
    """GATE ön koşulu: gerçek broker + gerçek Postgres; yoksa AÇIK hata."""

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
        except Exception as exc:  # vhost boot penceresi
            last_error = exc
            time.sleep(5.0)
    else:
        raise AssertionError(f"topology kurulamadı: {last_error}")

    require_postgres()
    recreate_test_database()
    run_agent_migrations(AGENT_TEST_DB)


@pytest.fixture(scope="session", autouse=True)
def _close_shared_loop() -> Any:
    yield
    import e2e.harness as harness_mod

    if harness_mod._shared_loop is not None and not harness_mod._shared_loop.is_closed():
        harness_mod._shared_loop.close()
    harness_mod._shared_loop = None


@pytest.fixture(autouse=True)
def clean_environment(real_environment: None) -> Any:
    purge_queues()
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
def agent_publisher() -> Any:
    """Relay'in kullandığı gerçek agent rolü publisher (confirm'lu)."""

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
def event_publisher(db_pool: Any) -> AgentEventPublisher:
    """Worker'ın kullandığı gerçek olay yayıncısı (outbox aynı-transaction)."""

    return AgentEventPublisher(db_pool, schema="agent")


@pytest.fixture()
def relay(store: JobStore, agent_publisher: Any) -> OutboxRelay:
    """Outbox → gerçek broker relay'i (make_relay deseni)."""

    return OutboxRelay(store, agent_publisher, batch_size=32, lease_seconds=30.0)
