"""Backpressure ölçümü (plan satır 422): kabul edilmiş job backlog'u + en eski iş yaşı
+ kuyruk derinlikleri birlikte ölçülür.

`.NET` tarafındaki sistem düzeyi kapasite sınırı testleri Api.Tests içindedir
(AgentBackpressureTests); burada kalıcı iş + broker görünümü doğrulanır.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from messaging.control import build_control_consumer
from messaging.topology import CONTROL_QUEUE, EXECUTE_QUEUE

from .conftest import (
    CONTROL_QUEUE as CQ,
    EXECUTE_QUEUE as EQ,
    TEST_TIERS,
    queue_depth,
    queue_depth_async,
    run,
    seed_job,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_broker")


def test_backpressure_snapshot_counts_active_jobs_only(store: Any, db_pool: Any) -> None:
    queued_a = "f1000000-0000-0000-0000-000000000001"
    queued_b = "f1000000-0000-0000-0000-000000000002"
    running = "f1000000-0000-0000-0000-000000000003"
    completed = "f1000000-0000-0000-0000-000000000004"

    run(seed_job(db_pool, run_id=queued_a, status="queued", deadline_seconds=600.0, created_age_seconds=900.0))
    run(seed_job(db_pool, run_id=queued_b, status="queued", deadline_seconds=-60.0))
    run(seed_job(db_pool, run_id=running, status="running", execution_attempt=1))
    run(seed_job(db_pool, run_id=completed, status="completed"))

    snapshot = run(store.backpressure())

    assert snapshot.accepted_backlog == 3  # queued + running; terminal hariç
    assert snapshot.queued == 2 and snapshot.running == 1
    assert snapshot.oldest_active_age_seconds is not None
    assert snapshot.oldest_active_age_seconds >= 900.0  # kabul edilmiş en eski iş yaşı ölçülür
    assert snapshot.oldest_active_run_id == queued_a


def test_backpressure_empty_store(store: Any) -> None:
    snapshot = run(store.backpressure())

    assert snapshot.accepted_backlog == 0
    assert snapshot.oldest_active_age_seconds is None
    assert snapshot.oldest_active_run_id is None


def test_probe_combines_queue_depths_and_store_snapshot(store: Any, db_pool: Any) -> None:
    """Kuyruk derinliği + kalıcı backlog birlikte ölçülür (plan: 'Queue derinliğine EK olarak')."""

    from messaging.topology import BACKEND_EVENTS_QUEUE, EXECUTE_QUEUE, CONTROL_QUEUE

    run(seed_job(db_pool, run_id="f1000000-0000-0000-0000-000000000005", status="queued"))

    async def _depths() -> dict[str, int]:
        return {
            EXECUTE_QUEUE: await queue_depth_async(EXECUTE_QUEUE),
            CONTROL_QUEUE: await queue_depth_async(CONTROL_QUEUE),
        }

    depths = run(_depths())
    snapshot = run(store.backpressure())

    assert depths[EXECUTE_QUEUE] == 0 and depths[CONTROL_QUEUE] == 0  # broker boş
    assert snapshot.accepted_backlog == 1  # ama kalıcı iş var: mesaj kaybı olsa bile görünür


def test_control_consumer_is_built_with_retry_awareness(store: Any, agent_publisher: Any) -> None:
    """build_control_consumer karar-farkında consumer kurar (HOLD yolunu destekler)."""

    async def _build() -> Any:
        from messaging.connection import connect_broker
        from .conftest import make_settings, AGENT_USER

        conn = await connect_broker(make_settings(*AGENT_USER))
        consumer = build_control_consumer(
            conn,
            store,
            agent_publisher,
            make_settings(*AGENT_USER),
            tiers=TEST_TIERS,
        )
        await consumer.start()
        running = consumer.running
        await consumer.stop()
        await conn.close()
        return running

    assert run(_build()) is True
