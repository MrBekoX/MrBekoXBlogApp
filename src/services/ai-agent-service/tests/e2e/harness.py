"""B11 E2E yardımcıları: loop, komut zarfı, intake/worker kurulumu.

Bu modül ``tests/e2e`` paketi içindedir; testler ``from harness import ...``
ile kullanır (L005 uyumlu: yardımcılar ayrı adlandırılmış modülde, conftest
import edilmez).

Komut zarfı: backend'in yazdığı ``agent.execute.requested`` zarfının birebir
kablo karşılığı (B1 sözleşmesi; worker/helpers.py'deki tohumlama yardımcısıyla
aynı şekil — payload alanları ``payloads/agent.execute.requested.schema.json``
ile doğrulanır; intake gerçek doğrulayıcıyla keser).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core.adapters.test_doubles.fake_model import FakeModelProvider
from agent_core.checkpoint.store import FileCheckpointStore

from messaging import BrokerConsumer, BrokerPublisher, IntakeService, JobStore, connect_broker
from messaging.contracts import SCHEMA_VERSION, AgentEnvelope, Producer
from messaging.worker import ExecutionDependencies, ExecutionWorker, WorkerSettings
from messaging.topology import EXECUTE_QUEUE

# --------------------------------------------------------------------------
# Paylaşımlı loop (B4/B6 deseni)
# --------------------------------------------------------------------------


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
    """Coroutine'i paylaşımlı loop'ta ARKA PLANDA başlatır."""

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.create_task(coroutine)


_shared_loop: asyncio.AbstractEventLoop | None = None


async def wait_until(condition: Any, timeout_seconds: float = 20.0, interval: float = 0.05) -> None:
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


# --------------------------------------------------------------------------
# Komut zarfı (backend kablo karşılığı) + gerçek broker yayını
# --------------------------------------------------------------------------


def make_execution_payload(
    question: str = "Bu makaledeki ana fikir nedir?",
    *,
    mode_preference: str = "fast",
    article_id: str | None = None,
    article_revision: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_ref": "user-1",
        "question": question,
        "language": "tr",
        "mode_preference": mode_preference,
        "budget_profile": "default",
    }
    if article_id is not None:
        payload["article_id"] = article_id
        payload["article_revision"] = article_revision or 1
        payload["article_content_hash"] = "a" * 64
    return payload


def make_execute_envelope(
    *,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    message_id: str | None = None,
    deadline_seconds: float = 600.0,
) -> AgentEnvelope:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)
    return AgentEnvelope(
        message_id=message_id or str(uuid.uuid4()),
        message_type="agent.execute.requested",
        schema_version=SCHEMA_VERSION,
        run_id=run_id or str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        deadline_at=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=Producer.BACKEND_NET,
        payload=payload or make_execution_payload(),
    )


async def publish_command(
    envelope: AgentEnvelope,
    settings: Any,
    *,
    raw: bytes | None = None,
    routing_key: str | None = None,
) -> None:
    """Komutu GERÇEK üretici rolüyle (backend_svc) commands exchange'ine yayınlar."""

    conn = await connect_broker(settings)
    publisher = BrokerPublisher(conn, ("blog.agent.commands",), settings)
    try:
        await publisher.start()
        result = await publisher.publish_raw(
            "blog.agent.commands",
            routing_key or f"{envelope.message_type}.v1",
            raw or envelope.model_dump_json(exclude_none=True).encode("utf-8"),
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            type_name=envelope.message_type,
        )
        assert result.confirmed, f"komut yayını confirm almadı: {result.detail}"
    finally:
        await publisher.close()
        await conn.close()


# --------------------------------------------------------------------------
# Intake (gerçek consumer) ve worker (gerçek graph + test sağlayıcı)
# --------------------------------------------------------------------------


class IdleGraphExecutor:
    """Intake'in graph_executor kaydı: intake kabul anında graph ÇALIŞTIRMAZ
    (B4 sözleşmesi); bu casus yalnız çağrılmadığını kanıtlar."""

    is_test_double = True

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, parsed: Any) -> None:
        self.calls.append(parsed)


async def run_intake_once(store: JobStore, settings: Any) -> None:
    """Gerçek BrokerConsumer'ı başlatır; execute kuyruğu boşalana dek tüketir.

    Consumer gerçek IntakeService'i kullanır: B1 doğrulama → tür/üretici
    politikası → inbox tekilleştirme → iş + accepted outbox TEK transaction
    → commit → ACK.
    """

    executor = IdleGraphExecutor()
    intake = IntakeService(store, consumer_name="b11-e2e-intake", graph_executor=executor)
    conn = await connect_broker(settings)
    consumer = BrokerConsumer(conn, EXECUTE_QUEUE, intake.handle_delivery)
    try:
        await consumer.start()

        async def _queue_empty() -> bool:
            from e2e.conftest import queue_depth_async  # paket içi yardımcı

            return await queue_depth_async(EXECUTE_QUEUE) == 0

        await wait_until(_queue_empty, timeout_seconds=15.0)
    finally:
        await consumer.stop()
        await conn.close()
        # kuyruk boşaldıysa ACK'lar commit sonrası verilmiştir; DLQ'da birikme
        # testlerin kendi iddiasıdır


def make_e2e_worker(
    store: JobStore,
    pool: Any,
    *,
    worker_id: str = "b11-e2e-worker",
    model: Any | None = None,
    publisher: Any | None = None,
    content_state: Any | None = None,
    control_store: Any | None = None,
    queue_classes: tuple[str, ...] = ("fast",),
    checkpoint_dir: str | None = None,
) -> ExecutionWorker:
    """Gerçek ExecutionWorker; model YOKSA test sağlayıcısı (is_test_double)."""

    import tempfile

    resolved_model = model or FakeModelProvider(response_text="B11 e2e test yanıtı")
    deps = ExecutionDependencies(model=resolved_model, content_state=content_state)
    settings = WorkerSettings(
        worker_id=worker_id,
        queue_classes=queue_classes,
        lease_seconds=2.0,
        renew_interval_seconds=0.5,
        poll_interval_seconds=0.05,
        max_execution_attempts=3,
    )
    return ExecutionWorker(
        store,
        deps,
        settings=settings,
        publisher=publisher,
        checkpoint_store=FileCheckpointStore(checkpoint_dir or tempfile.mkdtemp(prefix="b11_e2e_ckpt_")),
        control_store=control_store,
    )


async def relay_once(relay: Any) -> Any:
    return await relay.run_once()


def job_row(pool: Any, run_id: str) -> Any:
    async def _fetch() -> Any:
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id)
            )

    return _fetch()


def pending_outbox_envelopes(pool: Any, run_id: str) -> list[dict[str, Any]]:
    async def _fetch() -> list[dict[str, Any]]:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT envelope FROM agent.outbox_events WHERE published_at IS NULL "
                "AND envelope->>'run_id' = $1 ORDER BY created_at",
                run_id,
            )
            return [json.loads(r["envelope"]) for r in rows]

    return _fetch()


def count_jobs(pool: Any) -> int:
    async def _count() -> int:
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT count(*) FROM agent.jobs")

    return _count()
