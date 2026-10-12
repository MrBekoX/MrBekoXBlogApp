"""B6 job store guard testleri: claim/renew/complete/fail/requeue/sweep (gerçek DB).

Ortak store sözleşmesinin (entegrasyon sahibi tanımı) DB karşılığı doğrulanır:
- claim ``FOR UPDATE SKIP LOCKED`` ile tek worker'a gider; execution_attempt
  artar; fencing_token global diziden kesin artar;
- ``renew_lease`` yalnız sahibiyseniz uzatır;
- ``complete_job``/``fail_job`` ATOMİK guard: running + fencing eş + aktif
  iptal niyeti yok; aksi 'rejected' ve gerekçe;
- terminal-öncelik yarışı: tamamlanma commit'i intent'ten önceyse kazanır;
- SINIRLI recovery sınırı: denemesi biten iş sweep'le kalıcı kapanır;
- duplicate (terminal) iş claim ile yeniden BAŞLATILMAZ.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from messaging.contracts import Producer, SCHEMA_VERSION, AgentEnvelope, parse_envelope
from messaging.contracts.payloads import AgentRunCompletedV1

from worker.helpers import (
    expire_lease,
    insert_cancel_intent,
    job_row,
    pending_outbox_events,
    run,
    seed_execute_job,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


# ---------------------------------------------------------------------------
# Migration 0003 şeması
# ---------------------------------------------------------------------------


def test_migration_0003_job_columns_and_cancel_intents(db_pool):
    async def _check() -> None:
        async with db_pool.acquire() as conn:
            cols = await conn.fetch(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'agent' AND table_name = 'jobs'"
            )
            names = {row["column_name"]: row for row in cols}
            for expected in (
                "lease_owner",
                "lease_until",
                "execution_attempt",
                "fencing_token",
                "result_json",
                "queue_class",
                "started_at",
            ):
                assert expected in names, f"jobs.{expected} kolonu yok (migration 0003)"
            assert names["queue_class"]["column_default"] == "'fast'::character varying"
            assert names["execution_attempt"]["column_default"] == "0"

            pk = await conn.fetch(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "JOIN pg_class c ON c.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE i.indisprimary AND n.nspname = 'agent' AND c.relname = 'cancel_intents'"
            )
            assert [r["attname"] for r in pk] == ["run_id"], "cancel_intents PK run_id olmalı"

            # queue_class kısıtı: research kabul, yabancı değer reddedilir
            await conn.execute(
                "INSERT INTO agent.jobs (job_id, run_id, conversation_id, origin_message_id, "
                "payload_hash, payload, envelope, status, queue_class, deadline_at, accepted_at) "
                "VALUES ($1,$2,$3,$4,'h','{}'::jsonb,'{}'::jsonb,'accepted','research',now(),now())",
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
            )
            with pytest.raises(Exception):
                await conn.execute(
                    "INSERT INTO agent.jobs (job_id, run_id, conversation_id, origin_message_id, "
                    "payload_hash, payload, envelope, status, queue_class, deadline_at, accepted_at) "
                    "VALUES ($1,$2,$3,$4,'h','{}'::jsonb,'{}'::jsonb,'accepted','bogus',now(),now())",
                    uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
                )

    run(_check())


# ---------------------------------------------------------------------------
# Claim: tekillik, sayaç, fencing, recovery
# ---------------------------------------------------------------------------


def test_claim_marks_running_increments_attempt_and_allocates_fencing(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))

    claimed = run(store.claim_next_job("w-a", lease_seconds=60, queue_class=("fast",)))
    assert claimed is not None
    assert claimed.run_id == run_id
    assert claimed.execution_attempt == 1
    assert claimed.fencing_token == 1  # dizi 1'den başlar (fixture resetler)
    assert claimed.queue_class == "fast"
    assert claimed.recovered is False
    assert claimed.payload["question"]
    assert claimed.envelope.message_type == "agent.execute.requested"

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "running"
    assert row["lease_owner"] == "w-a"
    assert row["lease_until"] is not None
    assert row["started_at"] is not None


def test_second_worker_claim_gets_nothing_while_lease_active(store, db_pool):
    run(seed_execute_job(db_pool))
    first = run(store.claim_next_job("w-a", lease_seconds=60))
    assert first is not None
    second = run(store.claim_next_job("w-b", lease_seconds=60))
    assert second is None, "SKIP LOCKED: aktif lease'li iş ikinci worker'a gitmemeli"


def test_expired_lease_recovery_claim_limited_by_attempts(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    first = run(store.claim_next_job("w-a", lease_seconds=60))
    assert first is not None

    # Lease aktifken recovery olmaz
    assert run(store.claim_next_job("w-b", lease_seconds=60)) is None

    run(expire_lease(db_pool, run_id))
    second = run(store.claim_next_job("w-b", lease_seconds=60))
    assert second is not None and second.run_id == run_id
    assert second.recovered is True
    assert second.execution_attempt == 2
    assert second.fencing_token > first.fencing_token, "fencing kesin artmalı"

    # SINIRLI recovery: attempt == max iken bir sonraki claim olmaz
    run(expire_lease(db_pool, run_id))
    third = run(store.claim_next_job("w-c", lease_seconds=60, max_execution_attempts=3))
    assert third is not None and third.execution_attempt == 3
    run(expire_lease(db_pool, run_id))
    assert run(store.claim_next_job("w-d", lease_seconds=60, max_execution_attempts=3)) is None


def test_claim_skips_expired_deadline_and_cancel_intent_jobs(store, db_pool):
    # deadline'ı geçmiş iş claim edilmez (terminal kapanışı B7 reaper'da)
    run(seed_execute_job(db_pool, deadline_seconds=-5.0))
    assert run(store.claim_next_job("w-a", lease_seconds=60)) is None

    # aktif iptal niyeti olan iş claim edilmez: iptal yeni yürütme başlatmaz
    run_id_cancel, *_ = run(seed_execute_job(db_pool, deadline_seconds=600.0))
    run(insert_cancel_intent(db_pool, run_id_cancel))
    assert run(store.claim_next_job("w-a", lease_seconds=60)) is None
    assert run(store.has_cancel_intent(run_id_cancel)) is True


# ---------------------------------------------------------------------------
# renew / complete / fail guard
# ---------------------------------------------------------------------------


def test_renew_lease_only_for_owner(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=60))
    assert claimed is not None

    assert run(store.renew_lease(run_id, claimed.fencing_token, 60)) is True
    assert run(store.renew_lease(run_id, claimed.fencing_token + 999, 60)) is False

    run_id2, *_ = run(seed_execute_job(db_pool))
    other = run(store.claim_next_job("w-b", lease_seconds=60))
    assert other is not None
    # w-b kendi işini w-a'nın token'ıyla uzatamaz
    assert run(store.renew_lease(run_id2, claimed.fencing_token, 60)) is False


def test_complete_job_guard_and_terminal_idempotency(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=60))
    assert claimed is not None

    ok = run(store.complete_job(run_id, {"outcome": "completed"}, claimed.fencing_token))
    assert ok.outcome == "completed" and ok.accepted

    again = run(store.complete_job(run_id, {"outcome": "completed"}, claimed.fencing_token))
    assert (again.outcome, again.reason) == ("rejected", "not_running")
    # terminal iş yeniden claim edilmez: duplicate komut işi yeniden başlatmaz
    assert run(store.claim_next_job("w-a", lease_seconds=60)) is None
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "completed"
    assert json.loads(row["result_json"])["outcome"] == "completed"
    assert row["lease_owner"] is None and row["lease_until"] is None


def test_fail_job_shares_complete_guard(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=60))
    assert claimed is not None
    res = run(
        store.fail_job(run_id, {"outcome": "failed", "error_code": "provider_error"}, claimed.fencing_token)
    )
    assert res.outcome == "failed"
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "failed"


def test_fencing_rejects_stale_attempt_result(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    stale = run(store.claim_next_job("w-a", lease_seconds=60))
    assert stale is not None
    run(expire_lease(db_pool, run_id))
    fresh = run(store.claim_next_job("w-b", lease_seconds=60))
    assert fresh is not None and fresh.fencing_token > stale.fencing_token

    rejected = run(store.complete_job(run_id, {"owner": "A-eski"}, stale.fencing_token))
    assert (rejected.outcome, rejected.reason) == ("rejected", "fencing_mismatch")
    # Eski denemenin sonucu YAZILMADI; yeni denemenin sonucu kazanır.
    ok = run(store.complete_job(run_id, {"owner": "B-yeni"}, fresh.fencing_token))
    assert ok.outcome == "completed"
    row = run(job_row(db_pool, run_id))
    assert json.loads(row["result_json"])["owner"] == "B-yeni"
    assert row["execution_attempt"] == 2


def test_cancel_intent_rejects_completion_and_terminal_priority(store, db_pool):
    # 1) Intent ÖNCE: complete guard'ı reddeder; terminal 'cancelled' B7'nin
    #    koşullu UPDATE'inin hakkıdır (iş running kalır).
    run_cancel, *_ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=60))
    assert claimed is not None
    run(insert_cancel_intent(db_pool, run_cancel, requested_by="user-1"))

    rejected = run(store.complete_job(run_cancel, {"outcome": "completed"}, claimed.fencing_token))
    assert (rejected.outcome, rejected.reason) == ("rejected", "cancel_requested")
    row = run(job_row(db_pool, run_cancel))
    assert row["status"] == "running", "intent terminal değildir; running kalır (B7 çevirir)"

    # 2) Completed commit'i intent insert'ünden ÖNCE: tamamlanma KAZANIR.
    run_done, *_ = run(seed_execute_job(db_pool))
    done_claim = run(store.claim_next_job("w-a", lease_seconds=60))
    assert done_claim is not None
    ok = run(store.complete_job(run_done, {"outcome": "completed"}, done_claim.fencing_token))
    assert ok.outcome == "completed"
    run(insert_cancel_intent(db_pool, run_done, requested_by="user-2"))
    late = run(store.complete_job(run_done, {"x": 1}, done_claim.fencing_token))
    assert (late.outcome, late.reason) == ("rejected", "not_running")
    row_done = run(job_row(db_pool, run_done))
    assert row_done["status"] == "completed", "terminal-öncelik: completed korunur"


# ---------------------------------------------------------------------------
# requeue / release / sweep
# ---------------------------------------------------------------------------


def test_requeue_job_returns_to_accepted_with_class_override(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=60))
    assert claimed is not None
    moved_back = run(
        store.requeue_job(run_id, claimed.fencing_token, queue_class="research", reset_attempt=True)
    )
    assert moved_back is True
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "accepted"
    assert row["queue_class"] == "research"
    assert row["execution_attempt"] == 0, "erteleme yürütme başlatmadı; sayaç resetlenir"

    # research kapasitesi yeniden claim eder
    moved = run(store.claim_next_job("w-res", lease_seconds=60, queue_class=("research",)))
    assert moved is not None and moved.run_id == run_id


def test_release_job_lease_enables_fast_recovery(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=300))
    assert claimed is not None
    assert run(store.release_job_lease(run_id, claimed.fencing_token)) is True
    # lease 300s idi ama release ile hemen kurtarılabilir
    recovered = run(store.claim_next_job("w-b", lease_seconds=60))
    assert recovered is not None and recovered.run_id == run_id and recovered.recovered


def test_sweep_closes_attempt_exhausted_jobs_with_outbox_event(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))

    async def _exhaust() -> None:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE agent.jobs SET status='running', lease_owner='w-old', "
                "lease_until = now() - interval '1s', execution_attempt = 3, "
                "fencing_token = nextval('agent.job_fencing_seq') WHERE run_id = $1",
                uuid.UUID(run_id),
            )

    run(_exhaust())
    closed = run(store.fail_expired_jobs_beyond_attempts(3))
    assert closed == [run_id]
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "failed"
    document = json.loads(row["result_json"])
    assert document["error_code"] == "provider_error"
    assert document["execution_attempt"] == 3

    # terminal başarısızlık olayı outbox'a AYNI transaction'da yazıldı
    events = run(pending_outbox_events(db_pool, run_id))
    assert len(events) == 1
    parsed = parse_envelope(events[0].encode("utf-8"))
    assert parsed.envelope.message_type == "agent.run.failed"
    assert parsed.envelope.payload["execution_attempt"] == 3
    # idempotent: ikinci sweep aynı işi kapatmaz
    assert run(store.fail_expired_jobs_beyond_attempts(3)) == []


# ---------------------------------------------------------------------------
# Terminal olayın fencing-guard'lı yazımla AYNI transaction'a girmesi
# ---------------------------------------------------------------------------


def test_complete_job_writes_terminal_outbox_in_same_transaction(store, db_pool):
    run_id, conv_id, corr_id, _ = run(seed_execute_job(db_pool))
    claimed = run(store.claim_next_job("w-a", lease_seconds=60))
    assert claimed is not None

    envelope = AgentEnvelope(
        message_id=str(uuid.uuid4()),
        message_type="agent.run.completed",
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        conversation_id=conv_id,
        correlation_id=corr_id,
        causation_id=claimed.origin_message_id,
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=Producer.AGENT_PY,
        payload=AgentRunCompletedV1(
            event_sequence=0,
            execution_attempt=1,
            fencing_token=str(claimed.fencing_token),
            selected_mode="fast",
            answer="cevap",
            source_scope="general",
            usage={
                "run_id": run_id,
                "total_tokens": 10,
                "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        ).model_dump(exclude_none=True),
    )
    res = run(
        store.complete_job(run_id, {"outcome": "completed"}, claimed.fencing_token, outbox_event=envelope)
    )
    assert res.outcome == "completed"
    events = run(pending_outbox_events(db_pool, run_id))
    assert len(events) == 1
    parsed = parse_envelope(events[0].encode("utf-8"))
    assert parsed.envelope.message_type == "agent.run.completed"
    assert parsed.envelope.payload["event_sequence"] == 1, "sıra DB'de atomik tahsis edildi"
    assert parsed.envelope.payload["fencing_token"] == str(claimed.fencing_token)


def test_rejected_terminal_write_produces_no_outbox_event(store, db_pool):
    run_id, conv_id, corr_id, _ = run(seed_execute_job(db_pool))
    stale = run(store.claim_next_job("w-a", lease_seconds=60))
    assert stale is not None
    run(expire_lease(db_pool, run_id))
    fresh = run(store.claim_next_job("w-b", lease_seconds=60))
    assert fresh is not None

    envelope = AgentEnvelope(
        message_id=str(uuid.uuid4()),
        message_type="agent.run.completed",
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        conversation_id=conv_id,
        correlation_id=corr_id,
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=Producer.AGENT_PY,
        payload=AgentRunCompletedV1(
            event_sequence=0,
            execution_attempt=1,
            fencing_token=str(stale.fencing_token),
            selected_mode="fast",
            answer="eski denemenin cevabı",
            source_scope="general",
            usage={
                "run_id": run_id,
                "total_tokens": 10,
                "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        ).model_dump(exclude_none=True),
    )
    rejected = run(
        store.complete_job(run_id, {"outcome": "completed"}, stale.fencing_token, outbox_event=envelope)
    )
    assert rejected.outcome == "rejected"
    assert run(pending_outbox_events(db_pool, run_id)) == [], "red durumunda outbox kaydı yok"
