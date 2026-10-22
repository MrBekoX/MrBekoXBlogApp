"""K4 (gerçek PostgreSQL): v2 execute kabulü run wire sürümünü kalıcılaştırır.

``agent.execute.v2.q`` intake'i yalnız v2 kabul eder; iş satırına
``wire_version=2`` yazılır ve accepted olayı aynı transaction'da ``.v2`` routing
key'iyle outbox'a girer. ``payload_hash`` mesaj başınadır: aynı run_id'nin v1 ve
v2 payload'ı çatışmadır (replay edilmez).

Bu paket gerçek broker + gerçek Postgres ister (conftest ``real_environment``;
skip yok — sahte başarı üretilmez).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from messaging import IntakePolicyError, IntakeService, JobPayloadConflict

from .conftest import REPO_ROOT, run

pytestmark = pytest.mark.usefixtures("truncated_db")

V2_FIXTURES = REPO_ROOT / "src" / "contracts" / "agent" / "fixtures" / "v2"
V1_FIXTURES = REPO_ROOT / "src" / "contracts" / "agent" / "fixtures"


class _Delivery:
    """Teslim double'ı: intake yalnız log için message_id/delivery_tag okur."""

    is_test_double = True
    message_id = "test"
    delivery_tag = 1


def _fixture(base: Path, name: str, *, run_id: str) -> bytes:
    document = json.loads((base / name).read_text(encoding="utf-8"))
    document["run_id"] = run_id
    document["message_id"] = str(uuid.uuid4())
    document["deadline_at"] = "2099-01-01T00:00:00Z"
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


async def _job_and_outbox(pool: Any, run_id: str) -> tuple[Any, list[Any]]:
    async with pool.acquire() as conn:
        job = await conn.fetchrow("SELECT wire_version, status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))
        outbox = await conn.fetch(
            "SELECT routing_key, envelope FROM agent.outbox_events WHERE envelope->>'run_id' = $1", run_id
        )
    return job, list(outbox)


def test_v2_execute_is_accepted_with_wire_version(store: Any, truncated_db: Any) -> None:
    run_id = str(uuid.uuid4())
    intake = IntakeService(store, accepted_versions=(2,))

    outcome = run(intake.handle_delivery(_fixture(V2_FIXTURES, "valid/agent.execute.requested.who_am_i.json", run_id=run_id), _Delivery()))

    assert outcome.outcome == "created"
    job, outbox = run(_job_and_outbox(truncated_db, run_id))
    assert job["wire_version"] == 2 and job["status"] == "accepted"
    (row,) = outbox
    assert row["routing_key"] == "agent.run.accepted.v2"
    assert json.loads(row["envelope"])["schema_version"] == 2


def test_v1_execute_keeps_wire_version_one(store: Any, truncated_db: Any) -> None:
    run_id = str(uuid.uuid4())
    intake = IntakeService(store, accepted_versions=(1,))

    run(intake.handle_delivery(_fixture(V1_FIXTURES, "valid/agent.execute.requested.json", run_id=run_id), _Delivery()))

    job, outbox = run(_job_and_outbox(truncated_db, run_id))
    assert job["wire_version"] == 1
    assert outbox[0]["routing_key"] == "agent.run.accepted.v1"


def test_queue_version_mismatch_is_policy_error(store: Any, truncated_db: Any) -> None:
    run_id = str(uuid.uuid4())
    intake = IntakeService(store, accepted_versions=(1,))

    with pytest.raises(IntakePolicyError):
        run(intake.handle_delivery(_fixture(V2_FIXTURES, "valid/agent.execute.requested.who_am_i.json", run_id=run_id), _Delivery()))

    job, _ = run(_job_and_outbox(truncated_db, run_id))
    assert job is None


def test_same_run_id_with_other_version_payload_is_conflict(store: Any, truncated_db: Any) -> None:
    """payload_hash mesaj başınadır: v1 kabul edilmiş run_id'ye v2 payload replay edilmez."""

    run_id = str(uuid.uuid4())
    run(IntakeService(store, accepted_versions=(1,)).handle_delivery(
        _fixture(V1_FIXTURES, "valid/agent.execute.requested.json", run_id=run_id), _Delivery()
    ))

    with pytest.raises(JobPayloadConflict):
        run(IntakeService(store, accepted_versions=(2,)).handle_delivery(
            _fixture(V2_FIXTURES, "valid/agent.execute.requested.auto_with_profile_snapshot.json", run_id=run_id),
            _Delivery(),
        ))

    job, _ = run(_job_and_outbox(truncated_db, run_id))
    assert job["wire_version"] == 1  # mevcut iş sürümünü korur
