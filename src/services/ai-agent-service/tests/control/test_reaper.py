"""Deadline reaper (plan satır 434): süresi geçen işleri kapatır, işi belirsiz bırakmaz.

- deadline dolan running iş: cancel intent yok → failed + agent.run.failed(timeout).
- deadline dolan iş + cancel intent → cancelled kazanır (kullanıcı isteği).
- canlı işe dokunulmaz; bu arada terminalleşen iş skipped sayılır (terminal kazanır).
- cancel intent'li queued iş (execute hiç gelmedi) başlatılmadan kapatılır.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from messaging.reaper import DeadlineReaper

from .conftest import (
    insert_cancel_intent,
    run,
    seed_job,
    status_is,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_broker")


async def _job_status(pool: Any, run_id: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))


async def _terminal_events(pool: Any, run_id: str, message_type: str) -> list[Any]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT envelope FROM agent.outbox_events "
            "WHERE envelope->>'run_id' = $1 AND message_type = $2",
            run_id,
            message_type,
        )


def test_expired_running_job_fails_with_timeout(store: Any, db_pool: Any) -> None:
    run_id = "e1000000-0000-0000-0000-000000000001"
    run(seed_job(db_pool, run_id=run_id, status="running", deadline_seconds=-30.0, execution_attempt=1))

    result = run(DeadlineReaper(store).run_once())

    assert result.expired_failed == 1 and result.skipped == 0
    run(wait_until(status_is(db_pool, run_id, "failed"), timeout_seconds=5))
    failed_events = run(_terminal_events(db_pool, run_id, "agent.run.failed"))
    assert len(failed_events) == 1
    import json

    payload = json.loads(failed_events[0]["envelope"])["payload"]
    assert payload["error_code"] == "timeout"  # AgentErrorCode.TIMEOUT


def test_expired_job_with_cancel_intent_is_cancelled(store: Any, db_pool: Any) -> None:
    run_id = "e1000000-0000-0000-0000-000000000002"
    run(seed_job(db_pool, run_id=run_id, status="running", deadline_seconds=-30.0, execution_attempt=1))
    run(insert_cancel_intent(db_pool, run_id))

    result = run(DeadlineReaper(store).run_once())

    assert result.expired_cancelled == 1
    run(wait_until(status_is(db_pool, run_id, "cancelled"), timeout_seconds=5))
    assert len(run(_terminal_events(db_pool, run_id, "agent.run.cancelled"))) == 1


def test_live_job_is_untouched(store: Any, db_pool: Any) -> None:
    run_id = "e1000000-0000-0000-0000-000000000003"
    run(seed_job(db_pool, run_id=run_id, status="running", deadline_seconds=600.0, execution_attempt=1))

    result = run(DeadlineReaper(store).run_once())

    assert (result.expired_failed, result.expired_cancelled, result.queued_cancelled, result.skipped) == (0, 0, 0, 0)
    assert run(_job_status(db_pool, run_id)) == "running"


def test_cancelled_queued_job_is_finalized_without_execute(store: Any, db_pool: Any) -> None:
    """Cancel intent'i olan queued iş: execute hiç gelmeden kapatılır (engel finalizer'ı)."""

    run_id = "e1000000-0000-0000-0000-000000000004"
    run(seed_job(db_pool, run_id=run_id, status="queued", deadline_seconds=600.0))
    run(insert_cancel_intent(db_pool, run_id))

    result = run(DeadlineReaper(store).run_once())

    assert result.queued_cancelled == 1
    run(wait_until(status_is(db_pool, run_id, "cancelled"), timeout_seconds=5))
    assert len(run(_terminal_events(db_pool, run_id, "agent.run.cancelled"))) == 1


def test_worker_terminal_wins_over_reaper(store: Any, db_pool: Any) -> None:
    """Reaper adayını bu arada worker terminalleştirdiyse dokunmaz (skipped)."""

    run_id = "e1000000-0000-0000-0000-000000000005"
    run(seed_job(db_pool, run_id=run_id, status="running", deadline_seconds=-30.0, execution_attempt=1))

    # Reaper aday listesini okuduktan SONRA iş terminalleşsin: çevrimi bölünmüş
    # simüle etmek için terminali önceden yazıp aday sorgusunun boş döndüğünü kanıtlıyoruz.
    from .conftest import db_conn_kwargs
    import asyncpg

    async def _complete() -> None:
        conn = await asyncpg.connect(**db_conn_kwargs("blogdb_agent_b7"))
        try:
            await conn.execute(
                "UPDATE agent.jobs SET status='completed', result_json='{}'::jsonb WHERE run_id=$1",
                uuid.UUID(run_id),
            )
        finally:
            await conn.close()

    run(_complete())
    result = run(DeadlineReaper(store).run_once())

    assert result.expired_failed == 0 and result.skipped == 0  # aday sorgusu terminal işi görmez
    assert run(_job_status(db_pool, run_id)) == "completed"  # geç terminal geri götürmez
    assert len(run(_terminal_events(db_pool, run_id, "agent.run.failed"))) == 0
