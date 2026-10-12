"""GERÇEK JobStore × GERÇEK ControlStore: B6 fencing + B7 iptal yarışı (bulgusu 2).

tests/control/test_control_cancel.py terminal-öncelik yarışını B6 test
double'ıyla, tests/worker/test_job_store_claims.py intent'i ham SQL ile
koşuyordu; iki GERÇEK store'un AYNI migration-kurulu şemadaki birleşimi
bu pakete aittir. Senaryolar:

(a) intent-önce → ``complete_job`` 'rejected(cancel_requested)' → worker
    sözleşmesi ``mark_cancelled_if_running`` → 'cancelled' + TAM 1
    agent.run.cancelled outbox kaydı;
(b) complete-önce → ``record_cancel_intent`` 'already_terminal' + mark
    'untouched';
(c) intent INSERT ile complete commit'inin EŞZAMANLI yarışı (iki asyncio
    task): tek terminal sonucu, kayıp iptal yok;
(d) 'accepted' durumlunda iptal (bulgusu 1a): pending finalizer işi
    yürütmeden kapatır; iş ne claim edilebilir ne reaper'a asılı kalır.

Şema GERÇEK alembic zinciridir (0001→0003): ``fencing_token`` BIGINT ve
``ck_jobs_status`` 'accepted' dahil — B7 scratch DDL'i DEĞİL.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from messaging.contracts import SCHEMA_VERSION, AgentEnvelope, Producer, parse_envelope
from messaging.control_store import CancelIntentOutcome, ControlStore
from messaging.job_store import ClaimedJob, JobStore
from messaging.reaper import DeadlineReaper

from .conftest import run


# ---------------------------------------------------------------------------
# Yardımcılar: gerçek B4 kabulü (parse_envelope + accept_execution)
# ---------------------------------------------------------------------------


def _execute_envelope(
    run_id: str,
    conversation_id: str,
    correlation_id: str,
    *,
    deadline_seconds: float = 600.0,
) -> AgentEnvelope:
    occurred = datetime.now(timezone.utc)
    deadline = occurred + timedelta(seconds=deadline_seconds)
    return AgentEnvelope(
        message_id=str(uuid.uuid4()),
        message_type="agent.execute.requested",
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        occurred_at=occurred.strftime("%Y-%m-%dT%H:%M:%SZ"),
        deadline_at=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=Producer.BACKEND_NET,
        payload={
            "user_ref": "user-1",
            "question": "Bu makalede hangi konu işleniyor?",
            "language": "tr",
            "mode_preference": "auto",
            "budget_profile": "default",
        },
    )


def _accepted_job(job_store: JobStore, *, deadline_seconds: float = 600.0) -> tuple[str, str, str]:
    """Execute komutunu B4'ün üretim yolundan kabul ettirir: inbox+job+outbox tek transaction."""

    run_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    envelope = _execute_envelope(
        run_id, conversation_id, correlation_id, deadline_seconds=deadline_seconds
    )
    parsed = parse_envelope(envelope.model_dump_json(exclude_none=True).encode("utf-8"))
    outcome = run(job_store.accept_execution(parsed, consumer_name="intake-w5int"))
    assert outcome.outcome == "created", f"kabul oluşmadı: {outcome.outcome} ({outcome.detail})"
    return run_id, conversation_id, correlation_id


def _claim(job_store: JobStore, worker_id: str) -> ClaimedJob:
    claimed = run(job_store.claim_next_job(worker_id, lease_seconds=60))
    assert claimed is not None, "bekleyen iş claim edilemedi"
    return claimed


async def _raw_status(pool: Any, run_id: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id)
        )


async def _outbox_events(pool: Any, run_id: str, message_type: str) -> list[Any]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT message_id, envelope FROM agent.outbox_events "
            "WHERE envelope->>'run_id' = $1 AND message_type = $2 ORDER BY created_at",
            run_id,
            message_type,
        )


def _cancel(
    control_store: ControlStore,
    run_id: str,
    conversation_id: str,
    correlation_id: str,
) -> Any:
    return run(
        control_store.record_cancel_intent(
            run_id,
            requested_by="w5-integration",
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
    )


def _mark(control_store: ControlStore, run_id: str, conversation_id: str, correlation_id: str) -> str:
    return run(
        control_store.mark_cancelled_if_running(
            run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
    )


# ---------------------------------------------------------------------------
# Şema: scratch sözleşme DDL'i DEĞİL, gerçek migration şeması geçerli
# ---------------------------------------------------------------------------


def test_real_migration_schema_is_in_effect(db_pool: Any) -> None:
    async def _check() -> None:
        async with db_pool.acquire() as conn:
            token_type = await conn.fetchval(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'agent' AND table_name = 'jobs' AND column_name = 'fencing_token'"
            )
            assert token_type == "bigint", (
                f"fencing_token tipi {token_type!r}: B7 scratch DDL'i (TEXT) değil gerçek migration geçerli olmalı"
            )
            status_check = await conn.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_jobs_status' AND conrelid = 'agent.jobs'::regclass"
            )
            assert status_check is not None and "accepted" in status_check, (
                f"ck_jobs_status 'accepted' içermeli: {status_check}"
            )
            intent_pk = await conn.fetchval(
                "SELECT column_name FROM information_schema.key_column_usage "
                "WHERE table_schema = 'agent' AND table_name = 'cancel_intents'"
            )
            assert intent_pk == "run_id"

    run(_check())


# ---------------------------------------------------------------------------
# (a) intent-önce: complete 'rejected' → mark_cancelled_if_running → cancelled
# ---------------------------------------------------------------------------


def test_intent_first_complete_rejected_then_cancelled(
    job_store: JobStore, control_store: ControlStore, db_pool: Any
) -> None:
    run_id, conversation_id, correlation_id = _accepted_job(job_store)
    claimed = _claim(job_store, "w-a")

    intent = _cancel(control_store, run_id, conversation_id, correlation_id)
    assert intent.outcome == CancelIntentOutcome.RECORDED  # running: niyet terminal değildir

    write = run(job_store.complete_job(run_id, {"outcome": "completed"}, claimed.fencing_token))
    assert (write.outcome, write.reason) == ("rejected", "cancel_requested"), (
        "aktif cancel intent'i varken completed YAZILAMAZ (fencing + intent guard)"
    )

    # Worker sözleşmesi: red sonrası terminali B7 koşullu UPDATE'i üretir.
    assert _mark(control_store, run_id, conversation_id, correlation_id) == "cancelled"
    assert run(_raw_status(db_pool, run_id)) == "cancelled"

    events = run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))
    assert len(events) == 1, "terminal olay durum değişikliğiyle TEK seferde üretilir"

    # İptal edilmiş iş yeniden claim EDİLMEZ: yürütme başlamaz.
    assert run(job_store.claim_next_job("w-b", lease_seconds=60)) is None


# ---------------------------------------------------------------------------
# (b) complete-önce: already_terminal + mark 'untouched'
# ---------------------------------------------------------------------------


def test_complete_first_cancel_is_already_terminal(
    job_store: JobStore, control_store: ControlStore, db_pool: Any
) -> None:
    run_id, conversation_id, correlation_id = _accepted_job(job_store)
    claimed = _claim(job_store, "w-a")

    write = run(job_store.complete_job(run_id, {"outcome": "completed"}, claimed.fencing_token))
    assert write.outcome == "completed"

    intent = _cancel(control_store, run_id, conversation_id, correlation_id)
    assert intent.outcome == CancelIntentOutcome.ALREADY_TERMINAL  # tamamlanma kazanır
    assert _mark(control_store, run_id, conversation_id, correlation_id) == "untouched"

    assert run(_raw_status(db_pool, run_id)) == "completed"
    assert run(_outbox_events(db_pool, run_id, "agent.run.cancelled")) == []


# ---------------------------------------------------------------------------
# (c) eşzamanlı yarış: intent INSERT ⟷ complete commit (iki asyncio task)
# ---------------------------------------------------------------------------


def test_concurrent_intent_insert_vs_complete_commit_single_terminal(
    job_store: JobStore, control_store: ControlStore, db_pool: Any
) -> None:
    """Kayıp iptal yok, çift terminal yok: PG serializasyonuyla iki sonuçtan BİRİ.

    - complete kazanır → intent 'already_terminal'; durum 'completed'; iptal olayı YOK.
    - intent kazanır → complete 'rejected(cancel_requested)'; durum 'cancelled';
      tam 1 iptal olayı (terminali mark üretir — worker sözleşmesi).
    """

    completed_wins = 0
    cancelled_wins = 0
    rounds = 30

    for _round in range(rounds):
        run_id, conversation_id, correlation_id = _accepted_job(job_store)
        claimed = _claim(job_store, "w-race")

        async def _race(rid: str, conv: str, corr: str, token: int) -> tuple[Any, Any]:
            intent_task = asyncio.create_task(
                control_store.record_cancel_intent(
                    rid,
                    requested_by="w5-integration",
                    conversation_id=conv,
                    correlation_id=corr,
                )
            )
            complete_task = asyncio.create_task(
                job_store.complete_job(rid, {"outcome": "completed"}, token)
            )
            intent_result, write_result = await asyncio.gather(intent_task, complete_task)
            return intent_result, write_result

        intent, write = run(_race(run_id, conversation_id, correlation_id, claimed.fencing_token))

        if write.outcome == "completed":
            assert intent.outcome == CancelIntentOutcome.ALREADY_TERMINAL, (
                "complete commit'i intent'ten önceyse tamamlanma kazanır"
            )
            assert run(_raw_status(db_pool, run_id)) == "completed"
            assert run(_outbox_events(db_pool, run_id, "agent.run.cancelled")) == []
            completed_wins += 1
        else:
            assert (write.outcome, write.reason) == ("rejected", "cancel_requested"), (
                f"beklenmeyen red gerekçesi: {write.reason}"
            )
            assert intent.outcome == CancelIntentOutcome.RECORDED, (
                "kayıp iptal yok: niyet kaydedildiyse terminal 'cancelled' olmak zorunda"
            )
            assert _mark(control_store, run_id, conversation_id, correlation_id) == "cancelled"
            assert run(_raw_status(db_pool, run_id)) == "cancelled"
            assert len(run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))) == 1
            cancelled_wins += 1

    assert completed_wins + cancelled_wins == rounds


# ---------------------------------------------------------------------------
# (d) 'accepted' durumunda iptal (bulgusu 1a): sonsuz 'accepted' kalmaz
# ---------------------------------------------------------------------------


def test_accepted_job_with_cancel_intent_finalizes_and_never_stuck(
    job_store: JobStore, control_store: ControlStore, db_pool: Any
) -> None:
    run_id, conversation_id, correlation_id = _accepted_job(job_store)
    assert run(_raw_status(db_pool, run_id)) == "accepted", "gerçek B4 kabulü 'accepted' yazar"

    intent = _cancel(control_store, run_id, conversation_id, correlation_id)
    assert intent.outcome == CancelIntentOutcome.QUEUED_CANCELLED, (
        "yürütme başlamamış iş ('accepted' dahil) niyetle ANINDA terminal olur"
    )
    assert intent.job_status == "cancelled"
    assert run(_raw_status(db_pool, run_id)) == "cancelled"
    assert len(run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))) == 1

    # Niyetli iş bir daha claim EDİLEMEZ (yürütme hiç başlamaz).
    assert run(job_store.claim_next_job("w-a", lease_seconds=60)) is None

    # Reaper çevrimi ikinci olay ÜRETMEZ (finalizer idempotent; iş zaten terminal).
    result = run(DeadlineReaper(control_store).run_once())
    assert result.queued_cancelled == 0
    assert len(run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))) == 1


def test_accepted_job_with_expired_deadline_is_closed_by_reaper(
    job_store: JobStore, control_store: ControlStore, db_pool: Any
) -> None:
    """Deadline'ı dolan 'accepted' iş reaper'ca kapatılır: aktif backlog'ta asılı kalmaz."""

    run_id, _conversation_id, _correlation_id = _accepted_job(job_store, deadline_seconds=-30.0)
    assert run(_raw_status(db_pool, run_id)) == "accepted"

    result = run(DeadlineReaper(control_store).run_once())
    assert result.expired_failed == 1
    assert run(_raw_status(db_pool, run_id)) == "failed"
    assert len(run(_outbox_events(db_pool, run_id, "agent.run.failed"))) == 1

    # Deadline'ı geçmiş iş claim EDİLMEZ (terminal kapanış reaper'ındadır).
    assert run(job_store.claim_next_job("w-a", lease_seconds=60)) is None


def test_accepted_job_without_intent_is_claimable(job_store: JobStore, db_pool: Any) -> None:
    """'accepted' bekleyendir: niyeti olmayan kabul işi üretim claim yoluyla yürütülür."""

    run_id, _conversation_id, _correlation_id = _accepted_job(job_store)
    claimed = _claim(job_store, "w-a")
    assert claimed.run_id == run_id
    assert claimed.execution_attempt == 1
    assert claimed.fencing_token == 1  # gerçek diziden: BIGINT (fixture 1'e sarar)
    assert claimed.recovered is False
    assert run(_raw_status(db_pool, run_id)) == "running"
