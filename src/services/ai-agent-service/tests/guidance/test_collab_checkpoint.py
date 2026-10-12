"""İş birliği akışının giriş noktası + A8 checkpoint entegrasyonu (plan A9:
"needs_input durumunda dur ve checkpoint'i sakla"; "Devam girdisinde ...
düzenleme sonucunu işleme").

Checkpoint YENİ store örneğiyle okunarak süreç restart benzetimi yapılır
(A8 kabul deseni); model double'ı çağrı sayacı 0 kalana kadar patlar —
iş birliği hazırlığının model çağrısı olmadığını ve başarı bildiriminin
yalnız doğrulanmış sonuçla geldiğini kanıtlar.
"""

from __future__ import annotations

import pytest

from agent_core.adapters.test_doubles import FakeCheckpointStore
from agent_core.checkpoint import FileCheckpointStore
from agent_core.checkpoint.models import CheckpointEnvelope
from agent_core.entrypoints import PreparedRun, ResumeRequest, execute_plan, prepare_and_route, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import RunStatus, ValidatedActionResult

from .conftest import NOW, ExplodingModelProvider, make_article_bound_context, run

FULL_REQUEST = (
    "Sitenizle i\u015f birli\u011fi yapmak istiyorum: \"RabbitMQ kuyruk y\u00f6netimi\" "
    "hakk\u0131nda konuk yaz\u0131; 2 hafta i\u00e7inde; b\u00fct\u00e7e 5000 TL; mail: a@b.co"
)
PARTIAL_REQUEST = "Sitenizle i\u015f birli\u011fi yapmak istiyorum"


def make_validated(proposal_id: str, run_id: str, *, outcome: str = "accepted"):
    return ValidatedActionResult(
        proposal_id=proposal_id,
        run_id=run_id,
        outcome=outcome,  # type: ignore[arg-type]
        applied_article_revision=4 if outcome == "accepted" else None,
        validated_at=NOW,
    )


def test_needs_input_persists_checkpoint_and_resume_completes(tmp_path) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    first_store = FileCheckpointStore(str(checkpoint_dir))
    model = ExplodingModelProvider()
    context = make_article_bound_context(PARTIAL_REQUEST)

    prepared = run(prepare_and_route(context, checkpoint=first_store, execution_id="exec-run-1-aaa"))
    assert prepared.route.intent.value == "collaboration"

    outcome = run(
        execute_plan(
            prepared,
            model=model,  # patlayan double: akış model çağıramaz
            checkpoint=first_store,
        )
    )
    assert outcome.status is RunStatus.NEEDS_INPUT
    # "iş birliği" amacı sinyalden çıkar; kapsam/takvim/iletişim eksik kalır (3 soru).
    assert len(outcome.unresolved_questions) == 3
    assert model.call_count == 0

    # Süreç restart benzetimi: YENİ store örneğiyle checkpoint'ten okunur.
    fresh_store = FileCheckpointStore(str(checkpoint_dir))
    _envelope, payload = run(fresh_store.load_latest(context.run_id))
    envelope = CheckpointEnvelope.model_validate_json(payload.decode("utf-8"))
    assert envelope.kind.value == "prepared"
    assert envelope.execution_id == "exec-run-1-aaa"
    restored = PreparedRun.model_validate_json(envelope.payload_bytes().decode("utf-8"))
    assert restored.collab_state is not None
    assert restored.collab_state.stage.value == "details_needed"
    assert len(restored.collab_state.questions) == 3

    # Devam girdisi: eksik alan cevapları → öneri üretilir, onay bekler.
    from agent_core.collab import CollabResumeInput

    second_outcome = run(
        resume(
            ResumeRequest(
                run_id=context.run_id,
                execution_id="exec-run-1-aaa",
                collab_input=CollabResumeInput(
                    answers={
                        "purpose": "Konuk yaz\u0131",
                        "scope": "Agent mimarisi",
                        "timeline": "2 hafta",
                        "contact": "z@example.com",
                    }
                ),
            ),
            checkpoint=fresh_store,
            model=model,
        )
    )
    assert second_outcome.status is RunStatus.NEEDS_INPUT
    assert second_outcome.action_proposal is not None
    assert model.call_count == 0

    # Doğrulanmış onay + backend sonucu → terminal başarı (yalnız şimdi).
    proposal_id = second_outcome.action_proposal.proposal_id
    final_outcome = run(
        resume(
            ResumeRequest(
                run_id=context.run_id,
                execution_id="exec-run-1-aaa",
                collab_input=CollabResumeInput(approved_proposal_id=proposal_id),
                validated_result=make_validated(proposal_id, context.run_id),
            ),
            checkpoint=fresh_store,
            model=model,
        )
    )
    assert final_outcome.status is RunStatus.COMPLETED
    assert "kaydedildi" in final_outcome.answer
    assert model.call_count == 0  # hiçbir aşamada model çağrısı yapılmadı


def test_collab_without_checkpoint_store_fails_with_config_error() -> None:
    context = make_article_bound_context(PARTIAL_REQUEST)
    prepared = run(prepare_and_route(context))

    outcome = run(execute_plan(prepared, model=ExplodingModelProvider(), checkpoint=None))

    # needs_input'un SAKLANMASI sözleşmenin parçasıdır; depo yoksa akış
    # sessizce devam etmez — dürüst config_error terminali döner.
    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.CONFIG_ERROR


def test_route_decision_binds_collab_intent_through_prepare(tmp_path) -> None:
    store = FakeCheckpointStore()
    context = make_article_bound_context(FULL_REQUEST)

    prepared = run(prepare_and_route(context, checkpoint=store))

    assert prepared.route.intent.value == "collaboration"
    assert prepared.route.selected_mode.value == "fast"
    assert prepared.route.needs_web is False
