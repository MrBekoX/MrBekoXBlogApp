"""B6 worker yaşam döngüsü testleri: yürütme, kill/restart, checkpoint devamı.

Kabul ölçütleri (plan B6:400): worker kill/restart ve checkpoint'ten devam
senaryoları GERÇEK broker + gerçek Postgres + gerçek dosya checkpoint deposuyla
doğrulanır. Test double yalnız model sağlayıcıdır (gerçek LLM sağlayıcısı
devrede değildir — progress.md açık riski); bu, broker/DB/checkpoint
davranışlarını geçersiz kılmaz.
"""

from __future__ import annotations

import json
import uuid

import pytest

from messaging.contracts import parse_envelope

from agent_core.adapters.test_doubles.fake_model import FakeModelProvider

from worker.helpers import (
    KillModel,
    expire_lease,
    job_row,
    make_relay,
    make_worker,
    pending_outbox_events,
    run,
    seed_execute_job,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


def _relay_once(store, agent_publisher) -> None:
    run(make_relay(store, agent_publisher).run_once())


def _fetch_and_parse_events() -> list:
    """backend.agent.events.q'daki bekleyen olayları çeker ve zarf olarak döner."""

    from worker.conftest import close_fetch, fetch_event_messages

    fetched = run(fetch_event_messages())
    envelopes = [parse_envelope(message.body) for _conn, _channel, message in fetched]
    if fetched:
        conn, channel, _message = fetched[0]
        close_fetch(conn, channel)
    return envelopes


# ---------------------------------------------------------------------------
# Temel yürütme: claim → çekirdek → terminal + gerçek broker olayı
# ---------------------------------------------------------------------------


def test_worker_executes_fast_job_and_publishes_terminal_event_to_broker(
    store, db_pool, publisher, agent_publisher
):
    run_id, conv_id, corr_id, _ = run(seed_execute_job(db_pool))
    worker = make_worker(store, db_pool, worker_id="w-fast", publisher=publisher)

    result = run(worker.run_once())
    assert (result.idle, result.action) == (False, "completed")
    assert result.run_id == run_id
    assert result.execution_attempt == 1
    assert result.fencing_token == 1

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "completed"
    document = json.loads(row["result_json"])
    assert document["outcome"] == "completed"
    assert document["selected_mode"] == "fast"
    assert document["execution_id"] == f"job-{run_id}"
    assert "uncertain_usage" not in document, "ilk denemede kesinti yok; belirsizlik işareti yok"

    # Terminal olay gerçek broker'a taşınır (relay confirm'lu yayın)
    _relay_once(store, agent_publisher)
    from worker.conftest import queue_depth_async

    async def _events_landed() -> bool:
        return await queue_depth_async("backend.agent.events.q") >= 1

    run(wait_until(_events_landed))

    events = _fetch_and_parse_events()
    terminal = [e for e in events if e.envelope.message_type == "agent.run.completed"]
    assert terminal, f"completed olayı kuyrukta yok: {[e.envelope.message_type for e in events]}"
    payload = terminal[0].envelope.payload
    assert payload["execution_attempt"] == 1
    assert payload["fencing_token"] == "1"
    assert payload["event_sequence"] >= 1
    assert terminal[0].envelope.run_id == run_id
    assert terminal[0].envelope.correlation_id == corr_id


# ---------------------------------------------------------------------------
# Duplicate/terminal iş yeniden başlatılmaz
# ---------------------------------------------------------------------------


def test_completed_job_is_not_restarted_by_next_cycle(store, db_pool, publisher):
    run_id, *_ = run(seed_execute_job(db_pool))
    worker = make_worker(store, db_pool, worker_id="w-fast", publisher=publisher)

    first = run(worker.run_once())
    assert first.action == "completed"
    # Aynı iş için ikinci çevrim: terminal iş claim EDİLMEZ → idle
    second = run(worker.run_once())
    assert second.idle is True
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "completed"
    assert row["execution_attempt"] == 1, "ikinci yürütme olmamalı"


# ---------------------------------------------------------------------------
# Kill/restart + A8 checkpoint'ten devam + deadline korunur + belirsiz maliyet
# ---------------------------------------------------------------------------


def test_worker_kill_and_restart_resumes_from_checkpoint(
    store, db_pool, publisher, checkpoint_dir
):
    payload = {
        "user_ref": "user-1",
        "question": "Bu makalede hangi konu işleniyor?",
        "language": "tr",
        "mode_preference": "fast",
        "budget_profile": "default",
        "conversation_history": [
            {"role": "user", "content": "önceki turda grafikleri anlatmıştın", "created_at": "2026-10-12T09:00:00Z"}
        ],
    }
    run_id, conv_id, corr_id, deadline_at = run(
        seed_execute_job(db_pool, payload=payload, deadline_seconds=600.0)
    )

    # "Worker A": hazırlığı yapıp model çağrısında çöker (süreç kill senaryosu)
    killer_a = KillModel()
    worker_a = make_worker(
        store, db_pool, worker_id="w-a", model=killer_a,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    with pytest.raises(RuntimeError, match="çöktü"):
        run(worker_a.run_once())

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "running", "çöken worker terminal yazmamalı"
    assert row["lease_owner"] == "w-a"
    # A8: hazırlık checkpoint'i kalıcı yazılmış (dosya deposu restart'ı korur)
    checkpoint_id = run(_latest_checkpoint_id(checkpoint_dir, run_id))
    assert checkpoint_id is not None, "hazırlık checkpoint'i yazılmış olmalı (A8)"

    # "Worker B": yeni süreç, AYNI checkpoint deposu; lease bitmiş işi devralır
    run(expire_lease(db_pool, run_id))
    restart_model = FakeModelProvider(response_text="restart sonrası cevap")
    worker_b = make_worker(
        store, db_pool, worker_id="w-b", model=restart_model,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    result = run(worker_b.run_once())

    assert result.action == "completed"
    assert result.recovered is True
    assert result.execution_attempt == 2

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "completed"
    assert row["execution_attempt"] == 2
    # Deadline yeniden yürütmede SIFIRLANMAZ: kabul anındaki değer aynen durur
    assert row["deadline_at"] == deadline_at

    document = json.loads(row["result_json"])
    assert document["execution_attempt"] == 2
    # Kesilen önceki denemenin dış model maliyeti belirsizdir (A2 işareti)
    assert document["uncertain_usage"]["uncertain"] is True
    assert document["uncertain_usage"]["prior_execution_attempts"] == [1]

    # Devam A8 resume yoluyladır: tam olarak bir model çağrısı (yürütme),
    # rota kararı checkpoint'ten okundu — yeniden hesaplanmadı.
    assert len(restart_model.requests) == 1
    # Konuşma geçmişi backend snapshot'ından korundu: prompt önceki turla gelir
    assert "önceki turda grafikleri anlatmıştın" in restart_model.requests[0].prompt

    # Outbox'ta run_resumed ilerlemesi resume yolunun kanıtıdır (A8 girişi)
    events = run(pending_outbox_events(db_pool, run_id))
    kinds = [
        json.loads(e)["payload"].get("kind")
        for e in events
        if json.loads(e)["message_type"] == "agent.run.progressed"
    ]
    assert "run_resumed" in kinds, f"resume ilerlemesi yayınlanmalı; çıkan: {kinds}"


async def _latest_checkpoint_id(checkpoint_dir: str, run_id: str) -> str | None:
    from agent_core.checkpoint.store import FileCheckpointStore

    store = FileCheckpointStore(checkpoint_dir)
    try:
        checkpoint_id, _payload = await store.load_latest(run_id)
        return checkpoint_id
    except Exception:
        return None


def test_recovery_does_not_resurrect_job_with_deadline_passed_during_downtime(
    store, db_pool, publisher, checkpoint_dir
):
    """Deadline'ı downtime'da dolan iş recovery ile yeniden YÜRÜTÜLMEZ.

    Claim süresi geçmiş işi seçmez (terminal kapanışı B7 reaper politikasıdır);
    bu test worker tarafındaki sözleşmeyi sabitler: deadline sıfırlanıp iş
    yeniden başlatılmaz.
    """
    run_id, *_ = run(seed_execute_job(db_pool, deadline_seconds=600.0))
    killer = KillModel()
    worker_a = make_worker(
        store, db_pool, worker_id="w-a", model=killer,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    with pytest.raises(RuntimeError, match="çöktü"):
        run(worker_a.run_once())

    row = run(job_row(db_pool, run_id))
    deadline_before = row["deadline_at"]

    async def _expire_deadline() -> None:
        # Downtime'ın deadline'ı tükettiği durumun deterministik taklidi.
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE agent.jobs SET deadline_at = now() - interval '1s' WHERE run_id = $1",
                uuid.UUID(run_id),
            )

    run(_expire_deadline())
    run(expire_lease(db_pool, run_id))
    worker_b = make_worker(
        store, db_pool, worker_id="w-b", checkpoint_dir=checkpoint_dir, publisher=publisher
    )
    result = run(worker_b.run_once())
    assert result.idle is True, "deadline'ı geçmiş iş recovery claim'ine girmez"

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "running", "iş B7 reaper'ına kadar running kalır; sıfırlanıp yeniden başlatılmaz"
    assert deadline_before is not None


# ---------------------------------------------------------------------------
# needs_input: iş beklemeye döner (terminal değildir), checkpoint korunur
# ---------------------------------------------------------------------------


def test_needs_input_outcome_requeues_job_for_resume(store, db_pool, publisher):
    from worker.helpers import make_execution_payload

    # Kişisel bağlam sinyali ("benim proj") → needs_clarification → needs_input
    payload = make_execution_payload("Benim projemde hangi Python sürümü kurulu?")
    run_id, *_ = run(seed_execute_job(db_pool, payload=payload))

    worker = make_worker(store, db_pool, worker_id="w-a", publisher=publisher)
    result = run(worker.run_once())

    assert result.action == "needs_input", f"çıkan: {result.action} {result.detail}"
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "accepted", "needs_input terminal değildir; iş beklemeye döner"
    assert row["result_json"] is None
    events = run(pending_outbox_events(db_pool, run_id))
    types = [json.loads(e)["message_type"] for e in events]
    assert "agent.run.needs_input" in types


# ---------------------------------------------------------------------------
# Bütçe yeniden yürütmede SIFIRLANMAZ (plan B6:398)
# ---------------------------------------------------------------------------


def test_budget_reservations_survive_recovery_execution(store, db_pool, publisher, checkpoint_dir):
    """Kesilen denemenin bütçe rezervasyonu, recovery'de KORUNUR.

    Aynı BudgetStore örneği iki worker'a da verilir (üretim karşılığı: bütçe
    deposu run_id ile anahtarlanır ve süreç restart'ı onu sıfırlamaz — worker
    ``deps.budget``'ı hem execute_plan'a hem resume'a geçirir). Deneme 1 model
    rezervasyonu AÇIK kalırken kesilir (release yolu çalışmaz); deneme 2 yeni
    rezervasyon açar. Sıfırlanmış olsaydı toplam ayrılan 1 olurdu; korunsaydı 2.
    """
    from agent_core.adapters.test_doubles.fake_state import FakeBudgetStore
    from agent_core.ports import BudgetKind

    run_id, *_ = run(seed_execute_job(db_pool))
    budget = FakeBudgetStore(model_call_capacity=3)

    worker_a = make_worker(
        store, db_pool, worker_id="w-a", model=KillModel(), budget=budget,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    with pytest.raises(RuntimeError, match="çöktü"):
        run(worker_a.run_once())

    assert budget.reserved == 1, "deneme 1'in model rezervasyonu kesinti anında açık kalmalı"

    run(expire_lease(db_pool, run_id))
    worker_b = make_worker(
        store, db_pool, worker_id="w-b", budget=budget,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    result = run(worker_b.run_once())
    assert result.action == "completed"

    # Bütçe sıfırlanmaz: deneme 1'in rezervasyonu hâlâ SAYALI (reset → 1 olurdu).
    assert budget.reserved == 2, (
        f"kesilen denemenin rezervasyonu korunmalı; bulunan: {budget.reserved}"
    )
    # Deneme 2'nin fiili kullanımı commit edildi (FakeModelProvider: 10+5 token).
    assert budget.committed[BudgetKind.MODEL_CALL] == 15
    usage = run(_budget_usage(budget, run_id))
    assert usage.committed[BudgetKind.MODEL_CALL] == 15


async def _budget_usage(budget, run_id: str):
    return await budget.usage(run_id)
