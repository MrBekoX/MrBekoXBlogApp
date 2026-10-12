"""W5 bütünleştirme bağlantı testleri: worker'ın B7 iptal terminali ve B8 stale guard'ı.

Bulgusu 1b: complete/fail 'cancel_requested' ile reddedildiğinde terminali
``mark_cancelled_if_running`` üretir — worker bu çağrıyı artık yapar (kontrol
deposu bağlandığında); aksi halde iş deadline reaper'ına dek 'running' asılı
kalır.

Bulgusu 4ii: makale üçlüsü taşıyan komutun snapshot revizyonu, B8 projection'ın
bildiği kaldırma revizyonundan eskiyse yürütme BAŞLAMAZ (``StaleExecutionRejected``
→ anlaşılır ``stale_snapshot`` terminali).

Gerçek Postgres + gerçek JobStore (tests/worker conftest migration şeması);
model test double'dır.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from messaging.contracts.payloads import ArticleContentChangedV1
from messaging.content import ContentSyncState
from messaging.control_store import ControlStore

from worker.helpers import (
    GateModel,
    job_row,
    make_execution_payload,
    make_worker,
    pending_outbox_events,
    run,
    seed_execute_job,
    spawn,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


async def _await_task(task: Any) -> Any:
    return await task


def _triple_payload(article_id: str, revision: int) -> dict[str, Any]:
    payload = make_execution_payload()
    payload["article_id"] = article_id
    payload["article_revision"] = revision
    payload["article_content_hash"] = "a" * 64
    return payload


def _state_with_removal(article_id: str, revision: int) -> ContentSyncState:
    state = ContentSyncState()
    state.apply_article_changed(
        ArticleContentChangedV1(article_id=article_id, article_revision=revision, action="unpublished")
    )
    return state


# ---------------------------------------------------------------------------
# Bulgusu 1b: 'cancel_requested' redsinde worker terminali B7 kuralıyla üretir
# ---------------------------------------------------------------------------


def test_cancel_requested_rejection_finalizes_cancelled_via_worker(
    store, db_pool, publisher
):
    run_id, conv_id, corr_id, _ = run(seed_execute_job(db_pool))
    control = ControlStore(db_pool, schema="agent")
    gate = GateModel()
    worker = make_worker(
        store, db_pool, worker_id="w-a", model=gate, publisher=publisher, control_store=control
    )

    task = spawn(worker.run_once())
    run(wait_until(gate.entered.is_set, timeout_seconds=10))

    # Yürütme SIRASINDA iptal niyeti kaydedilir (running: terminal değildir).
    intent = run(
        control.record_cancel_intent(
            run_id, requested_by="w5-test", conversation_id=conv_id, correlation_id=corr_id
        )
    )
    assert intent.outcome == "recorded"
    assert run(job_row(db_pool, run_id))["status"] == "running"

    gate.release.set()
    result = run(_await_task(task))
    assert result.run_id == run_id

    # Worker: complete_job 'cancel_requested' ile reddedildi → mark_cancelled_if_running.
    assert result.action == "aborted_cancel", f"çıkan: {result.action} {result.detail}"
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "cancelled", "terminal reaper beklemeden üretildi"
    events = run(pending_outbox_events(db_pool, run_id))
    cancelled = [json.loads(e) for e in events if json.loads(e)["message_type"] == "agent.run.cancelled"]
    assert len(cancelled) == 1, f"tam 1 iptal olayı; çıkan: {[e['message_type'] for e in events]}"


def test_without_control_store_rejection_stays_running_for_b7(store, db_pool, publisher):
    """Kontrol deposu BAĞLANMADIYSA davranış değişmez: iş B7'ye (reaper) kalır.

    Bu, ``control_store`` bağlantısının opsiyonel olduğunu ve bağlanmadığında
    worker'ın terminal yazmadığını sabitler — bağlamanın kendisi bulgusu 1b
    düzeltmesidir.
    """

    run_id, _conv, _corr, _ = run(seed_execute_job(db_pool))
    gate = GateModel()
    worker = make_worker(store, db_pool, worker_id="w-a", model=gate, publisher=publisher)

    task = spawn(worker.run_once())
    run(wait_until(gate.entered.is_set, timeout_seconds=10))

    async def _raw_intent() -> None:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent.cancel_intents (run_id, requested_by) VALUES ($1, $2) "
                "ON CONFLICT (run_id) DO NOTHING",
                uuid.UUID(run_id),
                "w5-test",
            )

    run(_raw_intent())
    gate.release.set()
    result = run(_await_task(task))

    assert result.action == "aborted_lease_lost"
    assert run(job_row(db_pool, run_id))["status"] == "running", (
        "kontrol deposu yoksa terminali B7 üretir; worker dokunmaz"
    )


# ---------------------------------------------------------------------------
# Bulgusu 4ii: stale komut yürütme BAŞLAMADAN reddedilir
# ---------------------------------------------------------------------------


def test_stale_command_is_rejected_before_execution(store, db_pool, publisher):
    article_id = str(uuid.uuid4())
    run_id, *_ = run(seed_execute_job(db_pool, payload=_triple_payload(article_id, revision=4)))

    model = GateModel()  # çağrılırsa test kırılır: yürütme başlamamalı
    state = _state_with_removal(article_id, revision=5)
    worker = make_worker(
        store, db_pool, worker_id="w-a", model=model, publisher=publisher, content_state=state
    )

    result = run(worker.run_once())

    assert result.action == "failed", f"çıkan: {result.action} {result.detail}"
    assert "eski komut" in result.detail
    assert model.entered.is_set() is False, "stale komutta model çağrısı olmaz"

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "failed"
    document = json.loads(row["result_json"])
    assert document["error_code"] == "stale_snapshot"
    # Terminal failed olayı outbox'a yazıldı (tek terminal kaydı).
    events = run(pending_outbox_events(db_pool, run_id))
    types = [json.loads(e)["message_type"] for e in events]
    assert types.count("agent.run.failed") == 1


def test_fresh_command_with_higher_revision_executes(store, db_pool, publisher):
    """Kaldırma revizyonundan YENİ snapshot guard'a takılmaz: yürütme BAŞLAR.

    Not: terminal 'completed' iddia edilmez — makale üçlüsü taşıyan bağlamda
    çekirdek article kapsamıyla çalışır ve citation taşımayan test double'ının
    sonucu B5 yayın kuralınca completed'a çevrilmez (başka kuralın alanı). Bu
    testin iddiası: guard YALNIZ eski komutu keser; revizyon 6 (> kaldırma 5)
    model çağrısına kadar gider ve red stale_snapshot DEĞİLDİR.
    """

    article_id = str(uuid.uuid4())
    run_id, *_ = run(seed_execute_job(db_pool, payload=_triple_payload(article_id, revision=6)))

    state = _state_with_removal(article_id, revision=5)
    model = GateModel()
    model.release.set()  # bekleme yok: yalnız 'model çağrısına girildi' gözlemi
    worker = make_worker(
        store, db_pool, worker_id="w-a", model=model, publisher=publisher, content_state=state
    )

    result = run(worker.run_once())

    assert model.entered.is_set(), "yürütme başladı: guard güncel snapshot'ı kesmez"
    row = run(job_row(db_pool, run_id))
    document = json.loads(row["result_json"]) if row["result_json"] else {}
    assert document.get("error_code") != "stale_snapshot"


def test_command_without_article_triple_skips_stale_guard(store, db_pool, publisher):
    """Makalesiz genel sorular üçlü taşımaz: guard devreye girmez (denetim yapılmaz)."""

    run_id, *_ = run(seed_execute_job(db_pool))
    worker = make_worker(
        store,
        db_pool,
        worker_id="w-a",
        publisher=publisher,
        content_state=_state_with_removal(str(uuid.uuid4()), revision=1),
    )

    result = run(worker.run_once())
    assert result.action == "completed"
    assert run(job_row(db_pool, run_id))["status"] == "completed"
