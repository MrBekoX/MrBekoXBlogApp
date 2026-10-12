"""İş birliği hazırlık akışı: çıkarım → soru → öneri → onay → sonuç (plan A9).

Plan A9 zincirinin yürütücüsü:

1. Amaç/kapsam/takvim/opsiyonel bütçe/iletişim çıkarımı (``extract``).
2. Zorunlu alan eksikse KISA sorularla ``needs_input`` — DURULUR ve state
   checkpoint'e saklanır (A8 zarfıyla; ``entrypoints`` yazımını yapar).
3. Detaylar tamamlandığında düzenlenebilir özet + içerik hash'li
   ``ActionProposal`` üretilir ve AÇIK ONAY beklenir (``needs_input``).
4. Resume girdisinde cevap/düzenleme işlenir; onay yalnız belirli proposal
   kimliği + içerik sürümüyle eşleşirse kabul edilir ve GERÇEK kayıt sonucu
   ``ValidatedActionResult`` ile alınır.
5. Başarı yalnız ``ValidatedActionResult.outcome == "accepted"`` SONRASINDA
   bildirilir; red gerekçesiyle dürüstçe aktarılır.

SINIR: bu akış backend'e talep KAYDEtmez ve e-posta GÖNDERMEZ; yalnız öneri
üretir ve onay bekler (kayıt B9/B10'dadır). Onaylı devam için doğrulanmış
backend sonucu ZORUNLUDUR — sonucu olmayan onay ``validation_error`` ile
reddedilir, başarı asla varsayılmaz.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..errors import AgentErrorCode, PortError
from ..models import (
    ActionProposal,
    AgentOutcome,
    RouteDecision,
    RunStatus,
    SourceScope,
    UsageRecord,
    ValidatedActionResult,
    compute_content_hash,
)
from ..ports import ProgressSink
from .extract import extract_collaboration_details, merge_answer, questions_for_missing_fields
from .models import CollabField, CollabResumeInput, CollabStage, CollaborationState
from .proposal import build_collab_proposal

__all__ = ["run_collaboration"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _usage(run_id: str, started_at: datetime) -> UsageRecord:
    """İş birliği hazırlığı model çağırmaz; kullanım kaydı buna göre yazılır."""
    return UsageRecord(
        run_id=run_id,
        model_calls=0,
        duration_seconds=max((_utcnow() - started_at).total_seconds(), 0.0),
        recorded_at=_utcnow(),
    )


def _outcome(
    route: RouteDecision,
    started_at: datetime,
    *,
    status: RunStatus,
    answer: str | None,
    questions: list[str] | None = None,
    proposal: ActionProposal | None = None,
    error_code: AgentErrorCode | None = None,
    error_message: str | None = None,
) -> AgentOutcome:
    return AgentOutcome(
        selected_mode=route.selected_mode,
        status=status,
        answer=answer,
        source_scope=SourceScope.GENERAL,
        unresolved_questions=questions or [],
        usage=_usage(route.run_id, started_at),
        action_proposal=proposal,
        error_code=error_code,
        error_message=error_message,
    )


def _validation_error(message: str) -> PortError:
    return PortError(AgentErrorCode.VALIDATION_ERROR, message, port="run_collaboration")


def _questions_block(route: RouteDecision, state: CollaborationState, *, started_at: datetime) -> AgentOutcome:
    """Eksik detaylar için ``needs_input`` terminali; çalışma burada DURUR."""
    return _outcome(
        route,
        started_at,
        status=RunStatus.NEEDS_INPUT,
        answer=None,
        questions=list(state.questions),
    )


def _approval_question(proposal: ActionProposal, language: str) -> str:
    if language.casefold().startswith("tr"):
        return (
            f"{proposal.proposal_id} kimlikli iş birliği önerisini onaylıyor musunuz? "
            "Gönderim yalnızca açık onayınızla ve backend doğrulamasıyla kayda dönüşür; "
            "özet/içeriği düzenleyip yeni sürüm de isteyebilirsiniz."
        )
    return (
        f"Do you approve the collaboration proposal {proposal.proposal_id}? "
        "Submission becomes a record only with your explicit approval and backend "
        "verification; you can also edit the summary/content for a new version."
    )


def _resolved_answer(result: ValidatedActionResult, language: str) -> str:
    """Kayıt sonucunun dürüst metni: başarı yalnız doğrulanmış kabulde."""
    turkish = language.casefold().startswith("tr")
    if result.outcome == "accepted":
        if turkish:
            return (
                "İş birliği talebiniz doğrulandı ve kaydedildi "
                f"(proposal: {result.proposal_id}, uygulanan revizyon: r{result.applied_article_revision})."
            )
        return (
            "Your collaboration request was verified and registered "
            f"(proposal: {result.proposal_id}, applied revision: r{result.applied_article_revision})."
        )
    reason = result.reason or ""
    if turkish:
        return (
            f"İş birliği talebi KAYDEDİLMEDİ (proposal: {result.proposal_id})."
            + (f" Gerekçe: {reason}" if reason else "")
        )
    return (
        f"Your collaboration request was NOT registered (proposal: {result.proposal_id})."
        + (f" Reason: {reason}" if reason else "")
    )


async def _publish_action_proposed(progress: ProgressSink | None, proposal: ActionProposal) -> None:
    if progress is None:
        return
    from ..models import DomainProgress, ProgressKind

    try:
        await progress.publish(
            DomainProgress(
                run_id=proposal.run_id,
                kind=ProgressKind.ACTION_PROPOSED,
                message=f"iş birliği önerisi hazırlandı: {proposal.proposal_id} (onay bekliyor)",
                occurred_at=_utcnow(),
                # W6 F1: proposal'ın tamamı sink ile taşınır; worker progress
                # sink'i bunu sözleşmedeki agent.action.proposed olayına çevirir.
                # Taşınmasaydı B5/B9 hattı ölü yol olurdu (proposal kaydı hiç
                # yazılmaz, onay akışı başlamazdı).
                proposal=proposal,
            )
        )
    except PortError:
        return  # sink arızası akışı başarısızlaştırmaz (port sözleşmesi)


def _apply_answers(state: CollaborationState, collab_input: CollabResumeInput) -> CollaborationState:
    """Resume cevaplarını detaya işler; bilinmeyen alan anlaşılır hatayla reddedilir."""
    if not collab_input.answers:
        return state
    details = state.details
    for field_name, value in collab_input.answers.items():
        try:
            details = merge_answer(details, field_name, value)
        except ValueError as error:
            raise _validation_error(str(error)) from error
    return state.model_copy(update={"details": details})


def _build_or_edit_proposal(
    context,
    state: CollaborationState,
    collab_input: CollabResumeInput | None,
    language: str,
) -> CollaborationState:
    """Detaylar tamamken öneri üretir veya düzenleme uygular (yeni sürüm)."""
    proposal = state.proposal
    content_hash = state.proposal_content_hash
    edited = collab_input is not None and (
        collab_input.edited_summary is not None or collab_input.edited_proposed_content is not None
    )
    if proposal is None or edited:
        fresh, fresh_hash = build_collab_proposal(context, state.details, language)
        summary = fresh.summary
        content = fresh.proposed_content
        if edited and collab_input is not None:
            # Düzenleme YENİ SÜRÜM üretir; kimlik ve içerik hash'i yenilenir (B9 sürüm bağı).
            summary = (collab_input.edited_summary or summary).strip()
            content = (collab_input.edited_proposed_content or content).strip()
        proposal = fresh.model_copy(
            update={
                "summary": summary,
                "proposed_content": content,
            }
        )
        # B9 tek tanım: onay sürümü hash'i düzenlenebilir özet metninin SHA-256'sı
        # (backend AgentCollaborationContentHash.Compute(summary) ile aynı değer).
        content_hash = compute_content_hash(proposal.summary)
    return state.model_copy(
        update={
            "stage": CollabStage.PROPOSAL_REVIEW,
            "proposal": proposal,
            "proposal_content_hash": content_hash,
            "missing_fields": [],
            "questions": [],
        }
    )


async def run_collaboration(
    context,
    route: RouteDecision,
    *,
    state: CollaborationState | None = None,
    collab_input: CollabResumeInput | None = None,
    validated_result: ValidatedActionResult | None = None,
    progress: ProgressSink | None = None,
    cancel=None,
) -> tuple[CollaborationState, AgentOutcome]:
    """İş birliği hazırlık state makinesinin bir adımını yürütür.

    Args:
        context: ``ExecutionContext``.
        route: hazırlıktaki ``RouteDecision`` (``intent=collaboration``).
        state: checkpoint'ten gelen önceki state; ``None`` taze yürütmedir.
        collab_input: resume girdisi (cevaplar / düzenleme / onay).
        validated_result: backend'in doğrulanmış kayıt kararı; yalnız onaylı
            devrede zorunludur (B9 kontrol consumer'ı taşır).

    Returns:
        ``(güncel_state, terminal_outcome)`` — state'i çağıran checkpoint'e yazar.

    Raises:
        PortError: ``cancelled`` — iptal sinyali; ``validation_error`` —
            bilinmeyen alan, öneri olmayan yerde düzenleme/onay, sürüm
            uyuşmazlığı, sonucuz onay veya sonuçlanmış çalışmaya müdahale.
    """
    if cancel is not None:
        cancel.raise_if_cancelled()
    started_at = _utcnow()
    language = context.language

    if state is None:
        article_title = context.article_snapshot.title if context.article_snapshot is not None else None
        state = CollaborationState(
            stage=CollabStage.DETAILS_NEEDED,
            details=extract_collaboration_details(context, article_title=article_title),
        )
    elif state.stage is CollabStage.RESOLVED:
        raise _validation_error("bu iş birliği çalışması sonuçlandı; sonuç üzerine devam edilmez")

    # 1) Onay yolu: açık onay girdisi VEYA backend'in doğrulanmış sonucu.
    #    AgentActionResultV1 belirli proposal'a bağlıdır; backend sonucu tek
    #    başına da onaylı devamı tetikler (B9 kontrol consumer'ı sözleşmesi),
    #    ancak sonucun proposal/sürüm bağlamı checkpoint'tekine DENETLENİR.
    approval_requested = (collab_input is not None and collab_input.approved_proposal_id is not None) or (
        validated_result is not None
    )
    if approval_requested:
        if state.stage is not CollabStage.PROPOSAL_REVIEW or state.proposal is None:
            raise _validation_error("onay bekleyen bir iş birliği önerisi yok")
        proposal = state.proposal
        if (
            collab_input is not None
            and collab_input.approved_proposal_id is not None
            and collab_input.approved_proposal_id != proposal.proposal_id
        ):
            raise _validation_error(
                "onaylanan öneri kimliği uyuşmuyor: beklenen="
                f"{proposal.proposal_id}, gelen={collab_input.approved_proposal_id}"
            )
        if (
            collab_input is not None
            and collab_input.approved_content_hash is not None
            and state.proposal_content_hash is not None
            and collab_input.approved_content_hash != state.proposal_content_hash
        ):
            raise _validation_error(
                "onay içerik sürümü uyuşmuyor: öneri onaydan sonra düzenlenmiş olabilir; "
                "güncel sürümü yeniden isteyin"
            )
        if validated_result is None:
            # Başarı yalnız doğrulanmış işlem sonucundan sonra bildirilir; sonucuz
            # onay başarı varsayılmaz (plan A9 + main-prompt kritik kontrol).
            raise _validation_error(
                "onaylı devam için doğrulanmış ValidatedActionResult zorunludur; "
                "backend kayıt sonucu olmadan graph sürdürülmez"
            )
        if validated_result.proposal_id != proposal.proposal_id:
            raise _validation_error(
                "backend sonucu başka öneriye ait: beklenen="
                f"{proposal.proposal_id}, gelen={validated_result.proposal_id}"
            )
        if validated_result.run_id != context.run_id:
            raise _validation_error(
                "backend sonucu başka çalışmaya ait: beklenen="
                f"{context.run_id}, gelen={validated_result.run_id}"
            )
        resolved = state.model_copy(update={"stage": CollabStage.RESOLVED})
        outcome = _outcome(
            route,
            started_at,
            status=RunStatus.COMPLETED,
            answer=_resolved_answer(validated_result, language),
        )
        return resolved, outcome

    # 2) Düzenleme yolu yalnız cevaplarla birleşebilir; eksik detayla öneri/düzenleme yoktur.
    edited_requested = collab_input is not None and (
        collab_input.edited_summary is not None or collab_input.edited_proposed_content is not None
    )
    if collab_input is not None and collab_input.answers:
        state = _apply_answers(state, collab_input)

    missing = state.details.missing_required()
    if missing:
        if edited_requested and state.proposal is None:
            raise _validation_error("düzenlenecek öneri yok; önce zorunlu alanlar tamamlanmalıdır")
        questions = questions_for_missing_fields(missing, language)
        state = state.model_copy(
            update={
                "stage": CollabStage.DETAILS_NEEDED,
                "missing_fields": [f.value for f in missing],
                "questions": questions,
            }
        )
        return state, _questions_block(route, state, started_at=started_at)

    # 3) Öneri üretimi/düzenlemesi; makale bağlamı zorunludur (sözleşme).
    #    Cevaplarla aynı turda gelen düzenleme geçerlidir: _build_or_edit_proposal
    #    önce taze öneriyi üretir, sonra düzenlemeyi yeni sürüm olarak uygular.
    try:
        state = _build_or_edit_proposal(context, state, collab_input, language)
    except PortError as error:
        if error.code is AgentErrorCode.CANCELLED:
            raise
        if error.code is AgentErrorCode.VALIDATION_ERROR and context.article_id is None:
            # Sözleşme gereği öneri makaleye bağlıdır; bağlam yoksa uydurulmaz,
            # hangi içerik olduğu kısa soruyla istenir (needs_input'ta dur).
            question = (
                "İş birliği önerisi bir içerik bağlamına bağlı olmalıdır; hangi makale "
                "veya konu için hazırlanmalı?"
                if language.casefold().startswith("tr")
                else "A collaboration proposal must be bound to a content context; which "
                "article or topic should it be prepared for?"
            )
            state = state.model_copy(
                update={
                    "stage": CollabStage.DETAILS_NEEDED,
                    "missing_fields": ["article_context"],
                    "questions": [question],
                }
            )
            return state, _questions_block(route, state, started_at=started_at)
        raise

    await _publish_action_proposed(progress, state.proposal)  # type: ignore[arg-type]
    outcome = _outcome(
        route,
        started_at,
        status=RunStatus.NEEDS_INPUT,
        answer=None,
        questions=[_approval_question(state.proposal, language)],  # type: ignore[arg-type]
        proposal=state.proposal,
    )
    return state, outcome
