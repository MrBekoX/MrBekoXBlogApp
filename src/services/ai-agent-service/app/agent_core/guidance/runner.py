"""Site rehberliği akışı: profil tanıtımı, proje rehberi, makale önerisi (plan A9).

Plan A9 profil/proje davranışının yürütücüsü:

- ``ProfileRepository`` / ``ProjectRepository`` portlarının ONAYLI
  kayıtlarından deterministik tr/en cevap üretilir; model çağrısı YAPILMAZ —
  onaylı olmayan hiçbir bilgi üretime karışamaz.
- Eksik deneyim/ücret/müsaitlik bilgisi sorulursa uydurulmaz; açık
  ``needs_input`` terminaliyle bildirilir.
- İlgiye göre makale önerisi yalnız çağıranın verdiği onaylı katalog
  kayıtlarıyla çalışır; kısa uygunluk gerekçesi ve kaynak bağlantısı
  taşır. Katalog bağlı değilse öneri üretilmez, dürüst not döner.

Hata sözleşmesi: port hataları terminal ``AgentOutcome``'a çevrilir
(``config_error``/``not_found``/``provider_error``/``timeout``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..errors import AgentErrorCode, PortError
from ..models import (
    AgentOutcome,
    RouteDecision,
    RunIntent,
    RunStatus,
    SourceScope,
    UsageRecord,
)
from ..ports import ProgressSink, ProfileRepository, ProjectRepository
from .compose import (
    compose_profile_answer,
    compose_projects_answer,
    compose_suggestion_answer,
    detect_missing_info_fields,
    missing_info_questions,
    project_interest_tokens,
    suggest_articles,
    unavailable_note,
)
from .models import ArticleCatalogEntry, GuidanceRunResult, MissingInfoField

__all__ = ["run_guidance"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _usage(run_id: str, started_at: datetime) -> UsageRecord:
    """Rehberlik akışı model çağırmaz; kullanım kaydı buna göre yazılır."""
    return UsageRecord(
        run_id=run_id,
        model_calls=0,
        duration_seconds=max((_utcnow() - started_at).total_seconds(), 0.0),
        recorded_at=_utcnow(),
    )


def _failed_outcome(route: RouteDecision, started_at: datetime, error: PortError) -> AgentOutcome:
    return AgentOutcome(
        selected_mode=route.selected_mode,
        status=RunStatus.FAILED,
        source_scope=SourceScope.GENERAL,
        usage=_usage(route.run_id, started_at),
        error_code=error.code,
        error_message=error.message,
    )


def _scope_for(intent: RunIntent) -> SourceScope:
    if intent is RunIntent.PROFILE:
        return SourceScope.PROFILE
    if intent is RunIntent.PROJECTS:
        return SourceScope.PROJECTS
    return SourceScope.GENERAL


async def run_guidance(
    context,
    route: RouteDecision,
    *,
    profile_repository: ProfileRepository | None = None,
    project_repository: ProjectRepository | None = None,
    article_catalog: list[ArticleCatalogEntry] | None = None,
    progress: ProgressSink | None = None,
    cancel=None,
) -> GuidanceRunResult:
    """Rehberlik niyetini (profil/proje/öneri) onaylı kayıtlardan yürütür.

    ``context`` ``ExecutionContext``'tir; yalnız ``run_id``/``question``/
    ``language`` alanları kullanılır. Model sağlayıcısı ALINMAZ: tüm cevaplar
    onaylı kayıtlardan deterministik kompozisyondur.

    Raises:
        PortError: ``cancelled`` — iptal sinyali.
    """
    if cancel is not None:
        cancel.raise_if_cancelled()
    started_at = _utcnow()
    run_id = context.run_id
    language = context.language
    intent = route.intent

    if progress is not None:
        from ..models import DomainProgress, ProgressKind

        try:
            await progress.publish(
                DomainProgress(
                    run_id=run_id,
                    kind=ProgressKind.GENERATION_STARTED,
                    message="onaylı kayıtlardan rehberlik cevabı hazırlanıyor",
                    occurred_at=_utcnow(),
                )
            )
        except PortError:
            pass

    try:
        if intent is RunIntent.PROFILE:
            if profile_repository is None:
                return GuidanceRunResult(
                    outcome=_config_error(route, started_at, "profil deposu", language),
                    state={},
                )
            profile = await profile_repository.get_profile()
            missing = detect_missing_info_fields(context.question)
            answer = compose_profile_answer(profile, language, missing_fields=missing)
            if missing:
                # Plan A9: eksik deneyim/ücret/müsaitlik uydurulmaz — açık soruyla dur.
                outcome = AgentOutcome(
                    selected_mode=route.selected_mode,
                    status=RunStatus.NEEDS_INPUT,
                    answer=answer,
                    source_scope=_scope_for(intent),
                    unresolved_questions=missing_info_questions(missing, language),
                    usage=_usage(run_id, started_at),
                )
            else:
                outcome = AgentOutcome(
                    selected_mode=route.selected_mode,
                    status=RunStatus.COMPLETED,
                    answer=answer,
                    source_scope=_scope_for(intent),
                    usage=_usage(run_id, started_at),
                )
            return GuidanceRunResult(outcome=outcome, state={"missing_info_fields": [f.value for f in missing]})

        if intent is RunIntent.PROJECTS:
            if project_repository is None:
                return GuidanceRunResult(
                    outcome=_config_error(route, started_at, "proje deposu", language),
                    state={},
                )
            projects = await project_repository.list_projects()
            interest = project_interest_tokens(context.question)
            answer = compose_projects_answer(projects, language, interest_tokens=interest)
            return GuidanceRunResult(
                outcome=AgentOutcome(
                    selected_mode=route.selected_mode,
                    status=RunStatus.COMPLETED,
                    answer=answer,
                    source_scope=_scope_for(intent),
                    usage=_usage(run_id, started_at),
                ),
                state={"project_count": len(projects)},
            )

        # CONTENT_SUGGESTION: yalnız verilen onaylı katalogla; katalog yoksa dürüst not.
        catalog = list(article_catalog or [])
        if not catalog:
            return GuidanceRunResult(
                outcome=AgentOutcome(
                    selected_mode=route.selected_mode,
                    status=RunStatus.PARTIAL,
                    answer=unavailable_note("makale kataloğu", language),
                    source_scope=_scope_for(intent),
                    usage=_usage(run_id, started_at),
                ),
                state={"suggestions": 0},
            )
        suggestions = suggest_articles(context.question, catalog, language)
        answer = compose_suggestion_answer(suggestions, language)
        return GuidanceRunResult(
            outcome=AgentOutcome(
                selected_mode=route.selected_mode,
                status=RunStatus.COMPLETED if suggestions else RunStatus.PARTIAL,
                answer=answer,
                source_scope=_scope_for(intent),
                usage=_usage(run_id, started_at),
            ),
            state={"suggestions": len(suggestions)},
        )

    except PortError as error:
        if error.code is AgentErrorCode.CANCELLED:
            raise
        return GuidanceRunResult(outcome=_failed_outcome(route, started_at, error), state={})


def _config_error(route: RouteDecision, started_at: datetime, capability: str, language: str) -> AgentOutcome:
    """Onaylı kaynak bağlı değilken dürüst ``config_error`` terminali.

    Rehberlik niyeti kayıtsız model çağrısına DÜŞMEZ: onaylı kayıt olmadan
    cevap üretmek uydurma riskidir; kapasite bağlı değil açıkça bildirilir.
    """
    return AgentOutcome(
        selected_mode=route.selected_mode,
        status=RunStatus.FAILED,
        source_scope=_scope_for(route.intent),
        usage=_usage(route.run_id, started_at),
        error_code=AgentErrorCode.CONFIG_ERROR,
        error_message=unavailable_note(capability, language),
    )
