"""B6 worker test yardımcıları: loop, tohumlama, worker kurulumu, model double'ları.

Bu modül ``tests/worker`` paketi içindedir; testler ``from worker.helpers import ...``
ile kullanır (pytest prepend modunda ``tests/`` sys.path'e eklenir, paket adı
``worker``'dır — L005 uyumlu: conftest import edilmez, yardımcılar ayrı modülde).
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
from agent_core.ports import CancellationToken, ModelRequest, ModelResponse, ModelUsage

from messaging import AgentEventPublisher, JobStore, OutboxRelay
from messaging.contracts import SCHEMA_VERSION, AgentEnvelope, Producer
from messaging.worker import ExecutionDependencies, ExecutionWorker, WorkerSettings

# --------------------------------------------------------------------------
# Paylaşımlı loop (pytest-asyncio'suz; B4 conftest'teki gerekçe aynen geçerli)
# --------------------------------------------------------------------------


def ensure_loop() -> asyncio.AbstractEventLoop:
    global _shared_loop
    if _shared_loop is None or _shared_loop.is_closed():
        _shared_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_shared_loop)
    return _shared_loop


def run(coroutine: Any) -> Any:
    """Coroutine'i paylaşımlı loop'ta ÇALIŞTIRARAK bekler."""

    ensure_loop()
    assert _shared_loop is not None
    return _shared_loop.run_until_complete(coroutine)


def spawn(coroutine: Any) -> asyncio.Task[Any]:
    """Coroutine'i paylaşımlı loop'ta ARKA PLANDA başlatır (eşzamanlı worker)."""

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
# İş tohumlama (B4 kabul transaction'ının DB sonucu birebir taklit edilir)
# --------------------------------------------------------------------------


def make_execution_payload(
    question: str = "Bu makaledeki ana fikir nedir?",
    *,
    mode_preference: str = "fast",
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_ref": "user-1",
        "question": question,
        "language": "tr",
        "mode_preference": mode_preference,
        "budget_profile": "default",
    }
    if conversation_history:
        payload["conversation_history"] = conversation_history
    return payload


def make_envelope_for(
    run_id: str,
    conversation_id: str,
    correlation_id: str,
    payload: dict[str, Any],
    *,
    deadline_at: datetime,
    schema_version: int = SCHEMA_VERSION,
) -> AgentEnvelope:
    return AgentEnvelope(
        message_id=str(uuid.uuid4()),
        message_type="agent.execute.requested",
        schema_version=schema_version,
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        deadline_at=deadline_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=Producer.BACKEND_NET,
        payload=payload,
    )


async def seed_execute_job(
    pool: Any,
    *,
    payload: dict[str, Any] | None = None,
    queue_class: str = "fast",
    deadline_seconds: float = 600.0,
    wire_version: int = 1,
) -> tuple[str, str, str, datetime]:
    """Kabul edilmiş işi B4'ün yazdığı kolonlarla yazar; (run, conv, corr, deadline) döner.

    ``wire_version`` (K4, migration 0005): kabul zarfının sürümü ve iş satırının
    ``wire_version`` kolonu birlikte yazılır (intake kabulünün DB sonucu).
    """

    run_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    deadline_at = datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)
    envelope = make_envelope_for(
        run_id,
        conversation_id,
        correlation_id,
        payload or make_execution_payload(),
        deadline_at=deadline_at,
        schema_version=wire_version,
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO agent.jobs (job_id, run_id, conversation_id, origin_message_id, "
            "payload_hash, payload, envelope, status, queue_class, deadline_at, accepted_at, wire_version) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12)",
            uuid.uuid4(),
            uuid.UUID(run_id),
            uuid.UUID(conversation_id),
            uuid.UUID(envelope.message_id),
            "seed-hash",
            json.dumps(envelope.payload, ensure_ascii=False),
            envelope.model_dump_json(exclude_none=True),
            "accepted",
            queue_class,
            deadline_at,
            datetime.now(timezone.utc),
            wire_version,
        )
    return run_id, conversation_id, correlation_id, deadline_at


def make_v2_execution_payload(
    question: str = "Berkay Kaplan hangi üniversitede okudu?",
    *,
    topic: str = "who_am_i",
    mode_preference: str = "fast",
    profile_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """v2 execute payload'ı (K3): konu + pinlenmiş profil sürümü."""

    payload = make_execution_payload(question, mode_preference=mode_preference)
    payload["conversation_topic"] = topic
    payload["profile_snapshot"] = profile_snapshot or {
        "profile_id": "berkay-kaplan",
        "revision": 1,
        "content_hash": "4f3b02e187c2b8c04134aa2c80df4b2d8c817377780aca74d2a11e9bf0c1406d",
    }
    return payload


async def job_row(pool: Any, run_id: str) -> Any:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))


async def expire_lease(pool: Any, run_id: str) -> None:
    """Lease'i deterministik biçimde geçmişe çeker (uyku yerine)."""

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent.jobs SET lease_until = now() - interval '1s' WHERE run_id = $1",
            uuid.UUID(run_id),
        )


async def insert_cancel_intent(pool: Any, run_id: str, requested_by: str = "user-1") -> None:
    """B7 ``control_store`` kaydının DB karşılığı (joint testler bütünleştirmede)."""

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO agent.cancel_intents (run_id, requested_by) VALUES ($1, $2) "
            "ON CONFLICT (run_id) DO NOTHING",
            uuid.UUID(run_id),
            requested_by,
        )


async def pending_outbox_events(pool: Any, run_id: str) -> list[Any]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT envelope FROM agent.outbox_events WHERE published_at IS NULL "
            "AND envelope->>'run_id' = $1 ORDER BY created_at",
            run_id,  # zarf alanı metindir (jsonb ->>)
        )
        return [r["envelope"] for r in rows]


# --------------------------------------------------------------------------
# Model test double'ları (worker senaryoları)
# --------------------------------------------------------------------------


class KillModel:
    """İlk çağrıda süreç çökmesini simüle eder: istisna yükselir, iş yarıda kalır."""

    is_test_double = True

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        self.call_count += 1
        raise RuntimeError("worker süreci model çağrısı sırasında çöktü (senaryo)")

    async def stream_complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None, on_delta: Any
    ) -> ModelResponse:
        return await self.complete(request, cancel=cancel)


class GateModel:
    """Çağrıya girip ``release`` bekleyen model: eşzamanlılık/lease senaryoları.

    Uyanırken iptal sinyalini denetler: lease kaybında yürütmenin CANCELLED
    ile kesildiğini gözlemlenebilir kılar.
    """

    is_test_double = True

    def __init__(self, response_text: str = "gate yanıtı") -> None:
        self.response_text = response_text
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.requests: list[ModelRequest] = []
        self.cancelled_while_waiting = False

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        if cancel is not None and cancel.is_cancelled():
            self.cancelled_while_waiting = True
            cancel.raise_if_cancelled()
        return ModelResponse(
            text=self.response_text,
            model_name="gate-model",
            usage=ModelUsage(prompt_tokens=7, completion_tokens=3),
            finished_at=datetime.now(timezone.utc),
        )

    async def stream_complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None, on_delta: Any
    ) -> ModelResponse:
        return await self.complete(request, cancel=cancel)


# --------------------------------------------------------------------------
# Worker / relay kurulumu
# --------------------------------------------------------------------------


def make_worker(
    store: JobStore,
    pool: Any,
    *,
    worker_id: str,
    model: Any | None = None,
    budget: Any | None = None,
    queue_classes: tuple[str, ...] = ("fast",),
    lease_seconds: float = 1.2,
    renew_interval_seconds: float | None = None,
    checkpoint_dir: str | None = None,
    publisher: AgentEventPublisher | None = None,
    max_execution_attempts: int = 3,
    control_store: Any | None = None,
    content_state: Any | None = None,
) -> ExecutionWorker:
    """Test worker'ı kurar; kısa lease/poll ile senaryolar hızlıdır.

    ``checkpoint_dir`` verilmezse GEÇİCİ bir dizin kullanılır: worker'ın
    varsayılan deposu cwd'ye yazmasın (repo kökü temiz kalsın — A8 dev
    deposunun varsayılanı ``.agent_checkpoints``'tir).

    ``control_store`` (W5 bulgusu 1b): B7 terminal üretim bağlantısı —
    complete/fail 'cancel_requested' reddinde ``mark_cancelled_if_running``.
    ``content_state`` (W5 bulgusu 4ii): B8 stale komut projection'u —
    ``ensure_execution_allowed`` yürütme öncesi denetimi.
    """

    import tempfile

    deps = ExecutionDependencies(
        model=model or FakeModelProvider(), budget=budget, content_state=content_state
    )
    settings = WorkerSettings(
        worker_id=worker_id,
        queue_classes=queue_classes,
        lease_seconds=lease_seconds,
        renew_interval_seconds=renew_interval_seconds,
        poll_interval_seconds=0.05,
        max_execution_attempts=max_execution_attempts,
    )
    resolved_checkpoint = checkpoint_dir or tempfile.mkdtemp(prefix="b6_worker_ckpt_")
    return ExecutionWorker(
        store,
        deps,
        settings=settings,
        publisher=publisher,
        checkpoint_store=FileCheckpointStore(resolved_checkpoint),
        control_store=control_store,
    )


def make_relay(store: JobStore, agent_publisher: Any) -> OutboxRelay:
    """Outbox → gerçek broker relay'i (terminal olayın kuyruğa düşmesi için)."""

    return OutboxRelay(store, agent_publisher, batch_size=32, lease_seconds=30.0)
