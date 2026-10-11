"""State checkpoint döngüsü ve checkpoint dışı artifact deposu.

Kabul ölçütü: "State checkpoint'e yazılıp geri yüklenebiliyor". Büyük kaynak
metinleri checkpoint payload'ına girmez; yalnız ``ArtifactRef`` referansı
taşınır (plan A2).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_core.adapters.test_doubles import FakeCheckpointStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import (
    AgentMode,
    BudgetProfile,
    ExecutionContext,
    EvidenceItem,
    ResearchFinding,
    RouteDecision,
    SourceReference,
)
from agent_core.state import (
    STATE_SCHEMA_VERSION,
    AgentState,
    InMemoryArtifactStore,
    deserialize_state,
    serialize_state,
)
from agent_core.state.artifacts import make_artifact_ref

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
BIG_PAGE = "sayfa gövdesi " + "x" * 8000


def _state() -> AgentState:
    context = ExecutionContext(
        run_id="run-a2",
        conversation_id="conv-a2",
        question="araştırma sorusu",
        language="tr",
        mode_preference="deep_research",
        budget_profile=BudgetProfile(
            name="test", max_model_calls=4, max_total_tokens=10_000, max_duration_seconds=30.0
        ),
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": "run-a2",
        "context": context,
        "route": RouteDecision(
            run_id="run-a2", selected_mode=AgentMode.DEEP_RESEARCH, reason="test",
            requires_web_search=True, decided_at=NOW,
        ),
        "article_revision": 7,
        "research_round": 2,
        "messages": [],
        "evidence": [
            EvidenceItem(
                evidence_id="ev-1",
                source=SourceReference(kind="web", url="https://example.com/a", accessed_at=NOW),
                excerpt="kanıt",
                collected_at=NOW,
            )
        ],
        "findings": [
            ResearchFinding(
                finding_id="find-1", run_id="run-a2", sub_question="S1",
                summary="özet", confidence="medium", evidence_ids=["ev-1"], created_at=NOW,
            )
        ],
        "usage_events": [],
        "errors": [],
        "artifact_refs": [make_artifact_ref("source_page", BIG_PAGE, created_at=NOW)],
        "pending_subtasks": [],
    }


def test_state_roundtrip_through_checkpoint_store() -> None:
    """serialize → CheckpointStore → load → deserialize: model türleri geri gelir."""
    store = FakeCheckpointStore()
    state = _state()

    payload = serialize_state(state)

    import asyncio

    asyncio.run(store.save("run-a2", "a2-state", payload))
    checkpoint_id, loaded = asyncio.run(store.load_latest("run-a2"))

    restored = deserialize_state(loaded, expected_run_id="run-a2")

    assert checkpoint_id == "a2-state"
    assert restored["run_id"] == "run-a2"
    assert restored["article_revision"] == 7
    assert restored["route"].selected_mode is AgentMode.DEEP_RESEARCH
    assert restored["context"].question == "araştırma sorusu"
    assert restored["findings"][0].finding_id == "find-1"
    assert restored["evidence"][0].source.source_id == restored["evidence"][0].source.source_id
    assert restored["artifact_refs"][0].sha256 == state["artifact_refs"][0].sha256
    # Serileştirilmiş state yeniden serileştirilebilir: kararlı biçim.
    assert deserialize_state(serialize_state(restored))["findings"][0].finding_id == "find-1"


def test_large_source_text_stays_out_of_checkpoint() -> None:
    """Büyük kaynak metni payload'da yer almaz; referans hâlâ depoda çözülür."""
    store = FakeCheckpointStore()
    artifacts = InMemoryArtifactStore()
    ref = artifacts.put("run-a2", "source_page", BIG_PAGE, created_at=NOW)
    state = _state()
    state["artifact_refs"] = [ref]

    payload = serialize_state(state)

    assert b"xxxxx" not in payload
    assert BIG_PAGE not in payload.decode("utf-8", errors="ignore")
    # Referans, depoya geri döndüğünde metni çözümler.
    assert artifacts.get("run-a2", ref.artifact_id) == BIG_PAGE


def test_deserialize_rejects_unknown_schema_version() -> None:
    """Eski/bilinmeyen şema sürümü anlaşılır ``validation_error`` ile reddedilir (A8 genişletir)."""
    payload = serialize_state(_state())
    tampered = payload.replace(b'"schema_version": 1', b'"schema_version": 999')

    with pytest.raises(PortError) as excinfo:
        deserialize_state(tampered)
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "şema sürümü" in excinfo.value.message


def test_deserialize_rejects_foreign_run() -> None:
    """Başka run'ın checkpoint'i beklenen run ile geri yüklenmez."""
    payload = serialize_state(_state())

    with pytest.raises(PortError) as excinfo:
        deserialize_state(payload, expected_run_id="baska-run")
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
