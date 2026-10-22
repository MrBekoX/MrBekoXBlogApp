"""K4 (gerçek PostgreSQL): yayıncı olayları iş satırının ``wire_version``'ıyla kurar.

- Ara olaylar (progress/mode_selected) sürümü transaction içinde iş satırından okur.
- Terminal olay yalnız sürümü yürütebilen oturumda (``agent.worker_wire_max=2``)
  yazılır; eski oturumda tetikleyici güncellemeyi atlar ve yayın "sürüm
  izolasyonu" ile reddedilir (olay yok, durum değişmez).
- v2 profil sonucu run_intent + pinlenmiş snapshot + profile citation taşır.

Bu paket gerçek broker + gerçek Postgres ister (conftest ``real_environment``;
skip yok — sahte başarı üretilmez).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest

from messaging import AgentEventPublisher, AgentOutcome, EventPublishError
from messaging.contracts import parse_envelope
from messaging.contracts.payloads import AgentUsageRecord
from messaging.contracts.payloads_v2 import AgentProfileSnapshotRef, AgentSourceReferenceV2

from .conftest import AGENT_TEST_DB, db_conn_kwargs, ensure_loop, make_run_ids, run, seed_accepted_job

PROFILE_HASH = "4f3b02e187c2b8c04134aa2c80df4b2d8c817377780aca74d2a11e9bf0c1406d"
SNAPSHOT = AgentProfileSnapshotRef(profile_id="sample-author", revision=1, content_hash=PROFILE_HASH)


@pytest.fixture()
def wire_v2_publisher(db_pool: Any) -> Any:
    """Yeni worker oturumunun yayıncısı (``db_pool`` tabloları sıfırlar)."""

    ensure_loop()
    pool = run(
        asyncpg.create_pool(
            **db_conn_kwargs(AGENT_TEST_DB),
            min_size=1,
            max_size=2,
            server_settings={"agent.worker_wire_max": "2"},
        )
    )
    yield AgentEventPublisher(pool, schema="agent", min_progress_interval_seconds=0.0)

    async def _close() -> None:
        await pool.close()

    run(_close())


async def _rows(pool: Any, run_id: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT routing_key, envelope FROM agent.outbox_events WHERE envelope->>'run_id' = $1 "
            "ORDER BY created_at, outbox_id",
            run_id,
        )
    return [{"routing_key": r["routing_key"], "envelope": json.loads(r["envelope"])} for r in rows]


def _profile_outcome(run_id: str) -> AgentOutcome:
    return AgentOutcome(
        kind="completed",
        selected_mode="fast",
        answer="Sample Author Bilgisayar Mühendisliği okudu.",
        citations=(
            AgentSourceReferenceV2(
                kind="profile",
                source_id=f"profile:sample-author:1:{PROFILE_HASH}:education:0",
                title="Eğitim",
                profile_id="sample-author",
                profile_revision=1,
                profile_content_hash=PROFILE_HASH,
                section_id="education",
                chunk_index=0,
                url="/about#education",
            ),
        ),
        source_scope="profile",
        usage=AgentUsageRecord(run_id=run_id, recorded_at="2026-10-22T10:00:00Z"),
        run_intent="profile",
        profile_snapshot=SNAPSHOT,
    )


def test_progress_and_mode_selected_follow_job_version(db_pool: Any, publisher: Any) -> None:
    v2_run, conv, corr = make_run_ids()
    v1_run, conv1, corr1 = make_run_ids()
    run(seed_accepted_job(db_pool, v2_run, conv, corr, wire_version=2))
    run(seed_accepted_job(db_pool, v1_run, conv1, corr1))

    run(publisher.publish_progress(run_id=v2_run, conversation_id=conv, correlation_id=corr,
                                   kind="retrieval_started", message="aranıyor"))
    run(publisher.publish_mode_selected(run_id=v2_run, conversation_id=conv, correlation_id=corr,
                                        selected_mode="fast", requires_web_search=False, reason="profil",
                                        run_intent="profile", source_scope="profile", profile_snapshot=SNAPSHOT))
    run(publisher.publish_progress(run_id=v1_run, conversation_id=conv1, correlation_id=corr1,
                                   kind="retrieval_started", message="aranıyor"))

    v2_rows = run(_rows(db_pool, v2_run))
    assert [r["routing_key"] for r in v2_rows] == ["agent.run.progressed.v2", "agent.run.mode_selected.v2"]
    assert all(parse_envelope(json.dumps(r["envelope"])).schema_version == 2 for r in v2_rows)
    (v1_row,) = run(_rows(db_pool, v1_run))
    assert v1_row["routing_key"] == "agent.run.progressed.v1"


def test_v2_profile_terminal_is_written_by_new_session(db_pool: Any, wire_v2_publisher: Any) -> None:
    run_id, conv, corr = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conv, corr, wire_version=2))

    envelope = run(wire_v2_publisher.publish_outcome(run_id=run_id, conversation_id=conv, correlation_id=corr,
                                                     outcome=_profile_outcome(run_id)))

    assert envelope.schema_version == 2
    (row,) = run(_rows(db_pool, run_id))
    assert row["routing_key"] == "agent.run.completed.v2"
    parsed = parse_envelope(json.dumps(row["envelope"]))
    assert parsed.payload.run_intent.value == "profile"
    assert parsed.payload.profile_snapshot.same_as(SNAPSHOT)

    async def _status() -> str:
        return await db_pool.fetchval("SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))

    assert run(_status()) == "completed"


def test_old_session_cannot_publish_v2_terminal(db_pool: Any, publisher: Any) -> None:
    run_id, conv, corr = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conv, corr, wire_version=2))

    with pytest.raises(EventPublishError) as excinfo:
        run(publisher.publish_outcome(run_id=run_id, conversation_id=conv, correlation_id=corr,
                                      outcome=AgentOutcome(kind="cancelled", cancel_reason="eski oturum")))

    assert "sürüm izolasyonu" in str(excinfo.value)
    assert run(_rows(db_pool, run_id)) == []

    async def _status() -> str:
        return await db_pool.fetchval("SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))

    assert run(_status()) == "accepted"
