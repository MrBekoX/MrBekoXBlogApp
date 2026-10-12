"""W6 F1: worker progress sink'inin ``ACTION_PROPOSED`` yönlendirmesi.

A9 öneri olayı ``agent.run.progressed``'e düşürülürse B5/B9 hattı ölü yol
olurdu (proposal kaydı hiç yazılmaz, onay akışı başlamazdı). Sink sözleşme
köprüsüdür: domain ``ActionProposal`` taşıyan ``DomainProgress`` olayını B1
``agent.action.proposed`` payload'ına çevirir; diğer kind'lar aynen progressed
kalır. Bu dosya broker'sız birim testtir (çift yayıncı kaydeder).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.models import DomainProgress, ProgressKind, compute_content_hash
from agent_core.models.action import ActionProposal

from .helpers import run
from messaging.worker import _LeaseWatch, _WorkerProgressSink


class _FakeWatch:
    """Lease watch double: heartbeat gözlemlenir, lease kaybı yok."""

    is_test_double = True

    def __init__(self) -> None:
        self.beats = 0

    async def heartbeat(self) -> None:
        self.beats += 1


class _RecordingPublisher:
    """İki yayın yöntemini ayırarak kaydeden double (B5 ``AgentEventPublisher``)."""

    is_test_double = True

    def __init__(self) -> None:
        self.progressed: list[dict[str, Any]] = []
        self.proposed: list[dict[str, Any]] = []

    async def publish_progress(self, **kwargs: Any) -> Any:
        self.progressed.append(kwargs)
        return object()  # ThrottledProgress değil

    async def publish_action_proposed(self, **kwargs: Any) -> Any:
        self.proposed.append(kwargs)
        return object()


def _proposal(run_id: str) -> ActionProposal:
    return ActionProposal(
        proposal_id="7b9c0000-0000-0000-0000-00000000c0de",
        run_id=run_id,
        article_id="1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1",
        article_revision=3,
        base_content_hash=compute_content_hash("makale-içeriği"),
        summary="İş birliği önerisi — konuk yazı. Kapsam: W6. Takvim: ekim.",
        proposed_content="İş birliği talebi (öneri)\n\nAmaç: konuk yazı",
        created_at=datetime.now(timezone.utc),
    )


def _sink(publisher: Any, watch: Any) -> Any:
    return _WorkerProgressSink(
        run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2",
        conversation_id="3aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa3",
        correlation_id="4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa4",
        causation_id="5aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa5",
        execution_attempt=1,
        publisher=publisher,
        watch=watch,
    )


def test_action_proposed_event_routes_to_contract_publisher() -> None:
    publisher = _RecordingPublisher()
    watch = _FakeWatch()
    sink = _sink(publisher, watch)
    run_id = "2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2"
    proposal = _proposal(run_id)

    run(sink.publish(DomainProgress(
        run_id=run_id,
        kind=ProgressKind.ACTION_PROPOSED,
        message="öneri hazır",
        occurred_at=datetime.now(timezone.utc),
        proposal=proposal,
    )))

    assert watch.beats == 1  # lease heartbeat ilerlemeye bağlı kalır
    assert publisher.progressed == []  # progressed'e DÜŞMEZ (ölü yol düzeltmesi)
    assert len(publisher.proposed) == 1
    call = publisher.proposed[0]
    assert call["run_id"] == run_id
    assert call["conversation_id"] == "3aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa3"
    assert call["correlation_id"] == "4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa4"
    assert call["causation_id"] == "5aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa5"
    assert call["execution_attempt"] == 1
    payload = call["proposal"]
    assert payload.proposal_id == proposal.proposal_id
    assert payload.article_id == proposal.article_id
    assert payload.article_revision == 3
    assert payload.base_content_hash == proposal.base_content_hash
    assert payload.summary == proposal.summary
    assert payload.proposed_content == proposal.proposed_content
    assert payload.created_at.endswith("Z")


def test_action_proposed_without_proposal_falls_back_to_progressed() -> None:
    # Savunmacı yol: proposal taşımayan ACTION_PROPOSED (eski üretici) sözleşme
    # olayına ÇEVRİLEMEZ; progressed olarak akar (sessiz kayıp yok).
    publisher = _RecordingPublisher()
    sink = _sink(publisher, _FakeWatch())
    run_id = "2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2"

    run(sink.publish(DomainProgress(
        run_id=run_id,
        kind=ProgressKind.ACTION_PROPOSED,
        message="öneri hazır (proposal'sız)",
        occurred_at=datetime.now(timezone.utc),
    )))

    assert publisher.proposed == []
    assert len(publisher.progressed) == 1
    assert publisher.progressed[0]["kind"] == "action_proposed"


def test_other_kinds_still_publish_progressed() -> None:
    publisher = _RecordingPublisher()
    sink = _sink(publisher, _FakeWatch())
    run_id = "2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2"

    run(sink.publish(DomainProgress(
        run_id=run_id,
        kind=ProgressKind.GENERATION_STARTED,
        message="üretim başladı",
        occurred_at=datetime.now(timezone.utc),
    )))

    assert publisher.proposed == []
    assert len(publisher.progressed) == 1
    assert publisher.progressed[0]["kind"] == "generation_started"


def test_worker_sink_module_exports_watch_types() -> None:
    # Paket-içi kullanım sözleşmesi: sink, _LeaseWatch ile kurulur; bu test
    # sembollerin modül bağlantısını sabitler (yeniden adlandırmada kırılır).
    assert _LeaseWatch is not None
