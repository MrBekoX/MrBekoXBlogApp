"""K4 (gerçek PostgreSQL): run wire sürümü izolasyonu — migration 0005 tetikleyicileri.

- ``db_pool``: ``agent.worker_wire_max`` bildirmeyen oturum = v2'yi bilmeyen ESKİ
  worker. ``wire_v2_pool``: ayarı 2 bildiren YENİ worker havuzu.
- Eski oturum v2 işini claim edemez, terminal/lease güncellemesi yapamaz
  (tetikleyici güncellemeyi atlar); yeni oturum v1 backlog'u ve v2 run'larını
  birlikte işler. Outbox tetikleyicisi run'ın sürümüyle uyuşmayan zarfı reddeder.
- Recovery/restart ve deneme tükenmesi run'ın sürümünü korur.

Bu paket gerçek broker + gerçek Postgres ister (conftest ``real_environment``;
skip yok — sahte başarı üretilmez).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import asyncpg
import pytest

from messaging import AgentEventPublisher, JobStore
from messaging.wire import compose_run_envelope

from worker.helpers import (
    expire_lease,
    job_row,
    make_execution_payload,
    make_v2_execution_payload,
    make_worker,
    run,
    seed_execute_job,
)


async def _outbox(pool: Any, run_id: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT routing_key, envelope FROM agent.outbox_events WHERE envelope->>'run_id' = $1 "
            "ORDER BY created_at, outbox_id",
            run_id,
        )
    return [{"routing_key": r["routing_key"], "envelope": json.loads(r["envelope"])} for r in rows]


def _progress_envelope(run_id: str, conversation_id: str, correlation_id: str, version: int):
    return compose_run_envelope(
        schema_version=version,
        message_type="agent.run.progressed",
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        payload={"event_sequence": 0, "kind": "run_started", "message": "başladı", "detail": {}},
    )


def test_old_session_cannot_claim_v2_job(db_pool: Any, wire_v2_pool: Any) -> None:
    run_id, *_ = run(seed_execute_job(db_pool, payload=make_v2_execution_payload(), wire_version=2))
    old_store = JobStore(db_pool, schema="agent")
    new_store = JobStore(wire_v2_pool, schema="agent")

    assert run(old_store.claim_next_job("old-worker", lease_seconds=30)) is None
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "accepted" and row["execution_attempt"] == 0  # dokunulmadı

    claimed = run(new_store.claim_next_job("new-worker", lease_seconds=30))
    assert claimed is not None and claimed.run_id == run_id and claimed.wire_version == 2


def test_v1_backlog_and_v2_run_coexist(db_pool: Any, wire_v2_pool: Any) -> None:
    v1_run, *_ = run(seed_execute_job(db_pool, payload=make_execution_payload()))
    v2_run, *_ = run(seed_execute_job(db_pool, payload=make_v2_execution_payload(), wire_version=2))
    old_store = JobStore(db_pool, schema="agent")
    new_store = JobStore(wire_v2_pool, schema="agent")

    first = run(old_store.claim_next_job("old-worker", lease_seconds=30))
    assert first is not None and first.run_id == v1_run and first.wire_version == 1
    # Eski worker v2 işini alamaz (kuyruğun başı v2 olsa bile güncelleme atlanır).
    assert run(old_store.claim_next_job("old-worker", lease_seconds=30)) is None

    second = run(new_store.claim_next_job("new-worker", lease_seconds=30))
    assert second is not None and second.run_id == v2_run and second.wire_version == 2


def test_old_session_terminal_write_on_v2_job_is_isolated(db_pool: Any, wire_v2_pool: Any) -> None:
    run_id, *_ = run(seed_execute_job(db_pool, payload=make_v2_execution_payload(), wire_version=2))
    claimed = run(JobStore(wire_v2_pool, schema="agent").claim_next_job("new-worker", lease_seconds=30))
    assert claimed is not None

    result = run(JobStore(db_pool, schema="agent").complete_job(run_id, {"outcome": "completed"}, claimed.fencing_token))

    assert not result.accepted and result.reason == "wire_isolated"
    assert run(job_row(db_pool, run_id))["status"] == "running"
    assert not run(JobStore(db_pool, schema="agent").renew_lease(run_id, claimed.fencing_token, 30))
    assert run(JobStore(wire_v2_pool, schema="agent").renew_lease(run_id, claimed.fencing_token, 30))


def test_outbox_trigger_rejects_envelope_of_other_version(db_pool: Any, wire_v2_pool: Any) -> None:
    run_id, conversation_id, correlation_id, _ = run(
        seed_execute_job(db_pool, payload=make_v2_execution_payload(), wire_version=2)
    )
    store = JobStore(wire_v2_pool, schema="agent")

    async def _insert(version: int) -> None:
        async with wire_v2_pool.acquire() as conn:
            async with conn.transaction():
                await store._insert_outbox_event(  # noqa: SLF001 - tetikleyici sınaması
                    conn,
                    envelope=_progress_envelope(run_id, conversation_id, correlation_id, version),
                    created_at=datetime.now(timezone.utc),
                )

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(_insert(1))
    run(_insert(2))
    rows = run(_outbox(db_pool, run_id))
    assert [r["routing_key"] for r in rows] == ["agent.run.progressed.v2"]


def test_recovery_reclaim_keeps_run_wire_version(db_pool: Any, wire_v2_pool: Any) -> None:
    run_id, *_ = run(seed_execute_job(db_pool, payload=make_v2_execution_payload(), wire_version=2))
    store = JobStore(wire_v2_pool, schema="agent")
    first = run(store.claim_next_job("worker-a", lease_seconds=30))
    run(expire_lease(wire_v2_pool, run_id))

    second = run(store.claim_next_job("worker-b", lease_seconds=30))

    assert second is not None and second.recovered and second.wire_version == 2
    assert second.fencing_token > first.fencing_token


def test_attempt_exhaustion_failure_is_published_in_run_version(db_pool: Any, wire_v2_pool: Any) -> None:
    run_id, *_ = run(seed_execute_job(db_pool, payload=make_v2_execution_payload(), wire_version=2))
    store = JobStore(wire_v2_pool, schema="agent")
    run(store.claim_next_job("worker-a", lease_seconds=30, max_execution_attempts=1))
    run(expire_lease(wire_v2_pool, run_id))

    # Eski oturum deneme tükenmesini kapatamaz (güncelleme atlanır, olay yok).
    assert run(JobStore(db_pool, schema="agent").fail_expired_jobs_beyond_attempts(1)) == []
    assert run(_outbox(db_pool, run_id)) == []

    assert run(store.fail_expired_jobs_beyond_attempts(1)) == [run_id]
    (row,) = run(_outbox(db_pool, run_id))
    assert row["routing_key"] == "agent.run.failed.v2"
    assert row["envelope"]["schema_version"] == 2


def test_v2_and_v1_runs_execute_end_to_end_in_their_own_versions(db_pool: Any, wire_v2_pool: Any, tmp_path) -> None:
    """Gerçek çekirdek + gerçek DB: her run'ın TÜM olayları kendi sürümünde (v2'de mode_selected)."""

    v1_run, *_ = run(seed_execute_job(db_pool, payload=make_execution_payload("Python nedir?")))
    v2_run, *_ = run(
        seed_execute_job(
            db_pool,
            payload=make_v2_execution_payload("CQRS nedir?", topic="auto"),
            wire_version=2,
        )
    )
    store = JobStore(wire_v2_pool, schema="agent")
    publisher = AgentEventPublisher(wire_v2_pool, schema="agent", min_progress_interval_seconds=0.0)
    worker = make_worker(store, wire_v2_pool, worker_id="new-worker", publisher=publisher,
                         checkpoint_dir=str(tmp_path / "ckpt"), lease_seconds=30.0)

    first = run(worker.run_once())
    second = run(worker.run_once())

    assert {first.run_id, second.run_id} == {v1_run, v2_run}
    for run_id, version in ((v1_run, 1), (v2_run, 2)):
        rows = run(_outbox(db_pool, run_id))
        assert rows, f"{run_id} için olay yok"
        assert {r["envelope"]["schema_version"] for r in rows} == {version}
        assert all(r["routing_key"].endswith(f".v{version}") for r in rows)
        types = [r["envelope"]["message_type"] for r in rows]
        assert ("agent.run.mode_selected" in types) is (version == 2)
        terminal = rows[-1]["envelope"]
        assert terminal["message_type"].startswith("agent.run.")
        if version == 2 and terminal["message_type"] in ("agent.run.completed", "agent.run.partially_completed"):
            assert "run_intent" in terminal["payload"]
    assert run(job_row(db_pool, v2_run))["wire_version"] == 2
