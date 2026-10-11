"""Ortak state reducer'ları ve kullanım görünümü (plan A2 kabul ölçütleri).

Kapsam: paralel kaynak sonuçlarının benzersiz kimlikle birleşmesi, mesaj
kopyasının düşmesi, kullanım kayıtlarının tekrar yürütmede kopya üretmemesi.
Not: testler conftest modülünden import yapmaz (``conftest`` adı kök
tests/conftest.py ile sys.modules'ta çakışabilir); sabitler yereldir.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_core.models import ConversationTurn, EvidenceItem, SourceReference
from agent_core.state import (
    merge_artifact_refs,
    merge_evidence,
    merge_messages,
    merge_usage_events,
    usage_record_from_events,
)
from agent_core.state.artifacts import make_artifact_ref
from agent_core.state.events import UsageEvent, UsageEventKind

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


def _evidence(evidence_id: str, excerpt: str = "kanıt") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source=SourceReference(kind="web", url=f"https://example.com/{evidence_id}", accessed_at=NOW),
        excerpt=excerpt,
        collected_at=NOW,
    )


def test_merge_evidence_drops_duplicate_ids_from_parallel_results() -> None:
    """Paralel worker'lar aynı kanıtı üretse kanal tek kopya tutar (ilk gelen kazanır)."""
    first = merge_evidence([], [_evidence("ev-1", "ilk")])
    second = merge_evidence(first, [_evidence("ev-1", "kopya"), _evidence("ev-2", "yeni")])

    assert [item.evidence_id for item in second] == ["ev-1", "ev-2"]
    assert second[0].excerpt == "ilk"  # ilk gelen korunur; kopya içerik ezmez


def test_merge_messages_drops_identical_turns() -> None:
    """Aynı (role, content, created_at) turu tekrar yürütmede çoğalmaz."""
    turn = ConversationTurn(role="assistant", content="cevap", created_at=NOW)
    merged = merge_messages([], [turn])
    again = merge_messages(merged, [ConversationTurn(role="assistant", content="cevap", created_at=NOW)])

    assert again == [turn]


def test_merge_artifact_refs_unique_by_content_address() -> None:
    """Aynı içeriğin tekrar okunması aynı artifact referansını üretir; kanal tek referans tutar."""
    ref = make_artifact_ref("source_page", "aynı içerik", created_at=NOW)
    merged = merge_artifact_refs([], [ref])
    merged = merge_artifact_refs(merged, [make_artifact_ref("source_page", "aynı içerik", created_at=NOW)])

    assert len(merged) == 1
    assert merged[0].artifact_id == ref.artifact_id


def _event(event_id: str, *, kind: UsageEventKind = UsageEventKind.MODEL_CALL, tokens: int = 10,
           outcome: str = "success", uncertain: bool = False) -> UsageEvent:
    return UsageEvent(
        event_id=event_id,
        run_id="run-a2",
        action_id=event_id.split("#")[0],
        kind=kind,
        attempt=1,
        outcome=outcome,
        total_tokens=tokens,
        prompt_tokens=tokens,
        uncertain=uncertain,
        recorded_at=NOW,
    )


def test_usage_events_deduplicated_on_reexecution() -> None:
    """Tekrar yürütme aynı event_id'yi üretir; kanal kopya kullanım kaydı oluşturmaz.

    Kabul ölçütü: "Kullanım kayıtları tekrar yürütmede kopya sonuç oluşturmuyor".
    """
    first_pass = [_event("subtask:0:answer#1", tokens=50)]
    second_pass = [_event("subtask:0:answer#1", tokens=50)]  # aynı eylemin yeniden yürütümü

    merged = merge_usage_events([], first_pass)
    merged = merge_usage_events(merged, second_pass)

    assert len(merged) == 1


def test_usage_record_counts_deduped_success_events_only() -> None:
    """Başarısız deneme çağrı sayımına girmez; belirsiz olay sayım dışıdır; retry ayrı denemedir."""
    events = [
        _event("subtask:0:answer#1", tokens=50),
        # Başarısız deneme: guard çıktı üretemediği için token bilgisi 0'dır
        # (kullanım görünümüne bilinmeyen token yazılmaz).
        _event("subtask:0:answer#2", tokens=0, outcome="failed"),
        _event("subtask:1:search#1", kind=UsageEventKind.WEB_SEARCH_CALL),
        _event("subtask:2:call#1", kind=UsageEventKind.TOOL_CALL),
        _event("subtask:3:call#1", kind=UsageEventKind.MODEL_CALL, tokens=20, uncertain=True),
    ]
    merged = merge_usage_events([], events)

    usage = usage_record_from_events("run-a2", merged, duration_seconds=1.5)

    assert usage.model_calls == 1  # belirsiz olay sayılmaz
    assert usage.web_search_calls == 1
    assert usage.tool_calls == 1
    assert usage.total_tokens == 70  # 50 + 20; belirsiz olayın token'ı rapor edilmez
    assert usage.duration_seconds == 1.5
