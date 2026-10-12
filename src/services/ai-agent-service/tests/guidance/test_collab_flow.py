"""İş birliği durum makinesi testleri (plan A9 zinciri).

Senaryolar: eksik alanlarda KISA sorularla duruş (needs_input), öneri
üretimi (düzenlenebilir özet + içerik hash'i), onay bekleyen state,
düzenleme → yeni sürüm, doğrulanmış onay + ``ValidatedActionResult`` ile
sonuç, sonucuz onayın reddi ve dürüst ret bildirimi.

SINIR kanıtı: akış yalnız ÖNERİ üretir — kayıt yok, e-posta yok; başarı
metni yalnız ``accepted`` doğrulanmış sonuçtan sonra üretilir.
"""

from __future__ import annotations

import pytest

from agent_core.collab import CollabResumeInput, CollaborationState, run_collaboration
from agent_core.collab.models import CollabStage
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import (
    RunIntent,
    RunStatus,
    ValidatedActionResult,
    compute_content_hash,
)
from agent_core.ports import CancellationToken

from .conftest import NOW, make_article_bound_context, make_route, run

INTENT = RunIntent.COLLABORATION

#: Zorunlu alanların tamamını tek mesajda taşıyan gerçekçi talep.
FULL_REQUEST = (
    "Sitenizle i\u015f birli\u011fi yapmak istiyorum: \"RabbitMQ kuyruk y\u00f6netimi\" "
    "hakk\u0131nda konuk yaz\u0131; 2 hafta i\u00e7inde; b\u00fct\u00e7e 5000 TL; mail: a@b.co"
)


def validated(proposal_id: str, outcome: str = "accepted", *, revision: int | None = 4, run_id: str = "run-1"):
    return ValidatedActionResult(
        proposal_id=proposal_id,
        run_id=run_id,
        outcome=outcome,  # type: ignore[arg-type]
        reason=None if outcome == "accepted" else "içerik güncel değildi",
        applied_article_revision=revision,
        validated_at=NOW,
    )


def test_missing_details_stop_with_short_questions_and_no_proposal() -> None:
    context = make_article_bound_context("Sitenizle bir \u015feyler yapmak istiyorum")
    state, outcome = run(run_collaboration(context, make_route(INTENT)))

    assert outcome.status is RunStatus.NEEDS_INPUT
    assert outcome.action_proposal is None  # henüz öneri üretilmez
    assert state.stage is CollabStage.DETAILS_NEEDED
    # Zorunlu eksik alan başına KISA soru; bütçe sorulmaz.
    assert len(outcome.unresolved_questions) == 4
    assert all(len(q) < 160 for q in outcome.unresolved_questions)
    assert outcome.usage.model_calls == 0


def test_complete_details_build_proposal_awaiting_explicit_approval() -> None:
    from .conftest import RecordingProgressSink

    context = make_article_bound_context(FULL_REQUEST)
    sink = RecordingProgressSink()
    state, outcome = run(run_collaboration(context, make_route(INTENT), progress=sink))

    assert state.stage is CollabStage.PROPOSAL_REVIEW
    # Onay bekleyen state: needs_input + öneri ekli + açık onay sorusu.
    assert outcome.status is RunStatus.NEEDS_INPUT
    assert outcome.action_proposal is not None
    assert len(outcome.unresolved_questions) == 1
    assert outcome.action_proposal.proposal_id in outcome.unresolved_questions[0]
    # Düzenlenebilir özet + içerik hash'li ActionProposal (sözleşme alanları).
    proposal = outcome.action_proposal
    assert "konuk yazı" in proposal.summary
    assert "RabbitMQ kuyruk yönetimi".lower() in proposal.summary.lower()
    assert proposal.base_content_hash == context.article_content_hash
    assert proposal.article_revision == context.article_revision
    # Onay sürümü hash'i B9 TEK TANIM (W6 F5): düzenlenebilir özet metninin
    # SHA-256'sı — backend AgentCollaborationContentHash.Compute(summary) ile
    # aynı değer (kabloyla uyuşan sürüm bağı).
    assert compute_content_hash(proposal.summary) == state.proposal_content_hash
    # İlerleme olayı: ACTION_PROPOSED (mevcut ProgressKind üyesi).
    assert any(event.kind.value == "action_proposed" for event in sink.events)
    # Kayıt YOKTUR: öneri metni gönderimin onay sonrası olacağını söyler.
    assert "açık onay" in proposal.proposed_content


def test_proposal_without_article_context_asks_which_content() -> None:
    # Sözleşme: ActionProposal makale üçlüsü zorunludur; bağlam yoksa
    # uydurulmaz, hangi içerik olduğu kısa soruyla istenir.
    context = make_article_bound_context(FULL_REQUEST)
    context = context.model_copy(update={"article_id": None, "article_revision": None, "article_content_hash": None, "article_snapshot": None})
    state, outcome = run(run_collaboration(context, make_route(INTENT)))

    assert outcome.status is RunStatus.NEEDS_INPUT
    assert outcome.action_proposal is None
    assert state.stage is CollabStage.DETAILS_NEEDED
    assert any("içerik bağlamı" in q for q in outcome.unresolved_questions)


def test_approval_without_backend_result_is_rejected() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                collab_input=CollabResumeInput(approved_proposal_id=state.proposal.proposal_id),
            )
        )
    # Başarı yalnız doğrulanmış işlem sonucundan sonra bildirilir; sonucuz
    # onay başarı varsaymaz (plan A9 + main-prompt kritik kontrol).
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "ValidatedActionResult" in excinfo.value.message


def test_approval_with_wrong_proposal_id_is_rejected() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                collab_input=CollabResumeInput(approved_proposal_id="prop-baska"),
                validated_result=validated("prop-baska"),
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "uyuşmuyor" in excinfo.value.message


def test_verified_acceptance_reports_success_only_after_result() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    resolved, outcome = run(
        run_collaboration(
            context,
            make_route(INTENT),
            state=state,
            collab_input=CollabResumeInput(
                approved_proposal_id=state.proposal.proposal_id,
                approved_content_hash=state.proposal_content_hash,
            ),
            validated_result=validated(state.proposal.proposal_id, "accepted", revision=4),
        )
    )

    assert resolved.stage is CollabStage.RESOLVED
    assert outcome.status is RunStatus.COMPLETED
    # Başarı metni yalnız doğrulanmış kabulde ve sürüm bilgisiyle.
    assert "kaydedildi" in outcome.answer
    assert state.proposal.proposal_id in outcome.answer
    assert "r4" in outcome.answer


def test_rejection_is_reported_honestly_without_success_claim() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    resolved, outcome = run(
        run_collaboration(
            context,
            make_route(INTENT),
            state=state,
            collab_input=CollabResumeInput(approved_proposal_id=state.proposal.proposal_id),
            validated_result=validated(state.proposal.proposal_id, "rejected", revision=None),
        )
    )

    assert resolved.stage is CollabStage.RESOLVED
    assert outcome.status is RunStatus.COMPLETED
    assert "KAYDEDİLMEDİ" in outcome.answer
    assert "kaydedildi" not in outcome.answer.split("KAYDEDİLMEDİ")[0]
    assert "içerik güncel değildi" in outcome.answer


def test_answers_complete_details_then_proposal_is_built() -> None:
    context = make_article_bound_context("Sitenizle i\u015f birli\u011fi yapmak istiyorum")
    state, first = run(run_collaboration(context, make_route(INTENT)))
    assert first.status is RunStatus.NEEDS_INPUT

    state, second = run(
        run_collaboration(
            context,
            make_route(INTENT),
            state=state,
            collab_input=CollabResumeInput(
                answers={
                    "purpose": "Konuk yaz\u0131 yazmak istiyorum",
                    "scope": "Agent mimarisi serisi",
                    "timeline": "2026-11-01",
                    "contact": "ziyaretci@example.com",
                }
            ),
        )
    )

    assert second.status is RunStatus.NEEDS_INPUT
    assert state.stage is CollabStage.PROPOSAL_REVIEW
    assert second.action_proposal is not None
    # Kullanıcının kendi ifadesi aynen taşınır (uydurma kategori yok).
    assert "Konuk yazı yazmak istiyorum" in second.action_proposal.proposed_content


def test_unknown_answer_field_rejected_with_clear_error() -> None:
    context = make_article_bound_context("Sitenizle i\u015f birli\u011fi yapmak istiyorum")
    state, _ = run(run_collaboration(context, make_route(INTENT)))

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                collab_input=CollabResumeInput(answers={"btc": "1 BTC"}),
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR


def test_edit_creates_new_proposal_version_with_new_hash() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None
    original_id = state.proposal.proposal_id
    original_hash = state.proposal_content_hash

    edited_state, outcome = run(
        run_collaboration(
            context,
            make_route(INTENT),
            state=state,
            collab_input=CollabResumeInput(
                edited_summary="Düzenlenmiş özet: çeviri katkısı",
                edited_proposed_content="Düzenlenmiş içerik gövdesi",
            ),
        )
    )

    assert outcome.status is RunStatus.NEEDS_INPUT
    assert edited_state.proposal is not None
    # Düzenleme YENİ proposal sürümüdür: kimlik ve içerik hash'i yenilenir.
    assert edited_state.proposal.proposal_id != original_id
    assert edited_state.proposal_content_hash != original_hash
    assert edited_state.proposal.proposed_content == "Düzenlenmiş içerik gövdesi"
    assert edited_state.proposal.summary.startswith("Düzenlenmiş özet")
    # ESKİ sürümün hash'iyle onay artık reddedilir (sürüm bağı).
    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=edited_state,
                collab_input=CollabResumeInput(
                    approved_proposal_id=edited_state.proposal.proposal_id,
                    approved_content_hash=original_hash,
                ),
                validated_result=validated(edited_state.proposal.proposal_id),
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "sürüm" in excinfo.value.message


def test_edit_without_existing_proposal_is_rejected() -> None:
    context = make_article_bound_context("Sitenizle \u00e7al\u0131\u015fmak istiyorum")
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.stage is CollabStage.DETAILS_NEEDED

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                collab_input=CollabResumeInput(edited_summary="erken düzenleme"),
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR


def test_approval_on_details_stage_is_rejected() -> None:
    context = make_article_bound_context("Sitenizle \u00e7al\u0131\u015fmak istiyorum")
    state, _ = run(run_collaboration(context, make_route(INTENT)))

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                collab_input=CollabResumeInput(approved_proposal_id="prop-yok"),
                validated_result=validated("prop-yok"),
            )
        )
    assert "onay bekleyen" in excinfo.value.message


def test_backend_result_for_other_run_is_rejected() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                collab_input=CollabResumeInput(approved_proposal_id=state.proposal.proposal_id),
                validated_result=validated(state.proposal.proposal_id, run_id="run-baska"),
            )
        )
    assert "başka çalışmaya" in excinfo.value.message


def test_backend_result_alone_completes_approved_proposal() -> None:
    # B9 sözleşmesi: AgentActionResultV1 belirli proposal'a bağlıdır; kontrol
    # consumer'ı onay kimliğini yankılamadan yalnız sonucu taşıyabilir —
    # sonuç checkpoint'teki proposal'a bağlanarak denetlenir.
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    resolved, outcome = run(
        run_collaboration(
            context,
            make_route(INTENT),
            state=state,
            validated_result=validated(state.proposal.proposal_id),
        )
    )

    assert resolved.stage is CollabStage.RESOLVED
    assert outcome.status is RunStatus.COMPLETED
    assert "kaydedildi" in outcome.answer


def test_backend_result_alone_for_other_proposal_is_rejected() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    with pytest.raises(PortError) as excinfo:
        run(
            run_collaboration(
                context,
                make_route(INTENT),
                state=state,
                validated_result=validated("prop-baska-sürüm"),
            )
        )
    assert "başka öneriye" in excinfo.value.message


def test_resolved_state_cannot_be_continued() -> None:
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    resolved, _ = run(
        run_collaboration(
            context,
            make_route(INTENT),
            state=state,
            collab_input=CollabResumeInput(approved_proposal_id=state.proposal.proposal_id),
            validated_result=validated(state.proposal.proposal_id),
        )
    )

    with pytest.raises(PortError) as excinfo:
        run(run_collaboration(context, make_route(INTENT), state=resolved))
    assert "sonuçlandı" in excinfo.value.message


def test_cancel_signal_is_honoured_before_any_step() -> None:
    from agent_core.adapters.test_doubles import PreCancelledToken

    context = make_article_bound_context(FULL_REQUEST)
    token = PreCancelledToken()

    with pytest.raises(PortError) as excinfo:
        run(run_collaboration(context, make_route(INTENT), cancel=token))
    assert excinfo.value.code is AgentErrorCode.CANCELLED


def test_proposal_review_state_is_idempotent_on_repeat_call() -> None:
    # Aynı state ile yeniden çağrı (resume girdisiz): öneri AYNI sürümle
    # yeniden sunulur — yeni sürüm üretilmez, idempotent davranış.
    context = make_article_bound_context(FULL_REQUEST)
    state, _ = run(run_collaboration(context, make_route(INTENT)))
    assert state.proposal is not None

    again_state, again_outcome = run(run_collaboration(context, make_route(INTENT), state=state))

    assert again_outcome.status is RunStatus.NEEDS_INPUT
    assert again_state.proposal.proposal_id == state.proposal.proposal_id
    assert again_state.proposal_content_hash == state.proposal_content_hash


# --------------------------------------------------- W6 bütünleştirme kuralları


def test_generated_proposal_id_is_canonical_uuid() -> None:
    # W6 F2: B9 backend hattı proposal kimliğini Guid olarak çözer
    # (AgentEventProjectionConsumer BuildProposalUpsert); 'prop-<hex>' biçimi
    # tüketici tarafında FormatException → DLQ üretirdi. Üretici KANONİK UUID
    # (RFC 4122 D biçimi) taahhüdündedir; sözleşmedeki identifier serbest
    # string olduğu için UUID alt kümesi iki tarafı da geçer.
    import uuid as uuid_module

    context = make_article_bound_context(FULL_REQUEST)
    state, outcome = run(run_collaboration(context, make_route(INTENT)))
    proposal = outcome.action_proposal
    assert proposal is not None

    parsed = uuid_module.UUID(proposal.proposal_id)
    # Kanonik D biçimi: birebir gidiş-dönüş (Guid.TryParseExact("D") karşılığı).
    assert str(parsed) == proposal.proposal_id
    # Üretim tekrarında yeni kimlik (sürüm kimliği çakışmaz).
    _state2, outcome2 = run(run_collaboration(context, make_route(INTENT)))
    assert outcome2.action_proposal is not None
    assert outcome2.action_proposal.proposal_id != proposal.proposal_id


def test_proposal_content_hash_is_b9_summary_hash() -> None:
    # W6 F5: onay sürümü hash'i TEK TANIM — düzenlenebilir özet metninin
    # UTF-8 SHA-256'sı (lowercase hex). Backend'in kalıcıladığı tek metin
    # özettir; gövde hash'i kabloyla asla karşılaştırılamazdı.
    import hashlib

    context = make_article_bound_context(FULL_REQUEST)
    state, outcome = run(run_collaboration(context, make_route(INTENT)))
    proposal = outcome.action_proposal
    assert proposal is not None

    expected = hashlib.sha256(proposal.summary.encode("utf-8")).hexdigest()
    assert state.proposal_content_hash == expected
    assert state.proposal_content_hash == compute_content_hash(proposal.summary)
