"""B4 intake test kurulumu: gerçek broker + gerçek PostgreSQL.

Bu dizin B4 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez (L005:
``tests/intake`` __init__.py'li pakettir, conftest.py güvenlidir).

Ortam:
- Broker: docker compose rabbitmq (B2 ile aynı vhost/kullanıcılar; idempotent
  provizyon + admin ile topology declare — K3: üretimde declarer backend'dir).
- DB: ``blogdb_agent_test`` scratch veritabanı (blogdb_dev'in agent şemasına
  dokunmaz; B3 paralel çalışmasını bozmaz). Session başında düşürülüp yeniden
  yaratılır ve AYNI Alembic migration zinciri (``migrations/``) programatik
  ``upgrade head`` ile uygulanır; her test tabloları truncate eder.
- Parola KODA GİRMEZ: docker/.env çalışma anında okunur (sır kuralı).

pytest-asyncio kuruludur diye bir varsayım YOKTUR: B2 paketindeki gibi
senkron testler ``run()`` ile coroutine çalıştırır; fixture'lar senktir.
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
    BrokerPublisher,
    BrokerSettings,
    IntakeService,
    JobStore,
    connect_broker,
    declare_topology,
)
from messaging.contracts import SCHEMA_VERSION, AgentEnvelope, Producer
from messaging.topology import BACKEND_EVENTS_QUEUE, EXECUTE_QUEUE

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
SERVICE_ROOT = REPO_ROOT / "src" / "services" / "ai-agent-service"

MGMT = broker_management_url()
#: B4 testlerine ÖZEL vhost: plan B2 kuralı ("ortam ön eki veya ayrı vhost ile
#: ayırma") uyarınca B2/B3'ün blogapp_dev vhost'unu paylaşmayız — paralel
#: agent'ların purge/drain işlemleri bu paketin teslimlerini yutmasın
#: (2026-10-11'de B3 .NET testleriyle aynı vhostta gözlemlendi: broker log
#: kanıtı 'b3-purge'/'b3-drain'/'backend-net-tests' bağlantıları).
VHOST = "blogapp_dev_b4"
ADMIN = ("blogapp", "blogapp_dev")
BACKEND_USER = ("backend_svc", "backend_svc_dev")
AGENT_USER = ("agent_svc", "agent_svc_dev")

AGENT_TEST_DB = "blogdb_agent_test"
INTAKE_QUEUE_PURGE_TARGETS = (EXECUTE_QUEUE, f"{EXECUTE_QUEUE}.dlq", BACKEND_EVENTS_QUEUE)


def ensure_loop() -> asyncio.AbstractEventLoop:
    """Paylaşımlı loop'u döndürür ve current yapar.

    ``set_event_loop`` gereklidir çünkü alembic ortamının ``asyncio.run``'ı
    çıkışta current loop'u None'a çeker; asyncpg ``create_pool`` (0.32'de
    senkron) deprecated ``get_event_loop`` yolunu kullanır ve None iken
    Python 3.13'te RuntimeError fırlatır. Argüman değerlendirmesi run()
    çağrısından ÖNCE olduğundan senkron çağrılardan önce bu işlev çağrılmalıdır.
    """

    global _shared_loop
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_shared_loop)
    return _shared_loop


def run(coroutine: Any) -> Any:
    """Coroutine'i paylaşımlı oturum loop'unda çalıştırır (pytest-asyncio'suz).

    Tek loop zorunludur: asyncpg havuzu ve aio-pika bağlantıları yaratıldıkları
    loop'a bağlanır; her çağrıda taze ``asyncio.run`` açmak "attached to a
    different loop" hataları üretir.
    """

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.run_until_complete(coroutine)


_shared_loop: asyncio.AbstractEventLoop | None = None


@pytest.fixture(scope="session", autouse=True)
def _close_shared_loop() -> Any:
    yield
    global _shared_loop

    async def _close_depth() -> None:
        for conn in _depth_connections.values():
            try:
                await conn.close()
            except Exception:
                pass
        _depth_connections.clear()

    if _shared_loop is not None and not _shared_loop.is_closed():
        try:
            _shared_loop.run_until_complete(_close_depth())
        except Exception:
            pass
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
# Broker yardımcıları (B2 conftest deseninin intake paketine uyarlaması)
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
    """Management API isteği; broker başka agent testleriyle yüklüyken kopan
    keep-alive bağlantılarına karşı sınırlı, artan backoff'lu retry yapar."""

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
            time.sleep(0.5 * (2**attempt))  # 0.5, 1, 2, 4 s
    raise RuntimeError(f"management isteği {method} {path} başarısız: {last_error}")


def mgmt_try(method: str, path: str, body: Any = None, auth: tuple[str, str] = ADMIN) -> int:
    try:
        mgmt_request(method, path, body, auth)
        return 200
    except urllib.error.HTTPError as exc:
        return exc.code


def provision_vhost_and_users() -> None:
    """B2 ile aynı izin modeli (idempotent); detaylar tests/messaging_broker/conftest.py."""

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
    """Kuyruk derinliği AMQP passive declare ile ölçülür (declaration_result).

    Management HTTP API'si, broker başka agent testleriyle yüklüyken bağlantı
    koparıyor; passive declare AMQP üzerinden çalışır ve agent/backend rolü
    kendi kuyruğunda izinlidir (D013 pasif declare izin kuralı).
    """

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
        return 0  # kuyruk henüz yoksa/kanal koptuysa yoklama tekrar dener
    finally:
        await channel.close()


_depth_connections: dict[str, Any] = {}


def queue_depth(queue: str) -> int:
    """Senkron derinlik okuması; YALNIZ wait_until DIŞINDA kullanılır."""

    return run(queue_depth_async(queue))


def purge_intake_queues() -> None:
    """Kuyruk boşaltma AMQP ``queue.purge()`` ile yapılır; statü denetimi açıktır
    (sessiz başarısızlık izin verilmez — B2'de management /contents uç noktası
    kullanılıyordu; burada AMQP yolu yük altında daha güvenilirdir). Broker
    başka agent testleriyle yüklüyken bağlantı kopmalarına karşı sınırlı
    retry yapılır."""

    async def _purge_once() -> None:
        for queue in INTAKE_QUEUE_PURGE_TARGETS:
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
        except (OSError, ConnectionError) as exc:  # aio-pika/aiormq kopmaları
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"kuyruk purge başarısız: {last_error}")


async def wait_until(condition: Any, timeout_seconds: float = 20.0, interval: float = 0.2) -> None:
    """Koşulu yoklar; koşul senkron bool döndürebilir veya await edilebilir
    (coroutine) döndürebilir. KOŞUL İÇİNDE ``run()`` ÇAĞRILMAZ — nested
    run_until_complete aynı loop'ta RuntimeError üretir."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = condition()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"koşul {timeout_seconds}s içinde sağlanmadı")


def job_count_is(store: Any, expected: int) -> Any:
    """``wait_until`` için async koşul: jobs sayısı beklenen değere ulaştı mı."""

    async def _condition() -> bool:
        return await store.count_jobs() == expected

    return _condition


def queue_depth_is(queue: str, expected: int) -> Any:
    async def _condition() -> bool:
        return await queue_depth_async(queue) == expected

    return _condition


# --------------------------------------------------------------------------
# Envelope üreticileri (sözleşme modelleriyle)
# --------------------------------------------------------------------------

DEADLINE = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_execution_payload(question: str = "Bu makalede hangi konu işleniyor?") -> dict[str, Any]:
    return {
        "user_ref": "user-1",
        "question": question,
        "language": "tr",
        "mode_preference": "auto",
        "budget_profile": "default",
    }


def make_envelope(
    *,
    message_type: str = "agent.execute.requested",
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    message_id: str | None = None,
    producer: Producer = Producer.BACKEND_NET,
    **overrides: Any,
) -> AgentEnvelope:
    defaults: dict[str, Any] = dict(
        message_id=message_id or str(uuid.uuid4()),
        message_type=message_type,
        schema_version=SCHEMA_VERSION,
        run_id=run_id or str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=producer,
        payload=payload if payload is not None else make_execution_payload(),
    )
    # Null taşınmaz kuralı (TransportModel): opsiyonel alan yalnız gerektiğinde eklenir.
    if message_type == "agent.execute.requested":
        defaults["deadline_at"] = DEADLINE
    defaults.update(overrides)
    return AgentEnvelope(**defaults)


def envelope_bytes(envelope: AgentEnvelope) -> bytes:
    return envelope.model_dump_json(exclude_none=True).encode("utf-8")


async def publish_command(
    envelope: AgentEnvelope, raw: bytes | None = None, *, routing_key: str | None = None
) -> None:
    """Komutu gerçek üretici rolüyle (backend_svc) broker'a yayınlar.

    ``routing_key`` verilmezse türün kendi kuyruğuna yönlendirilir; tür
    politikası testinde yanlış türü execute kuyruğuna manuel göndermek için
    override kullanılır.
    """

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
    queue_name: str = EXECUTE_QUEUE,
    username: str = AGENT_USER[0],
    password: str = AGENT_USER[1],
) -> tuple[Any, Any, Any]:
    """Kuyruktan bir mesajı ACK'sız çeker: (connection, channel, message|None).

    Mesaj ACK'sız kaldığı sürece teslim edilmiş sayılır; kanal kapatılırsa
    broker mesajı kuyruğa geri koyar (redelivery: ``redelivered=True``).
    backend.agent.events.q gibi backend kuyrukları için kimlik override edilir.
    """

    conn = await connect_broker(make_settings(username, password))
    channel = await conn.channel(publisher_confirms=False)
    queue = await channel.declare_queue(queue_name, durable=True, passive=True)
    message = await queue.get(no_ack=False, fail=False)
    return conn, channel, message


async def close_fetch(connection: Any, channel: Any) -> None:
    """Kanalı kapatır: ACK'sız teslimler brokerca kuyruğa geri konur."""

    await channel.close()
    await connection.close()


class RecordingExecutor:
    """B6 graph yürütücüsü yerine geçen casus: intake kabul akışı onu ASLA çağırmaz."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, parsed: Any) -> None:
        self.calls.append(parsed)


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
    purge_intake_queues()
    # Yüklü brokerda purge gecikebilir; kuyruklar gerçekten boşalana kadar
    # beklenmezse önceki testin kalıntısı sonraki testin yoklamasını bozar.

    async def _all_targets_empty() -> bool:
        depths = [await queue_depth_async(q) for q in INTAKE_QUEUE_PURGE_TARGETS]
        return all(d == 0 for d in depths)

    run(wait_until(_all_targets_empty))
    yield
    purge_intake_queues()


@pytest.fixture()
def db_pool() -> Any:
    ensure_loop()  # asyncpg create_pool lazy Pool döndürür; await ile init edilir
    pool = run(asyncpg.create_pool(**db_conn_kwargs(AGENT_TEST_DB), min_size=1, max_size=4))

    async def _close() -> None:
        await pool.close()

    yield pool
    run(_close())


@pytest.fixture()
def truncated_db(db_pool: Any) -> Any:
    async def _truncate() -> None:
        async with db_pool.acquire() as conn:
            await conn.execute("TRUNCATE agent.budget_reservations, agent.run_budgets, "
                               "agent.inbox_messages, agent.jobs, agent.outbox_events")

    run(_truncate())
    return db_pool


@pytest.fixture()
def store(truncated_db: Any) -> JobStore:
    return JobStore(truncated_db, schema="agent")


@pytest.fixture()
def executor_spy() -> RecordingExecutor:
    return RecordingExecutor()


@pytest.fixture()
def intake(store: JobStore, executor_spy: RecordingExecutor) -> IntakeService:
    return IntakeService(store, consumer_name="intake", graph_executor=executor_spy)


@pytest.fixture()
def agent_publisher() -> Any:
    """Relay testleri için agent rolüyle confirm'lu publisher."""

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
