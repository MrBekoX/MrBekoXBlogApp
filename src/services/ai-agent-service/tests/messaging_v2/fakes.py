"""Who am I (K4) offline test yardımcıları: asyncpg havuz/bağlantı ve iş deposu double'ları.

Bu paket broker/DB GEREKTİRMEZ: SQL davranışı test başına ``responder`` ile
programlanır; amaç sürüm seçimi, zarf kurma ve yönlendirme kararlarını
kanıtlamaktır (gerçek SQL/tetikleyici davranışı DB'li paketlerde sınanır).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from contract_paths import read_fixture, read_v2_fixture
from messaging.contracts import AgentEnvelope, parse_envelope
from messaging.job_store import ClaimedJob, TerminalWriteResult

Responder = Callable[[str, str, tuple[Any, ...]], Any]

RUN_ID = "aaaaaaa1-0000-4000-8000-000000000001"
CONV_ID = "bbbbbbb1-0000-4000-8000-000000000002"
CORR_ID = "ccccccc1-0000-4000-8000-000000000003"
ORIGIN_ID = "ddddddd1-0000-4000-8000-000000000004"
PROFILE_HASH = "4f3b02e187c2b8c04134aa2c80df4b2d8c817377780aca74d2a11e9bf0c1406d"


class FakeTransaction:
    is_test_double = True

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeConnection:
    """Çağrıları kaydeden asyncpg bağlantı double'ı; sonuçlar ``responder``'dan."""

    is_test_double = True

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchval", sql, args))
        return self._responder("fetchval", sql, args)

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchrow", sql, args))
        return self._responder("fetchrow", sql, args)

    async def fetch(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetch", sql, args))
        return self._responder("fetch", sql, args) or []

    async def execute(self, sql: str, *args: Any) -> Any:
        self.calls.append(("execute", sql, args))
        return self._responder("execute", sql, args)

    # --- gözlem ---

    def outbox_rows(self) -> list[dict[str, Any]]:
        """Outbox INSERT'lerinin (exchange, routing_key, zarf) özeti."""

        rows = []
        for kind, sql, args in self.calls:
            if kind == "execute" and "INSERT INTO agent.outbox_events" in sql:
                rows.append(
                    {
                        "message_type": args[2],
                        "exchange": args[3],
                        "routing_key": args[4],
                        "envelope": json.loads(args[5]),
                    }
                )
        return rows


class _Acquire:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakePool:
    is_test_double = True

    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def sequence_responder(base: Responder | None = None) -> Responder:
    """``run_event_sequences`` tahsisini 1,2,3... üreten sarmalayıcı."""

    counter = {"value": 0}

    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if "run_event_sequences" in sql:
            counter["value"] += 1
            return {"last_sequence": counter["value"]}
        return base(kind, sql, args) if base is not None else None

    return respond


def assert_valid_wire(envelope_json: dict[str, Any]) -> Any:
    """Outbox gövdesi tüketici doğrulayıcısından geçer (sözleşme kanıtı)."""

    return parse_envelope(json.dumps(envelope_json, ensure_ascii=False))


# --- iş deposu / yayıncı double'ları (worker testleri) ---


class RecordingJobStore:
    """``JobStore`` worker yüzeyinin double'ı: terminal yazımlarını kaydeder."""

    is_test_double = True

    def __init__(self) -> None:
        self.completed: list[tuple[dict[str, Any], AgentEnvelope | None]] = []
        self.failed: list[tuple[dict[str, Any], AgentEnvelope | None]] = []
        self.requeued: list[dict[str, Any]] = []
        self.released: list[str] = []

    async def renew_lease(self, run_id: str, fencing_token: int, lease_seconds: float) -> bool:
        return True

    async def release_job_lease(self, run_id: str, fencing_token: int) -> bool:
        self.released.append(run_id)
        return True

    async def has_cancel_intent(self, run_id: str) -> bool:
        return False

    async def complete_job(self, run_id, result_json, fencing_token, *, outbox_event=None):
        self.completed.append((result_json, outbox_event))
        return TerminalWriteResult(outcome="completed")

    async def fail_job(self, run_id, result_json, fencing_token, *, outbox_event=None):
        self.failed.append((result_json, outbox_event))
        return TerminalWriteResult(outcome="failed")

    async def requeue_job(self, run_id, fencing_token, *, queue_class=None, reset_attempt=False):
        self.requeued.append({"queue_class": queue_class, "reset_attempt": reset_attempt})
        return True


class RecordingEventPublisher:
    """``AgentEventPublisher`` yüzeyinin kayıtçı double'ı (DB'siz)."""

    is_test_double = True

    def __init__(self) -> None:
        self.progressed: list[dict[str, Any]] = []
        self.deltas: list[dict[str, Any]] = []
        self.proposed: list[dict[str, Any]] = []
        self.mode_selected: list[dict[str, Any]] = []

    async def publish_progress(self, **kwargs: Any) -> Any:
        self.progressed.append(kwargs)
        return object()

    async def publish_generation_delta(self, **kwargs: Any) -> list[Any]:
        self.deltas.append(kwargs)
        return [object()]

    async def publish_action_proposed(self, **kwargs: Any) -> Any:
        self.proposed.append(kwargs)
        return object()

    async def publish_mode_selected(self, **kwargs: Any) -> Any:
        self.mode_selected.append(kwargs)
        return object()


class FakeWatch:
    is_test_double = True

    def __init__(self) -> None:
        self.lost = False
        self.heartbeats = 0

    async def heartbeat(self) -> None:
        self.heartbeats += 1


def execute_envelope(fixture: str, *, version: int) -> AgentEnvelope:
    """Ortak fixture'dan execute zarfı (v1: fixtures/, v2: fixtures/v2/)."""

    raw = read_v2_fixture(fixture) if version == 2 else read_fixture(fixture)
    return parse_envelope(raw).envelope


def claimed_job(envelope: AgentEnvelope, *, wire_version: int, payload: dict[str, Any] | None = None) -> ClaimedJob:
    now = datetime.now(timezone.utc)
    return ClaimedJob(
        job_id=uuid.uuid4(),
        run_id=envelope.run_id or RUN_ID,
        conversation_id=envelope.conversation_id or CONV_ID,
        origin_message_id=envelope.message_id,
        payload=dict(payload if payload is not None else envelope.payload),
        envelope=envelope,
        queue_class="fast",
        deadline_at=now + timedelta(minutes=10),
        execution_attempt=1,
        fencing_token=7,
        accepted_at=now,
        started_at=now,
        recovered=False,
        wire_version=wire_version,
    )


def checkpoint_dir(tmp_path: Path) -> str:
    return str(tmp_path / "checkpoints")
