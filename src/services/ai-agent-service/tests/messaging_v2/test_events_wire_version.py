"""K4 offline: ``AgentEventPublisher`` her olayı run'ın wire sürümüyle kurar.

Sürüm, olayın yazıldığı transaction içinde iş satırından okunur (fake bağlantı
programlanır). Kanıtlanan: routing key/şema sürümü, v2 alanlarının yalnız v2'de
taşınması, v1 run'ında profile kaynağının reddi, ``partially_completed``
dalının artık erişilebilir olması (events.py:515 düzeltmesi), sürüm izolasyonu
reddi.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from agent_core.models import ProfileSnapshotRef, SourceReference
from messaging.contracts.payloads import AgentUsageRecord
from messaging.events import AgentEventPublisher, AgentOutcome, AlreadyTerminal, EventPublishError

from .fakes import (
    CONV_ID,
    CORR_ID,
    PROFILE_HASH,
    RUN_ID,
    FakeConnection,
    FakePool,
    assert_valid_wire,
    sequence_responder,
)

SNAPSHOT = ProfileSnapshotRef(profile_id="sample-author", revision=1, content_hash=PROFILE_HASH)


def _publisher(responder) -> tuple[AgentEventPublisher, FakeConnection]:
    conn = FakeConnection(sequence_responder(responder))
    return AgentEventPublisher(FakePool(conn), schema="agent", min_progress_interval_seconds=0.0), conn


def _job_version(version: int | None):
    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchval" and "SELECT wire_version FROM agent.jobs" in sql:
            return version
        return None

    return respond


def _terminal(version: int | None, *, status: str = "accepted", wire_max: int = 2):
    """publish_outcome yanıtları: UPDATE ... RETURNING wire_version (veya red teşhisi)."""

    def respond(kind: str, sql: str, args: tuple[Any, ...]) -> Any:
        if kind == "fetchrow" and sql.startswith("UPDATE agent.jobs SET status"):
            if version is None or status != "accepted" or version > wire_max:
                return None
            return {"job_id": uuid.uuid4(), "wire_version": version}
        if kind == "fetchrow" and "current_setting" in sql:
            if version is None:
                return None
            return {"status": status, "wire_version": version, "wire_max": wire_max}
        return None

    return respond


def _usage() -> AgentUsageRecord:
    return AgentUsageRecord(run_id=RUN_ID, recorded_at="2026-10-22T10:00:00Z")


def _profile_citation() -> SourceReference:
    return SourceReference(
        kind="profile",
        title="Eğitim",
        profile_id=SNAPSHOT.profile_id,
        profile_revision=SNAPSHOT.revision,
        profile_content_hash=SNAPSHOT.content_hash,
        section_id="education",
        chunk_index=0,
    )


def _ids() -> dict[str, str]:
    return {"run_id": RUN_ID, "conversation_id": CONV_ID, "correlation_id": CORR_ID}


@pytest.mark.parametrize(("job_version", "expected"), [(2, 2), (1, 1), (None, 1)])
def test_progress_uses_run_wire_version(job_version: int | None, expected: int) -> None:
    publisher, conn = _publisher(_job_version(job_version))

    envelope = asyncio.run(
        publisher.publish_progress(**_ids(), kind="retrieval_started", message="aranıyor", detail={"hits": "3"})
    )

    assert envelope.schema_version == expected
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == f"agent.run.progressed.v{expected}"
    assert row["envelope"]["payload"]["event_sequence"] == 1
    assert assert_valid_wire(row["envelope"]).schema_version == expected


def test_generation_delta_chunks_use_run_wire_version() -> None:
    publisher, conn = _publisher(_job_version(2))

    envelopes = asyncio.run(publisher.publish_generation_delta(**_ids(), text="x" * 1600))

    assert [e.schema_version for e in envelopes] == [2, 2]
    assert {row["routing_key"] for row in conn.outbox_rows()} == {"agent.run.progressed.v2"}


def test_mode_selected_v2_carries_intent_scope_snapshot() -> None:
    publisher, conn = _publisher(_job_version(2))

    asyncio.run(
        publisher.publish_mode_selected(
            **_ids(),
            selected_mode="fast",
            requires_web_search=False,
            reason="profil",
            run_intent="profile",
            source_scope="profile",
            profile_snapshot=SNAPSHOT,
        )
    )

    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.mode_selected.v2"
    payload = row["envelope"]["payload"]
    assert payload["run_intent"] == "profile" and payload["source_scope"] == "profile"
    assert payload["profile_snapshot"]["content_hash"] == PROFILE_HASH
    assert payload["requires_web_search"] is False
    assert_valid_wire(row["envelope"])


def test_mode_selected_v1_run_drops_v2_fields() -> None:
    publisher, conn = _publisher(_job_version(1))

    asyncio.run(
        publisher.publish_mode_selected(
            **_ids(),
            selected_mode="fast",
            requires_web_search=False,
            reason="kısa soru",
            run_intent="article_qa",
            source_scope="article",
        )
    )

    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.mode_selected.v1"
    assert "run_intent" not in row["envelope"]["payload"]
    assert_valid_wire(row["envelope"])


def test_mode_selected_profile_with_web_is_rejected_without_writing() -> None:
    publisher, conn = _publisher(_job_version(2))

    with pytest.raises(ValueError):
        asyncio.run(
            publisher.publish_mode_selected(
                **_ids(),
                selected_mode="deep_research",
                requires_web_search=True,
                reason="aykırı",
                run_intent="profile",
                source_scope="profile",
                profile_snapshot=SNAPSHOT,
            )
        )
    assert conn.outbox_rows() == []


def test_partially_completed_branch_is_reachable_and_valid_v1() -> None:
    """events.py:515 düzeltmesi: partially_completed terminali gerçekten üretilir."""

    publisher, conn = _publisher(_terminal(1))

    envelope = asyncio.run(
        publisher.publish_outcome(
            **_ids(),
            outcome=AgentOutcome(
                kind="partially_completed",
                selected_mode="analysis",
                answer="kısmi cevap",
                source_scope="general",
                usage=_usage(),
            ),
        )
    )

    assert envelope.message_type == "agent.run.partially_completed"
    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.partially_completed.v1"
    assert_valid_wire(row["envelope"])


def test_v2_profile_completed_is_published_with_intent_and_snapshot() -> None:
    publisher, conn = _publisher(_terminal(2))

    asyncio.run(
        publisher.publish_outcome(
            **_ids(),
            outcome=AgentOutcome(
                kind="completed",
                selected_mode="fast",
                answer="Sample Author Bilgisayar Mühendisliği okudu.",
                citations=(_profile_citation(),),
                source_scope="profile",
                usage=_usage(),
                run_intent="profile",
                profile_snapshot=SNAPSHOT,
            ),
        )
    )

    (row,) = conn.outbox_rows()
    assert row["routing_key"] == "agent.run.completed.v2"
    parsed = assert_valid_wire(row["envelope"])
    assert parsed.payload.run_intent.value == "profile"
    assert parsed.payload.citations[0].source_id.startswith("profile:sample-author:1:")


def test_v2_completed_without_run_intent_is_rejected() -> None:
    publisher, conn = _publisher(_terminal(2))

    with pytest.raises((EventPublishError, ValueError)):
        asyncio.run(
            publisher.publish_outcome(
                **_ids(),
                outcome=AgentOutcome(
                    kind="completed", selected_mode="fast", answer="x", source_scope="general", usage=_usage()
                ),
            )
        )
    assert conn.outbox_rows() == []


def test_v1_run_cannot_publish_profile_citation() -> None:
    publisher, conn = _publisher(_terminal(1))

    with pytest.raises(EventPublishError):
        asyncio.run(
            publisher.publish_outcome(
                **_ids(),
                outcome=AgentOutcome(
                    kind="completed",
                    selected_mode="fast",
                    answer="x",
                    citations=(_profile_citation(),),
                    source_scope="profile",
                    usage=_usage(),
                ),
            )
        )
    assert conn.outbox_rows() == []


@pytest.mark.parametrize(
    ("scope", "kinds"),
    [("profile", ("web",)), ("article", ("profile",)), ("general", ("profile",))],
)
def test_scope_rules_reject_mixed_profile_provenance(scope: str, kinds: tuple[str, ...]) -> None:
    from datetime import datetime, timezone

    citations = []
    for kind in kinds:
        if kind == "profile":
            citations.append(_profile_citation())
        else:
            citations.append(
                SourceReference(kind="web", url="https://example.com", accessed_at=datetime.now(timezone.utc))
            )
    with pytest.raises(EventPublishError):
        AgentEventPublisher._check_source_scope(
            AgentOutcome(kind="completed", citations=tuple(citations), source_scope=scope)
        )


def test_run_intent_profile_requires_profile_scope() -> None:
    with pytest.raises(EventPublishError):
        AgentEventPublisher._check_source_scope(
            AgentOutcome(kind="completed", source_scope="general", run_intent="profile")
        )


def test_terminal_rejections_are_classified() -> None:
    outcome = AgentOutcome(kind="cancelled", cancel_reason="test")

    no_job, _ = _publisher(_terminal(None))
    with pytest.raises(EventPublishError) as excinfo:
        asyncio.run(no_job.publish_outcome(**_ids(), outcome=outcome))
    assert not isinstance(excinfo.value, AlreadyTerminal)

    terminal, _ = _publisher(_terminal(1, status="completed"))
    with pytest.raises(AlreadyTerminal):
        asyncio.run(terminal.publish_outcome(**_ids(), outcome=outcome))

    isolated, conn = _publisher(_terminal(2, wire_max=1))
    with pytest.raises(EventPublishError) as excinfo:
        asyncio.run(isolated.publish_outcome(**_ids(), outcome=outcome))
    assert "sürüm izolasyonu" in str(excinfo.value)
    assert not isinstance(excinfo.value, AlreadyTerminal)
    assert conn.outbox_rows() == []
