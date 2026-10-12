"""Agent çekirdeğinin üç uygulama girişi (plan A1, ``01-agent-gelistirme-plani.md:186``):

- ``prepare_and_route``: hazırlık/mod seçimi; router kararı burada bir kez
  hesaplanır — kesin durumlarda kurallar, belirsiz durumlarda verilen
  ``router_model``'den yapılandırılmış öneri (plan A5); kararı yeniden
  hesaplamaz.
- ``execute_plan``: hazırlanmış planı yürütür; kararı yeniden hesaplamaz.
  A5: makale bağlamlı analysis çalışması analysis alt akışını koşar; fast
  çalışma A4 QA akışını koşar ve yetersizlikte SINIRLI, KAYITLI bir
  fast → analysis yükseltmesi yapabilir; ``needs_clarification`` kararı
  tahminle değil ``needs_input`` terminaliyle döner; ``needs_web`` kararında
  web araçları bağlı değilse özelliğin kullanılamaz olduğu doğru durumla
  bildirilir.
  A7: makaleye bağlı deep_research çalışması ``web_tools`` (A6
  ``build_web_tools`` çıktısı) verildiğinde A7 derin araştırma graph'ını
  koşar; ``web_tools`` verilmediğinde A5 geçiş davranışı korunur (tek
  çağrı + web kullanılamazlık notu).
- ``resume``: duraklatılmış çalışmayı checkpoint'ten yükleyip sürdürür;
  route kararını checkpoint'ten okur, yeniden model çağrısıyla hesaplamaz.

Paket dış adaptör olmadan test girdisiyle çağrılabilir: tüm bağımlılıklar
portlardan gelir ve ``agent_core.adapters.test_doubles`` ile koşulur.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .analysis.models import AnalysisConfig
from .analysis.runner import run_article_analysis
from .errors import AgentErrorCode, PortError
from .models import (
    AgentMode,
    AgentOutcome,
    BusinessModel,
    DomainProgress,
    ExecutionContext,
    Identifier,
    ModeUpgradeRecord,
    ProgressKind,
    RouteDecision,
    RunStatus,
    SourceScope,
    UsageRecord,
    UtcDatetime,
    compute_content_hash,
)
from .ports import BudgetStore, CheckpointStore, CancellationToken, ModelProvider, ProgressSink
from .ports.budget import BudgetKind
from .ports.model import ModelRequest
from .qa.models import QaFlowConfig
from .qa.runner import run_article_qa
from .research.runner import run_deep_research
from .routing import is_multi_part_question, route_for_context

__all__ = ["PreparedRun", "ResumeRequest", "execute_plan", "prepare_and_route", "resume"]

#: Hazırlık state'inin checkpoint kimliği; resume bunu ya da en yazılanı okur.
_PREPARED_CHECKPOINT_PREFIX = "prepared"


class PreparedRun(BusinessModel):
    """Hazırlık girişinin çıktısı: bağlam + bir kez hesaplanmış rota kararı.

    Checkpoint'e serileştirilir; ``resume`` bu değeri geri yükler.
    """

    context: ExecutionContext
    route: RouteDecision
    prepared_at: UtcDatetime


class ResumeRequest(BusinessModel):
    """Resume girişi; ``checkpoint_id`` verilmezse en son checkpoint kullanılır."""

    run_id: Identifier
    checkpoint_id: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _publish(
    progress: ProgressSink | None, run_id: str, kind: ProgressKind, message: str
) -> None:
    """İlerleme yayınlar; sink arızası iş akışını başarısızlaştırmaz (port sözleşmesi)."""
    if progress is None:
        return
    event = DomainProgress(run_id=run_id, kind=kind, message=message, occurred_at=_utcnow())
    try:
        await progress.publish(event)
    except PortError:
        return


def _check_cancel(cancel: CancellationToken | None) -> None:
    if cancel is not None:
        cancel.raise_if_cancelled()


def verify_snapshot_binding(context: ExecutionContext) -> None:
    """Sunulan snapshot'ın hash bağlamını yeniden hesaplayarak doğrular (A0 §7.2).

    İçerik yoksa (yalnız referans taşıyan EC, K7 durumu) doğrulanacak bir şey
    yoktur ve geçerlidir.

    Raises:
        PortError: ``stale_snapshot`` — snapshot kendi hash'iyle veya
            ExecutionContext'in içerik referansıyla uyuşmuyor.
    """
    snapshot = context.article_snapshot
    if snapshot is None:
        return
    actual = compute_content_hash(snapshot.content)
    if snapshot.content_hash != actual:
        raise PortError(
            AgentErrorCode.STALE_SNAPSHOT,
            "makale snapshot'ı bozuk: content_hash alanı içeriğin SHA-256 özetiyle uyuşmuyor",
            port="prepare_and_route",
        )
    if context.article_content_hash != actual:
        raise PortError(
            AgentErrorCode.STALE_SNAPSHOT,
            "bayat bağlam: ExecutionContext.article_content_hash, sunulan snapshot içeriğinin "
            f"hash'iyle uyuşmuyor (beklenen {context.article_content_hash!s:.12}…, hesaplanan {actual[:12]}…)",
            port="prepare_and_route",
        )


async def prepare_and_route(
    context: ExecutionContext,
    *,
    router_model: ModelProvider | None = None,
    progress: ProgressSink | None = None,
    cancel: CancellationToken | None = None,
    checkpoint: CheckpointStore | None = None,
) -> PreparedRun:
    """Hazırlık ve mod seçimi; rota kararı bir kez üretilir.

    Kesin durumlarda karar model çağrısız kuraldır; belirsiz durumlarda
    ``router_model`` verildiyse yapılandırılmış öneri istenir ve doğrulanmış
    politika profiline eşlenir (plan A5). ``router_model`` verilmediğinde
    belirsiz durumlar deterministik kuralıyla çözülür (geçiş davranışı).

    Raises:
        PortError: ``cancelled`` — iptal sinyali; ``stale_snapshot`` — snapshot
            bağlamı doğrulanamadı; ``provider_error``/``timeout`` — checkpoint
            yazımı arızası (yalnız checkpoint verildiğinde).
    """
    _check_cancel(cancel)
    verify_snapshot_binding(context)

    await _publish(progress, context.run_id, ProgressKind.RUN_STARTED, "çalışma hazırlanıyor")
    if context.article_snapshot is not None:
        await _publish(
            progress, context.run_id, ProgressKind.ARTICLE_CONTEXT_READY,
            f"makale bağlamı doğrulandı: {context.article_id}",
        )

    route = await route_for_context(context, router_model=router_model, cancel=cancel)
    await _publish(
        progress, context.run_id, ProgressKind.MODE_SELECTED,
        f"mod seçildi: {route.selected_mode.value} ({route.brief_reason})",
    )

    prepared = PreparedRun(context=context, route=route, prepared_at=_utcnow())
    if checkpoint is not None:
        payload = prepared.model_dump_json().encode("utf-8")
        await checkpoint.save(context.run_id, f"{_PREPARED_CHECKPOINT_PREFIX}:run", payload)
    return prepared


def _compose_prompt(prepared: PreparedRun) -> ModelRequest:
    """Mod ve bağlama göre tek tamamlama isteği kurar; deterministiktir."""
    context = prepared.context
    mode = prepared.route.selected_mode

    if mode is AgentMode.DEEP_RESEARCH:
        system = "Sen makaleyi merkez alan kaynaklı derin araştırma raporları hazırlayan bir asistansın."
    elif mode is AgentMode.ANALYSIS:
        system = "Sen kod ve metin açıklamaları yapan bir asistansın; yalnız verilen bağlama dayanırsın."
    else:
        system = "Sen makale sorularını yanıtlayan bir asistansın; yalnız verilen bağlama dayanırsın."

    sections: list[str] = [f"Soru ({context.language}):\n{context.question}"]
    if context.article_snapshot is not None:
        snapshot = context.article_snapshot
        sections.append(f"Makale: {snapshot.title}\n\n{snapshot.content}")
    if context.selected_text is not None:
        sections.append(f"Seçili metin:\n{context.selected_text}")
    if context.conversation_history:
        transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in context.conversation_history)
        sections.append(f"Önceki konuşma:\n{transcript}")

    return ModelRequest(
        prompt="\n\n---\n\n".join(sections),
        system=system,
        metadata={"run_id": context.run_id, "mode": mode.value},
    )


def _build_usage(prepared: PreparedRun, started_at: datetime, *, model_usage=None) -> UsageRecord:
    now = _utcnow()
    return UsageRecord(
        run_id=prepared.context.run_id,
        model_calls=1 if model_usage is not None else 0,
        prompt_tokens=model_usage.prompt_tokens if model_usage else 0,
        completion_tokens=model_usage.completion_tokens if model_usage else 0,
        total_tokens=model_usage.total_tokens if model_usage else 0,
        duration_seconds=max((now - started_at).total_seconds(), 0.0),
        recorded_at=now,
    )


def _scope_for(prepared: PreparedRun) -> SourceScope:
    if prepared.route.needs_web:
        return SourceScope.ARTICLE_AND_WEB
    if prepared.route.source_scope is not None:
        return prepared.route.source_scope
    if prepared.context.article_snapshot is not None:
        return SourceScope.ARTICLE
    return SourceScope.GENERAL


def _is_article_bound(context: ExecutionContext) -> bool:
    """Bağlam bir makaleye mi bağlı? (snapshot veya yalnız referans — K7)."""
    return context.article_snapshot is not None or context.article_id is not None


#: Plan A5: web araçları A6'ya kadar bağlı değildir; ihtiyaç duyan çalışma
#: özelliğin kullanılamaz olduğunu doğru durumla bildirir.
_WEB_UNAVAILABLE_TR_WIRED = (
    "Not: bu çalışma güncel dış kanıt gerektiriyor; ancak web araştırma akışı bu "
    "sürümde henüz uygulanmadığı için dış kanıt toplanamadı. Sunulan içerik yalnızca "
    "makale bağlamına dayanır."
)
_WEB_UNAVAILABLE_TR_UNWIRED = (
    "Not: bu çalışma güncel dış kanıt gerektiriyor; ancak web araştırma araçları bu "
    "sürümde bağlı olmadığı için bu özellik kullanılamıyor. Sunulan içerik yalnızca "
    "makale bağlamına dayanır."
)
_WEB_UNAVAILABLE_EN_WIRED = (
    "Note: this request requires up-to-date external evidence, but the web research "
    "flow is not implemented in this release, so no external evidence was collected. "
    "The content below relies on the article context only."
)
_WEB_UNAVAILABLE_EN_UNWIRED = (
    "Note: this request requires up-to-date external evidence, but web research tools "
    "are not connected in this release, so this capability is unavailable. The content "
    "below relies on the article context only."
)


def _web_unavailability_note(language: str, *, wired: bool) -> str:
    if language.casefold().startswith("tr"):
        return _WEB_UNAVAILABLE_TR_WIRED if wired else _WEB_UNAVAILABLE_TR_UNWIRED
    return _WEB_UNAVAILABLE_EN_WIRED if wired else _WEB_UNAVAILABLE_EN_UNWIRED


def _clarification_outcome(prepared: PreparedRun, started_at: datetime) -> AgentOutcome:
    """``needs_clarification`` kararı için ``needs_input`` terminali.

    Eksik bağlam/kişisel bilgi tahminle tamamlanmaz; model çağrısı yapılmaz,
    kullanıcıya açık soru döner (plan A5).
    """
    question = prepared.route.clarification_question or ""
    return AgentOutcome(
        selected_mode=prepared.route.selected_mode,
        status=RunStatus.NEEDS_INPUT,
        source_scope=_scope_for(prepared),
        unresolved_questions=[question] if question else [],
        usage=_build_usage(prepared, started_at),
    )


def _terminal_outcome(
    prepared: PreparedRun, started_at: datetime, error: PortError
) -> AgentOutcome:
    """Port hatasını terminal AgentOutcome'a çevirir (plan durumları)."""
    cancelled = error.code is AgentErrorCode.CANCELLED
    usage = _build_usage(prepared, started_at)
    return AgentOutcome(
        selected_mode=prepared.route.selected_mode,
        status=RunStatus.CANCELLED if cancelled else RunStatus.FAILED,
        source_scope=_scope_for(prepared),
        usage=usage,
        error_code=None if cancelled else error.code,
        error_message=error.message,
    )


async def execute_plan(
    prepared: PreparedRun,
    *,
    model: ModelProvider,
    retriever=None,
    content=None,
    budget: BudgetStore | None = None,
    progress: ProgressSink | None = None,
    cancel: CancellationToken | None = None,
    qa_config: QaFlowConfig | None = None,
    analysis_config: AnalysisConfig | None = None,
    web_search=None,
    web_tools: dict[str, object] | None = None,
) -> AgentOutcome:
    """Hazırlanmış planı yürütür; rota kararını yeniden hesaplamaz.

    Makaleye bağlı çalışmalarda (``retriever`` verildiğinde):

    - ``analysis`` modu A5 analysis alt akışını koşar: soru cevap başlıklarına
      ayrılır, başlık başına arama + sınırlı kapsam artırma + kanıt kontrolü
      yapılır, açıklama makale örnekleriyle üretilir ve atıflarla
      ilişkilendirilir (plan A5).
    - ``fast`` modu A4 QA akışını koşar; yetersizlik ve çok bölümlü soru
      durumunda TEK KEZ analysis alt akışına yükselir — yükseltme
      ``AgentOutcome.mode_upgrades`` ile kayıtlıdır (plan A5: "Mod
      yükseltmesini sınırlı ve kayıtlı yap").
    - ``needs_clarification`` kararında model çağrısı yapılmaz; açık soruyla
      ``needs_input`` terminali döner: eksik kişisel bilgi tahminle
      tamamlanmaz (plan A5).
    - ``deep_research`` A7 derin araştırma graph'ını koşar: koşul — makaleye
      bağlı bağlam ve ``web_tools`` (A6 ``build_web_tools`` çıktısı)
      verilmiş olması. ``web_tools`` verilmediğinde A5 geçiş davranışı
      korunur: tek model çağrısı + web kullanılamazlık notu (makaleye bağlı
      olmayan derin araştırma bu fazın kapsamı değildir).

    ``content`` (``ContentRepository``) yalnız referans taşıyan bağlamların
    (K7) içerik getirmesi içindir. ``web_search`` portu graph tarafından
    doğrudan çağrılmaz; yalnız bağlantı durumunun doğru bildirilmesi için
    kabul edilir — gerçek web erişimi ``web_tools`` kümesiyladır.

    GEÇİŞ DAVRANIŞI (B4 kapanacak): ``retriever`` verilmediğinde makale
    bağlamlı çalışma A1 tek-çağrı yolunda kalır. Bu, kanıtsız makale cevabı
    riskini taşır; worker wiring'i (B4) ``retriever``'ı zorunlu kılınca
    kaldırılacak ve ekseni ``config_error`` terminaline dönecektir
    (A4-rapor.md F1; A5 dispatch'i dosya sahipliği gereği bu geçişi kapatmaz).

    Raises:
        PortError: yalnız beklenmedik (terminal olmayan) arızalarda; plan
            kapsamındaki hatalar terminal ``AgentOutcome``'a çevrilir.
    """
    started_at = _utcnow()
    run_id = prepared.context.run_id
    try:
        _check_cancel(cancel)
    except PortError as error:
        return _terminal_outcome(prepared, started_at, error)

    route = prepared.route

    # Plan A5: eksik bağlam/kişisel bilgi tahminle tamamlanmaz.
    if route.needs_clarification:
        return _clarification_outcome(prepared, started_at)

    # Plan A7: makale merkezli derin araştırma graph'ı (web araç kümesi bağlıysa).
    if (
        route.selected_mode is AgentMode.DEEP_RESEARCH
        and _is_article_bound(prepared.context)
        and web_tools is not None
    ):
        research_result = await run_deep_research(
            prepared.context,
            route,
            model=model,
            web_tools=web_tools,
            content=content,
            store=budget,
            cancel=cancel,
            progress=progress,
        )
        return research_result.outcome

    if (
        _is_article_bound(prepared.context)
        and route.selected_mode is not AgentMode.DEEP_RESEARCH
        and retriever is not None
    ):
        if route.selected_mode is AgentMode.ANALYSIS:
            analysis_result = await run_article_analysis(
                prepared.context,
                route,
                model=model,
                retriever=retriever,
                content=content,
                config=analysis_config,
                store=budget,
                cancel=cancel,
                progress=progress,
            )
            return analysis_result.outcome

        result = await run_article_qa(
            prepared.context,
            route,
            model=model,
            retriever=retriever,
            content=content,
            config=qa_config,
            store=budget,
            cancel=cancel,
            progress=progress,
        )
        verdict = result.state.get("sufficiency")
        fast_insufficient = verdict is not None and not verdict.sufficient
        if fast_insufficient and is_multi_part_question(prepared.context.question):
            upgrade = ModeUpgradeRecord(
                from_mode=AgentMode.FAST,
                to_mode=AgentMode.ANALYSIS,
                reason=(
                    "fast tek bölüm araması çok bölümlü soruyu karşılamadı; "
                    "analysis alt akışı çalıştırıldı (sınırlı yükseltme: çalışma başına bir)"
                ),
                upgraded_at=_utcnow(),
            )
            await _publish(
                progress, run_id, ProgressKind.MODE_SELECTED,
                f"mod yükseltmesi: fast → analysis ({upgrade.reason})",
            )
            # Alt akış, fiilen çalışan modu taşır: terminal sonuç analysis moduyla etiketlenir.
            upgraded_route = route.model_copy(
                update={
                    "selected_mode": AgentMode.ANALYSIS,
                    "brief_reason": f"{route.brief_reason}; mod yükseltmesi: analysis",
                }
            )
            analysis_result = await run_article_analysis(
                prepared.context,
                upgraded_route,
                model=model,
                retriever=retriever,
                content=content,
                config=analysis_config,
                store=budget,
                mode_upgrade=upgrade,
                cancel=cancel,
                progress=progress,
            )
            return analysis_result.outcome
        return result.outcome

    await _publish(progress, run_id, ProgressKind.GENERATION_STARTED, "yanıt üretiliyor")

    reservation = None
    try:
        if budget is not None:
            reservation = await budget.reserve(run_id, BudgetKind.MODEL_CALL, 1)
        response = await model.complete(_compose_prompt(prepared), cancel=cancel)
        if budget is not None and reservation is not None:
            await budget.commit(reservation, max(response.usage.total_tokens, 1))
    except PortError as error:
        if budget is not None and reservation is not None:
            await budget.release(reservation)
        return _terminal_outcome(prepared, started_at, error)

    usage = _build_usage(prepared, started_at, model_usage=response.usage)
    await _publish(
        progress, run_id, ProgressKind.GENERATION_COMPLETED,
        f"yanıt üretildi ({usage.total_tokens} token)",
    )

    deep = route.selected_mode is AgentMode.DEEP_RESEARCH
    report = response.text if deep else None
    if deep and route.needs_web:
        report = (
            f"{response.text}\n\n"
            f"{_web_unavailability_note(prepared.context.language, wired=web_search is not None)}"
        )
    return AgentOutcome(
        selected_mode=route.selected_mode,
        status=RunStatus.COMPLETED,
        report=report,
        answer=None if deep else response.text,
        source_scope=_scope_for(prepared),
        usage=usage,
    )


async def resume(
    request: ResumeRequest,
    *,
    checkpoint: CheckpointStore,
    model: ModelProvider,
    retriever=None,
    content=None,
    budget: BudgetStore | None = None,
    progress: ProgressSink | None = None,
    cancel: CancellationToken | None = None,
    web_search=None,
    web_tools: dict[str, object] | None = None,
) -> AgentOutcome:
    """Duraklatılmış çalışmayı checkpoint'ten sürdürür; rota kararı yeniden hesaplanmaz.

    Raises:
        PortError: ``not_found`` — run için checkpoint yok; ``validation_error``
            — checkpoint payload'ı bozuk veya başka run'a ait.
    """
    _check_cancel(cancel)

    if request.checkpoint_id is not None:
        payload = await checkpoint.load(request.run_id, request.checkpoint_id)
    else:
        _, payload = await checkpoint.load_latest(request.run_id)

    try:
        prepared = PreparedRun.model_validate_json(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"checkpoint payload'ı çözümlenemedi: {error}",
            port="resume",
        ) from error
    if prepared.context.run_id != request.run_id:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "checkpoint payload'ı istenen run'a ait değil",
            port="resume",
        )

    await _publish(
        progress, request.run_id, ProgressKind.RUN_RESUMED,
        f"çalışma checkpoint'ten sürdürüldü (mod: {prepared.route.selected_mode.value})",
    )
    return await execute_plan(
        prepared,
        model=model,
        retriever=retriever,
        content=content,
        budget=budget,
        progress=progress,
        cancel=cancel,
        web_search=web_search,
        web_tools=web_tools,
    )
