"""K4 offline: kabul / deneme tükenmesi / iptal / deadline / drain üreticileri run sürümünü korur.

``JobStore`` ve ``ControlStore`` sahte asyncpg bağlantısıyla sürülür; SQL'in
gerçek davranışı (tetikleyiciler dahil) DB'li paketlerde ayrıca sınanır.
Kanıtlanan: üretilen her olay İŞİN ``wire_version``'ıyla kurulur (komutun ya da
global bir sabitin değil), outbox routing key'i zarfın sürümündendir, sürüm
izolasyonu nedeniyle güncellenemeyen işe olay yazılmaz.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from contract_paths import read_v2_fixture
from messaging.contracts import parse_envelope
from messaging.control import ControlConsumerService, ControlPolicyError
from messaging.control_store import WIRE_DRAIN_REASON, ControlStore, WireIsolationError
from messaging.intake import IntakePolicyError, IntakeService
from messaging.job_store import JobStore, build_accepted_envelope
from messaging.wire import WORKER_WIRE_MAX
from messaging.wire_drain import DrainReport, cancel_active, check_active

from .fakes import (
    CONV_ID,
    CORR_ID,
    ORIGIN_ID,
    RUN_ID,
    FakeConnection,
    FakePool,
    assert_valid_wire,
    execute_envelope,
    sequence_responder,
)

RUN_UUID = uuid.UUID(RUN_ID)


def _store(cls, responder) -> tuple[Any, FakeConnection]:
    conn = FakeConnection(sequence_responder(responder))
    return cls(FakePool(conn), schema="agent"), conn


# --- ControlStore ---


def _pending_cancel(status: str, version: int, *, update_returns: Any = RUN_UUID):
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchval" and "INSERT INTO agent.cancel_intents" in sql:
            return RUN_UUID
        if kind == "fetchrow" and "SELECT status, execution_attempt, wire_version FROM agent.jobs" in sql:
            return {"status": status, "execution_attempt": 0, "wire_version": version}
        if kind == "fetchval" and sql.startswith("UPDATE agent.jobs SET status = 'cancelled'"):
            return update_returns
        return None

    return respond


@pytest.mark.parametrize("version", [1, 2])
def test_cancel_of_pending_job_emits_cancelled_in_job_version(version: int) -> None:
    store, conn = _store(ControlStore, _pending_cancel("accepted", version))

    result = asyncio.run(
        store.record_cancel_intent(
            RUN_ID, "backend-net", conversation_id=CONV_ID, correlation_id=CORR_ID, reason="kullanıcı"
        )
    )

    assert result.outcome == "queued_cancelled"
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == f"agent.run.cancelled.v{version}"
    parsed = assert_valid_wire(row["envelope"])
    assert parsed.schema_version == version
    assert parsed.payload.reason == "kullanıcı"


def test_cancel_finalize_without_row_update_raises_and_writes_no_event() -> None:
    """Sürüm izolasyonu güncellemeyi atladıysa (GUC'suz havuz) terminal olay yazılmaz."""

    store, conn = _store(ControlStore, _pending_cancel("accepted", 2, update_returns=None))

    with pytest.raises(WireIsolationError):
        asyncio.run(
            store.record_cancel_intent(RUN_ID, "backend-net", conversation_id=CONV_ID, correlation_id=CORR_ID)
        )
    assert conn.outbox_rows() == []


def test_mark_cancelled_if_running_uses_job_version() -> None:
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and "status = 'running'" in sql:
            return {"execution_attempt": 2, "wire_version": 2}
        if kind == "fetchval" and sql.startswith("UPDATE agent.jobs SET status = 'cancelled'"):
            return RUN_UUID
        return None

    store, conn = _store(ControlStore, respond)

    assert asyncio.run(store.mark_cancelled_if_running(RUN_ID, conversation_id=CONV_ID, correlation_id=CORR_ID)) == (
        "cancelled"
    )
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.cancelled.v2"
    assert assert_valid_wire(row["envelope"]).payload.execution_attempt == 2


def test_mark_cancelled_untouched_when_isolated_or_not_running() -> None:
    store, conn = _store(ControlStore, lambda *_: None)

    assert asyncio.run(store.mark_cancelled_if_running(RUN_ID, conversation_id=CONV_ID, correlation_id=CORR_ID)) == (
        "untouched"
    )
    assert conn.outbox_rows() == []


@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
def test_deadline_close_uses_job_version(terminal: str) -> None:
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and "RETURNING execution_attempt, wire_version" in sql:
            return {"execution_attempt": 1, "wire_version": 2}
        return None

    store, conn = _store(ControlStore, respond)
    payload: dict[str, Any] = {"event_sequence": 0}
    if terminal == "failed":
        payload.update(error_code="timeout", error_message="deadline doldu")

    closed = asyncio.run(
        store.close_expired_job(
            RUN_ID, conversation_id=CONV_ID, correlation_id=CORR_ID, terminal_status=terminal, payload=payload
        )
    )

    assert closed is True
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == f"agent.run.{terminal}.v2"
    assert_valid_wire(row["envelope"])


def _drain_row(status: str, version: int):
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and "origin_message_id" in sql and "FOR UPDATE" in sql:
            return {
                "status": status,
                "execution_attempt": 1,
                "wire_version": version,
                "conversation_id": uuid.UUID(CONV_ID),
                "origin_message_id": uuid.UUID(ORIGIN_ID),
                "correlation_id": CORR_ID,
            }
        if kind == "fetchval" and sql.startswith("UPDATE agent.jobs SET status = 'cancelled'"):
            return RUN_UUID
        return None

    return respond


def test_drain_finalizes_active_v2_job_with_v2_cancelled() -> None:
    store, conn = _store(ControlStore, _drain_row("running", 2))

    assert asyncio.run(store.finalize_cancelled_for_drain(RUN_ID)) is True

    intents = [c for c in conn.calls if c[0] == "execute" and "INSERT INTO agent.cancel_intents" in c[1]]
    assert intents and intents[0][2][2] == "wire-drain"
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.cancelled.v2"
    parsed = assert_valid_wire(row["envelope"])
    assert parsed.payload.reason == WIRE_DRAIN_REASON
    assert parsed.envelope.causation_id == ORIGIN_ID


@pytest.mark.parametrize(("status", "version"), [("completed", 2), ("running", 1)])
def test_drain_skips_terminal_or_other_version(status: str, version: int) -> None:
    store, conn = _store(ControlStore, _drain_row(status, version))

    assert asyncio.run(store.finalize_cancelled_for_drain(RUN_ID)) is False
    assert conn.outbox_rows() == []


# --- wire_drain CLI çekirdeği ---


class _DrainStore:
    is_test_double = True

    def __init__(self, active: list[str], *, stuck: set[str] | None = None) -> None:
        self.active = list(active)
        self.stuck = stuck or set()
        self.finalized: list[tuple[str, str]] = []

    async def active_jobs_by_wire_version(self) -> dict[int, int]:
        return {1: 3, 2: len(self.active)} if self.active else {1: 3}

    async def active_jobs_for_wire_version(self, version: int, *, limit: int = 100):
        return [{"run_id": run_id} for run_id in self.active[:limit]]

    async def finalize_cancelled_for_drain(self, run_id: str, *, reason: str, expected_wire_version: int) -> bool:
        assert expected_wire_version == 2
        if run_id in self.stuck:
            return False
        self.finalized.append((run_id, reason))
        self.active.remove(run_id)
        return True


def test_drain_check_reports_remaining_v2_jobs() -> None:
    report = asyncio.run(check_active(_DrainStore(["r1", "r2"])))
    assert isinstance(report, DrainReport)
    assert report.remaining == 2
    assert report.to_dict()["active_by_version"] == {"1": 3, "2": 2}

    clean = asyncio.run(check_active(_DrainStore([])))
    assert clean.remaining == 0  # v1 işleri drain'i engellemez


def test_drain_cancel_finalizes_all_and_terminates_on_no_progress() -> None:
    store = _DrainStore(["r1", "r2", "r3"], stuck={"r3"})

    report = asyncio.run(cancel_active(store, batch_size=2))

    assert report.cancelled == ["r1", "r2"]
    assert report.skipped == ["r3"]  # ilerleme olmayan iş sonsuz döngü üretmez
    assert report.remaining == 1
    assert all(reason == WIRE_DRAIN_REASON for _, reason in store.finalized)


# --- JobStore ---


def test_accepted_envelope_keeps_execute_version() -> None:
    parsed = parse_envelope(read_v2_fixture("valid/agent.execute.requested.who_am_i.json"))

    envelope = build_accepted_envelope(
        parsed, accepted_at=datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc), new_message_id=uuid.uuid4
    )

    assert envelope.schema_version == 2
    assert envelope.causation_id == parsed.envelope.message_id
    assert_valid_wire(json.loads(envelope.model_dump_json(exclude_none=True)))


def test_accept_execution_stores_wire_version_and_v2_accepted_event() -> None:
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and "INSERT INTO agent.inbox_messages" in sql:
            return {"consumer_name": "intake"}
        return None

    store, conn = _store(JobStore, respond)
    parsed = parse_envelope(read_v2_fixture("valid/agent.execute.requested.who_am_i.json"))

    outcome = asyncio.run(store.accept_execution(parsed, consumer_name="intake"))

    assert outcome.outcome == "created"
    (job_insert,) = [c for c in conn.calls if c[0] == "execute" and "INSERT INTO agent.jobs" in c[1]]
    assert "wire_version" in job_insert[1]
    assert job_insert[2][-1] == 2  # run wire sürümü = execute zarfının sürümü
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.accepted.v2"
    assert_valid_wire(row["envelope"])


def test_claim_filters_supported_versions_and_returns_wire_version() -> None:
    envelope = execute_envelope("valid/agent.execute.requested.who_am_i.json", version=2)
    now = datetime.now(timezone.utc)

    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and "WITH picked AS" in sql:
            return {
                "job_id": uuid.uuid4(),
                "run_id": uuid.UUID(envelope.run_id),
                "conversation_id": uuid.UUID(envelope.conversation_id),
                "origin_message_id": uuid.UUID(envelope.message_id),
                "payload": json.dumps(envelope.payload),
                "envelope": envelope.model_dump_json(exclude_none=True),
                "queue_class": "fast",
                "deadline_at": now + timedelta(minutes=5),
                "execution_attempt": 1,
                "fencing_token": 11,
                "accepted_at": now,
                "started_at": now,
                "wire_version": 2,
                "was_recoverable": False,
            }
        return None

    store, conn = _store(JobStore, respond)

    claimed = asyncio.run(store.claim_next_job("w1", lease_seconds=30))

    assert claimed is not None and claimed.wire_version == 2
    (_, sql, args) = next(c for c in conn.calls if "WITH picked AS" in c[1])
    assert "c.wire_version <= $6" in sql
    assert args[5] == WORKER_WIRE_MAX


def test_attempt_exhaustion_failure_uses_job_version() -> None:
    envelope = execute_envelope("valid/agent.execute.requested.who_am_i.json", version=2)

    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetch" and "execution_attempt, wire_version FROM agent.jobs" in sql:
            return [
                {
                    "run_id": uuid.UUID(envelope.run_id),
                    "conversation_id": uuid.UUID(envelope.conversation_id),
                    "envelope": envelope.model_dump_json(exclude_none=True),
                    "origin_message_id": uuid.UUID(envelope.message_id),
                    "execution_attempt": 3,
                    "wire_version": 2,
                }
            ]
        if kind == "fetchrow" and sql.startswith("UPDATE agent.jobs SET status = $3"):
            return {"job_id": uuid.uuid4()}
        return None

    store, conn = _store(JobStore, respond)

    closed = asyncio.run(store.fail_expired_jobs_beyond_attempts(3))

    assert closed == [envelope.run_id]
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.failed.v2"
    assert assert_valid_wire(row["envelope"]).payload.error_code.value == "provider_error"


def test_terminal_rejection_diagnoses_wire_isolation() -> None:
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and "FOR UPDATE" in sql:
            return {"job_id": uuid.uuid4()}
        if kind == "fetchrow" and "current_setting" in sql:
            return {"status": "running", "fencing_token": 5, "wire_version": 2, "wire_max": 1}
        return None

    store, conn = _store(JobStore, respond)

    result = asyncio.run(store.complete_job(RUN_ID, {"outcome": "completed"}, 5))

    assert not result.accepted and result.reason == "wire_isolated"
    assert conn.outbox_rows() == []


# --- kuyruk/sürüm politikası ---


class _RecordingAcceptStore:
    is_test_double = True

    def __init__(self) -> None:
        self.accepted: list[Any] = []

    async def accept_execution(self, parsed, *, consumer_name, on_event=None):
        from messaging.job_store import AcceptOutcome

        self.accepted.append(parsed)
        return AcceptOutcome(outcome="created", job_id=uuid.uuid4(), outbox_id=uuid.uuid4())


def test_intake_queue_accepts_only_its_version() -> None:
    raw_v2 = read_v2_fixture("valid/agent.execute.requested.who_am_i.json").encode("utf-8")
    store = _RecordingAcceptStore()

    v1_queue = IntakeService(store, accepted_versions=(1,))  # type: ignore[arg-type]
    with pytest.raises(IntakePolicyError):
        asyncio.run(v1_queue.handle_delivery(raw_v2, object()))  # type: ignore[arg-type]
    assert store.accepted == []

    v2_queue = IntakeService(store, accepted_versions=(2,))  # type: ignore[arg-type]
    outcome = asyncio.run(v2_queue.handle_delivery(raw_v2, object()))  # type: ignore[arg-type]
    assert outcome.accepted and store.accepted[0].schema_version == 2


def test_control_queue_accepts_only_its_version() -> None:
    raw_v2_cancel = read_v2_fixture("valid/agent.cancel.requested.json").encode("utf-8")
    service = ControlConsumerService(object(), accepted_versions=(1,))  # type: ignore[arg-type]

    with pytest.raises(ControlPolicyError):
        asyncio.run(service.handle_delivery(raw_v2_cancel, object()))  # type: ignore[arg-type]
