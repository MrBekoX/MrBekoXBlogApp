"""K4 (gerçek PostgreSQL): iptal / deadline / reaper / drain terminal olayları run sürümünde.

- Yeni worker havuzu (``agent.worker_wire_max=2``) v2 işini v2 olayıyla kapatır.
- Eski oturum (ayar yok) v2 işine dokunamaz: tetikleyici güncellemeyi atlar,
  terminal olay yazılmaz (iptal finalizer'ı ``WireIsolationError`` ile geri alınır,
  koşullu yollar "dokunulmadı" döner).
- Rollback drain'i (``wire_drain --cancel`` çekirdeği) v2 işlerini v2
  ``agent.run.cancelled`` (gerekçe ``wire_v2_rollback``) ile kapatır.

Bu paket gerçek broker + gerçek Postgres ister (conftest ``real_environment``;
skip yok — sahte başarı üretilmez).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest

from messaging.control_store import WIRE_DRAIN_REASON, ControlStore, WireIsolationError
from messaging.reaper import DeadlineReaper
from messaging.wire_drain import cancel_active, check_active

from .conftest import AGENT_TEST_DB, db_conn_kwargs, ensure_loop, insert_cancel_intent, run, seed_job

pytestmark = pytest.mark.usefixtures("clean_broker")


@pytest.fixture()
def wire_v2_store(store: Any) -> Any:
    """Yeni worker oturumu: ``agent.worker_wire_max=2`` (``store`` tabloları sıfırlar)."""

    ensure_loop()
    pool = run(
        asyncpg.create_pool(
            **db_conn_kwargs(AGENT_TEST_DB),
            min_size=1,
            max_size=2,
            server_settings={"agent.worker_wire_max": "2"},
        )
    )
    yield ControlStore(pool, schema="agent")

    async def _close() -> None:
        await pool.close()

    run(_close())


async def _events(pool: Any, run_id: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT routing_key, envelope FROM agent.outbox_events WHERE envelope->>'run_id' = $1",
            run_id,
        )
    return [{"routing_key": r["routing_key"], "envelope": json.loads(r["envelope"])} for r in rows]


async def _status(pool: Any, run_id: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))


def test_cancel_of_pending_v2_job_emits_v2_cancelled(store: Any, wire_v2_store: Any, db_pool: Any) -> None:
    run_id = str(uuid.uuid4())
    conversation_id = run(seed_job(db_pool, run_id=run_id, status="queued", wire_version=2))

    # Eski oturum: güncelleme atlanır → finalizer geri alınır, olay yok.
    with pytest.raises(WireIsolationError):
        run(store.record_cancel_intent(run_id, "backend-net", conversation_id=conversation_id,
                                       correlation_id=str(uuid.uuid4())))
    assert run(_status(db_pool, run_id)) == "queued"
    assert run(_events(db_pool, run_id)) == []

    result = run(wire_v2_store.record_cancel_intent(run_id, "backend-net", conversation_id=conversation_id,
                                                    correlation_id=str(uuid.uuid4()), reason="kullanıcı"))

    assert result.outcome == "queued_cancelled"
    (event,) = run(_events(db_pool, run_id))
    assert event["routing_key"] == "agent.run.cancelled.v2"
    assert event["envelope"]["schema_version"] == 2


def test_running_v2_job_cancel_finalized_only_by_new_session(store: Any, wire_v2_store: Any, db_pool: Any) -> None:
    run_id = str(uuid.uuid4())
    conversation_id = run(seed_job(db_pool, run_id=run_id, status="running", execution_attempt=1, wire_version=2))
    run(insert_cancel_intent(db_pool, run_id))

    assert run(store.mark_cancelled_if_running(run_id, conversation_id=conversation_id,
                                               correlation_id=str(uuid.uuid4()))) == "untouched"
    assert run(wire_v2_store.mark_cancelled_if_running(run_id, conversation_id=conversation_id,
                                                       correlation_id=str(uuid.uuid4()))) == "cancelled"
    (event,) = run(_events(db_pool, run_id))
    assert event["routing_key"] == "agent.run.cancelled.v2"


def test_reaper_closes_expired_v2_job_in_v2(store: Any, wire_v2_store: Any, db_pool: Any) -> None:
    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id, status="running", deadline_seconds=-30.0, execution_attempt=1, wire_version=2))

    old = run(DeadlineReaper(store).run_once())
    assert old.skipped == 1 and old.expired_failed == 0  # eski oturum v2 işini kapatamaz
    assert run(_events(db_pool, run_id)) == []

    new = run(DeadlineReaper(wire_v2_store).run_once())
    assert new.expired_failed == 1
    (event,) = run(_events(db_pool, run_id))
    assert event["routing_key"] == "agent.run.failed.v2"
    assert event["envelope"]["payload"]["error_code"] == "timeout"


def test_v1_job_still_closed_in_v1_by_new_session(wire_v2_store: Any, db_pool: Any) -> None:
    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id, status="running", deadline_seconds=-30.0, execution_attempt=1))

    assert run(DeadlineReaper(wire_v2_store).run_once()).expired_failed == 1
    (event,) = run(_events(db_pool, run_id))
    assert event["routing_key"] == "agent.run.failed.v1"
    assert event["envelope"]["schema_version"] == 1


def test_rollback_drain_cancels_active_v2_jobs(wire_v2_store: Any, db_pool: Any) -> None:
    v2_runs = [str(uuid.uuid4()) for _ in range(2)]
    v1_run = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=v2_runs[0], status="queued", wire_version=2))
    run(seed_job(db_pool, run_id=v2_runs[1], status="running", execution_attempt=1, wire_version=2))
    run(seed_job(db_pool, run_id=v1_run, status="queued"))

    before = run(check_active(wire_v2_store))
    assert before.remaining == 2

    report = run(cancel_active(wire_v2_store))

    assert sorted(report.cancelled) == sorted(v2_runs) and report.remaining == 0
    for run_id in v2_runs:
        (event,) = run(_events(db_pool, run_id))
        assert event["routing_key"] == "agent.run.cancelled.v2"
        assert event["envelope"]["payload"]["reason"] == WIRE_DRAIN_REASON
    assert run(_status(db_pool, v1_run)) == "queued"  # v1 işi drain'e dahil değil
    assert run(_events(db_pool, v1_run)) == []
