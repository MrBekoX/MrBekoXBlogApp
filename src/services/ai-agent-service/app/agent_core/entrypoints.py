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
  koşar; ``web_tools`` verilmediğinde model çağrısı yapmadan açık bir
  ``config_error`` sonucu döner.
- ``resume``: duraklatılmış çalışmayı checkpoint'ten yükleyip sürdürür;
  route kararını checkpoint'ten okur, yeniden model çağrısıyla hesaplamaz.
  A8: checkpoint zarf sözleşmeleri (şema sürümü, run ve kararlı yürütme
  kimliği bağlaması) ``agent_core.checkpoint`` katmanıyla denetlenir;
  güncel bağlam verildiyse içerik revizyonu kapsam değerlendirmesi yapılır
  (``FULL_REUSE`` / ``EVIDENCE_STALE`` / ``NOT_RESUMABLE``) ve devam
  ettirilen çalışmada iptal ile deadline yeniden uygulanır.
  A9 (additive): resume girdisi iş birliği hazırlığı için cevap/düzenleme/
  doğrulanmış onay taşıyabilir (``ResumeRequest.collab_input`` +
  ``ResumeRequest.validated_result``).

A9 (additive): profil/proje/öneri niyetleri onaylı kayıtlardan deterministik
``guidance`` akışıyla, iş birliği niyeti ``collab`` durum makinesiyle
yürütülür; her ikisi de model çağrısı yapmaz. İş birliği ``needs_input``
adımlarında DURUR ve güncel ``PreparedRun`` (``collab_state`` dâhil) A8
checkpoint zincirine yazılır; başarı yalnız doğrulanmış backend sonucuyla
bildirilir — agent kayıt atmaz, e-posta göndermez.

Who am I (additive, K5): v2 run'larda (``context.is_profile_rag_run``)
``PROFILE`` niyeti pinlenmiş canonical profil üzerinde profil RAG runner'ına
(``agent_core.profile.run_profile_rag``) gider; ``profile_knowledge``
(``ProfileKnowledgeRepository``) bağlı değilse veya snapshot pinlenmemişse
``failed/config_error`` döner (AUTO ziyaretçi-kimliği netleştirmesi hariç:
korpus gerektirmez). v1 run'larda A9 ``run_guidance`` yolu aynen kalır.
Her terminal sonuç ``run_intent = route.intent`` ile işaretlenir; profil RAG
sonuçları pinlenmiş ``profile_snapshot``'ı taşır.

Dependencies are supplied through explicit ports; production composition uses
the configured remote model and persistent semantic index.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .analysis.models import AnalysisConfig
from .analysis.runner import run_article_analysis
from .budget.guard import BudgetGuard, CallResult, estimate_model_tokens
from .budget.policy import BudgetPolicy, Deadline
from .budget.store import PolicyBudgetStore
from .checkpoint.models import CheckpointKind, ResumeScope, new_execution_id
from .checkpoint.resume import (
    evaluate_resume,
    load_resume_payload,
    save_checkpoint,
    validate_execution_id,
)
from .collab.models import CollabResumeInput, CollaborationState
from .collab.runner import run_collaboration
from .errors import AgentErrorCode, PortError
from .guidance.models import ArticleCatalogEntry
from .guidance.runner import run_guidance
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
    RunIntent,
    RunStatus,
    SourceScope,
    UsageRecord,
    UtcDatetime,
    ValidatedActionResult,
    compute_content_hash,
    split_generation_delta,
)
from .ports import (
    BudgetStore,
    CheckpointStore,
    CancellationToken,
    ModelProvider,
    ModelResponse,
    ProgressSink,
)
from .ports.budget import BudgetKind
from .ports.model import ModelRequest
from .ports.profile import ProfileKnowledgeRepository
from .profile.detection import is_visitor_identity_route
from .profile.runner import run_profile_rag, visitor_identity_outcome
from .profile.detection import ProfileIdentity
from .qa.models import QaFlowConfig
from .qa.runner import run_article_qa
from .research.runner import run_deep_research
from .routing import is_multi_part_question, route_for_context
from .state.events import usage_record_from_events
from .web.tools import WebTools

__all__ = ["PreparedRun", "ResumeRequest", "execute_plan", "prepare_and_route", "resume"]

#: Hazırlık state'inin checkpoint kimliği; resume bunu ya da en yazılanı okur.
_PREPARED_CHECKPOINT_PREFIX = "prepared"


class PreparedRun(BusinessModel):
    """Hazırlık girişinin çıktısı: bağlam + bir kez hesaplanmış rota kararı.

    Checkpoint'e serileştirilir; ``resume`` bu değeri geri yükler.

    ``execution_id`` (A8): çalıştırma zincirinin KARARLI kimliğidir; hazırlıkta
    bir kez atanır (dış adaptör verebilir — ``prepare_and_route``), checkpoint
    zincirine bağlanır ve resume'da denetlenir. İstemci yetki kaynağı değildir.

    ``collab_state`` (A9, additive): iş birliği niyetinin checkpoint'te taşınan
    hazırlık state'i; ``None`` iş birliği dışındaki tüm çalışmalarda varsayılandır.
    """

    context: ExecutionContext
    route: RouteDecision
    prepared_at: UtcDatetime
    execution_id: str | None = None
    collab_state: CollaborationState | None = None


class ResumeRequest(BusinessModel):
    """Resume girişi; ``checkpoint_id`` verilmezse en son checkpoint kullanılır.

    A8 alanları (tümü seçime bağlı; A1 çağrıları değişmez):

    - ``execution_id``: beklenen kararlı yürütme kimliği; checkpoint başka bir
      yürütme zincirine bağlıysa anlaşılır ``validation_error`` döner.
    - ``deadline_seconds``: devam ettirilen çalışma için kalan süre sınırı;
      dolduğunda ``timeout`` terminali üretilir (süreç asılı kalmaz).
    - ``current_context``: güncel içerik bağlamı; verilirse revizyon kapsamı
      değerlendirilir (``evaluate_resume``) — içerik kaldırılmışsa/gerilemişse
      devam ``stale_snapshot`` ile reddedilir, revizyon ilerlemişse makale
      kanıtları yeniden kullanılmadan güncel bağlamla sürülür.

    A9 alanları (additive; iş birliği niyeti için):

    - ``collab_input``: eksik alan cevapları, öneri düzenlemesi veya
      doğrulanmış onay (``collab.CollabResumeInput``).
    - ``validated_result``: backend'in doğrulanmış kayıt kararı
      (``ValidatedActionResult``); onaylı devrede ZORUNLUDUR — sonucuz onay
      başarı varsaymaz, ``validation_error`` ile reddedilir.
    """

    run_id: Identifier
    checkpoint_id: str | None = None
    execution_id: str | None = None
    deadline_seconds: float | None = None
    current_context: ExecutionContext | None = None
    collab_input: CollabResumeInput | None = None
    validated_result: ValidatedActionResult | None = None


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


async def _publish_delta(progress: ProgressSink | None, run_id: str, chunk: str) -> None:
    """Parçalı üretim metnini ``GENERATION_DELTA`` olarak yayınlar; sink arızası akışı kesmez.

    Taşıyıcı üst sınırını aşan chunk bölünür (token-başına broker mesajı yok).
    """
    if progress is None:
        return
    for piece in split_generation_delta(chunk):
        try:
            await progress.publish(
                DomainProgress(
                    run_id=run_id,
                    kind=ProgressKind.GENERATION_DELTA,
                    message=piece,
                    occurred_at=_utcnow(),
                )
            )
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
    execution_id: str | None = None,
    profile_identity: ProfileIdentity | None = None,
) -> PreparedRun:
    """Hazırlık ve mod seçimi; rota kararı bir kez üretilir.

    Kesin durumlarda karar model çağrısız kuraldır; belirsiz durumlarda
    ``router_model`` verildiyse yapılandırılmış öneri istenir ve doğrulanmış
    politika profiline eşlenir (plan A5). ``router_model`` verilmediğinde
    belirsiz durumlar deterministik kuralıyla çözülür (geçiş davranışı).

    A8: ``execution_id`` verilmezse kararlı bir yürütme kimliği üretilir ve
    ``PreparedRun``'a bağlanır; checkpoint zinciri resume'da bu kimliğe
    karşı denetlenir. Verilen kimliğin biçimi doğrulanır (dış adaptörün
    doğrulama sözleşmesi — ``validate_execution_id``).

    Raises:
        PortError: ``cancelled`` — iptal sinyali; ``stale_snapshot`` — snapshot
            bağlamı doğrulanamadı; ``validation_error`` — yürütme kimliği biçimi
            geçersiz; ``provider_error``/``timeout`` — checkpoint yazımı arızası
            (yalnız checkpoint verildiğinde).
    """
    _check_cancel(cancel)
    verify_snapshot_binding(context)

    if execution_id is not None:
        resolved_execution_id = validate_execution_id(execution_id)
    else:
        resolved_execution_id = new_execution_id(context.run_id)

    await _publish(progress, context.run_id, ProgressKind.RUN_STARTED, "çalışma hazırlanıyor")
    if context.article_snapshot is not None:
        await _publish(
            progress, context.run_id, ProgressKind.ARTICLE_CONTEXT_READY,
            f"makale bağlamı doğrulandı: {context.article_id}",
        )

    route = await route_for_context(context, router_model=router_model, cancel=cancel, profile_identity=profile_identity)
    await _publish(
        progress, context.run_id, ProgressKind.MODE_SELECTED,
        f"mod seçildi: {route.selected_mode.value} ({route.brief_reason})",
    )

    prepared = PreparedRun(
        context=context, route=route, prepared_at=_utcnow(), execution_id=resolved_execution_id
    )
    if checkpoint is not None:
        # Sürümlü zarfla yazım (W5 bulgusu 3 notu): şema sürümü + run/yürütme
        # kimliği bağlamı CHECKPOINT ZARFINDA taşınır; ``load_resume_payload``'ın
        # zarf guard'ları üretim yazımlarında da devreye girer. Zarfsız (A1
        # dönemi ham PreparedRun JSON) checkpoint'ler okuma tarafında geriye
        # dönük uyumlulukla yüklenmeye devam eder. Checkpoint kimliği korunur
        # (``prepared:run``): resume ``load_latest`` sıralaması değişmez.
        await save_checkpoint(
            checkpoint,
            run_id=context.run_id,
            execution_id=resolved_execution_id,
            kind=CheckpointKind.PREPARED,
            payload=prepared.model_dump_json().encode("utf-8"),
            checkpoint_id=f"{_PREPARED_CHECKPOINT_PREFIX}:run",
        )
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


def _stamp_outcome(prepared: PreparedRun, outcome: AgentOutcome) -> AgentOutcome:
    """Terminal sonuca etkin niyeti (ve profil RAG'de pinlenmiş snapshot'ı) işler.

    ``run_intent`` routing'in çözdüğü niyettir (v2 terminal olaylarında taşınır).
    Profil RAG sonucunda snapshot runner tarafından zaten yazılır; burada yalnız
    eksikse pinlenmiş bağlamdan tamamlanır (citation'sız red/netleştirme dahil).
    """
    update: dict[str, object] = {"run_intent": prepared.route.intent}
    context = prepared.context
    if (
        prepared.route.intent is RunIntent.PROFILE
        and context.is_profile_rag_run
        and outcome.profile_snapshot is None
        and context.profile_snapshot is not None
    ):
        update["profile_snapshot"] = context.profile_snapshot
    return outcome.model_copy(update=update)


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
    web_tools: WebTools | None = None,
    profile_repository=None,
    project_repository=None,
    article_catalog: list[ArticleCatalogEntry] | None = None,
    checkpoint: CheckpointStore | None = None,
    collab_input: CollabResumeInput | None = None,
    validated_result: ValidatedActionResult | None = None,
    profile_knowledge: ProfileKnowledgeRepository | None = None,
    profile_retriever=None,
) -> AgentOutcome:
    """Hazırlanmış planı yürütür ve sonucu etkin niyetle işaretler.

    Yürütme ``_dispatch_plan``'dadır; bu sarmalayıcı her terminal sonuca
    ``run_intent`` (ve profil RAG'de ``profile_snapshot``) yazar.
    ``profile_knowledge`` (Who am I): v2 PROFILE niyetinin canonical profil
    deposu; v1 PROFILE yolu ``profile_repository`` ile A9 rehberliğinde kalır.
    """
    outcome = await _dispatch_plan(
        prepared,
        model=model,
        retriever=retriever,
        content=content,
        budget=budget,
        progress=progress,
        cancel=cancel,
        qa_config=qa_config,
        analysis_config=analysis_config,
        web_search=web_search,
        web_tools=web_tools,
        profile_repository=profile_repository,
        project_repository=project_repository,
        article_catalog=article_catalog,
        checkpoint=checkpoint,
        collab_input=collab_input,
        validated_result=validated_result,
        profile_knowledge=profile_knowledge,
        profile_retriever=profile_retriever,
    )
    return _stamp_outcome(prepared, outcome)


async def _dispatch_plan(
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
    web_tools: WebTools | None = None,
    profile_repository=None,
    project_repository=None,
    article_catalog: list[ArticleCatalogEntry] | None = None,
    checkpoint: CheckpointStore | None = None,
    collab_input: CollabResumeInput | None = None,
    validated_result: ValidatedActionResult | None = None,
    profile_knowledge: ProfileKnowledgeRepository | None = None,
    profile_retriever=None,
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
    - ``deep_research`` requires an article and configured web tools. Missing
      capability fails before a model call. Production supplies a factory that
      binds fresh tools to the research run's own guard and budget.
    - A9: ``profile``/``projects``/``content_suggestion`` niyetleri
      ``profile_repository``/``project_repository``/``article_catalog``
      onaylı kaynaklarıyla deterministik rehberlik akışında yürür; onaylı
      kaynak bağlı değilken dürüst ``config_error`` döner (kayıtsız model
      çağrısına düşülmez). ``collaboration`` niyeti ``checkpoint`` zorunlu
      durum makinesinde yürür: eksik detayda needs_input + checkpoint,
      öneri üretimi, düzenleme → yeni sürüm, onay yalnız doğrulanmış
      ``validated_result`` ile sonuçlanır — agent kayıt atmaz.

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

    # Who am I: AUTO ziyaretçi-kimliği belirsizliği korpus/model gerektirmez;
    # kısa, tamamlanmış netleştirme cevabı (needs_input değil; v1 ve v2).
    if is_visitor_identity_route(route):
        return visitor_identity_outcome(prepared.context, route)

    # Plan A5: eksik bağlam/kişisel bilgi tahminle tamamlanmaz.
    if route.needs_clarification:
        return _clarification_outcome(prepared, started_at)

    # Who am I (K5): v2 PROFILE niyeti pinlenmiş canonical profil üzerinde RAG
    # ile yürür. Makale snapshot'ı/seçili metin bu akışa girmez; web aracı
    # kurulmaz; generation_delta yayınlanmaz. v1 PROFILE aşağıdaki A9 yolunda.
    if route.intent is RunIntent.PROFILE and prepared.context.is_profile_rag_run:
        profile_result = await run_profile_rag(
            prepared.context,
            route,
            model=model,
            knowledge=profile_knowledge,
            retriever=profile_retriever,
            store=budget,
            progress=progress,
            cancel=cancel,
        )
        return profile_result.outcome

    # Plan A9 (additive): rehberlik niyetleri onaylı kayıtlardan deterministik
    # yürütülür; model çağrısı yapılmaz. Onaylı kaynak bağlı değilken akış
    # kayıtsız modele DÜŞMEZ — dürüst config_error terminali döner.
    if route.intent in (RunIntent.PROFILE, RunIntent.PROJECTS, RunIntent.CONTENT_SUGGESTION):
        guidance_result = await run_guidance(
            prepared.context,
            route,
            profile_repository=profile_repository,
            project_repository=project_repository,
            article_catalog=article_catalog,
            progress=progress,
            cancel=cancel,
        )
        return guidance_result.outcome

    # Plan A9 (additive): iş birliği hazırlığı durum makinesi. needs_input
    # adımlarında DURULUR ve güncel PreparedRun (collab_state dâhil) A8
    # checkpoint zincirine yazılır; onay yalnız doğrulanmış backend sonucuyla
    # işlenir — agent kayıt atmaz, e-posta göndermez.
    if route.intent is RunIntent.COLLABORATION:
        if checkpoint is None:
            # needs_input durumunun saklanması sözleşmenin parçasıdır; depo
            # olmadan akış durdurulamaz — anlaşılır config_error döner.
            return AgentOutcome(
                selected_mode=route.selected_mode,
                status=RunStatus.FAILED,
                source_scope=_scope_for(prepared),
                usage=_build_usage(prepared, started_at),
                error_code=AgentErrorCode.CONFIG_ERROR,
                error_message=(
                    "iş birliği hazırlığı checkpoint deposu olmadan yürütülemez: "
                    "needs_input durumunun saklanması (A8) zorunludur"
                ),
            )
        collab_state, collab_outcome = await run_collaboration(
            prepared.context,
            route,
            state=prepared.collab_state,
            collab_input=collab_input,
            validated_result=validated_result,
            progress=progress,
            cancel=cancel,
        )
        prepared.collab_state = collab_state
        execution_id = prepared.execution_id or new_execution_id(run_id)
        prepared.execution_id = execution_id
        await save_checkpoint(
            checkpoint,
            run_id=run_id,
            execution_id=execution_id,
            kind=CheckpointKind.PREPARED,
            payload=prepared.model_dump_json().encode("utf-8"),
            checkpoint_id=f"{_PREPARED_CHECKPOINT_PREFIX}:run",
        )
        return collab_outcome

    # Research requires actual article content and configured evidence tools.
    # Never substitute the legacy bare-prompt completion for missing capability.
    if route.selected_mode is AgentMode.DEEP_RESEARCH and (
        not _is_article_bound(prepared.context) or web_tools is None
    ):
        return _terminal_outcome(prepared, started_at, PortError(
            AgentErrorCode.CONFIG_ERROR,
            "Deep research requires an article and a configured web search provider",
            port="execute_plan",
        ))

    if route.selected_mode is AgentMode.DEEP_RESEARCH and (
        prepared.context.budget_profile.max_web_search_calls == 0
        or prepared.context.budget_profile.max_tool_calls == 0
    ):
        return _terminal_outcome(prepared, started_at, PortError(
            AgentErrorCode.BUDGET_EXHAUSTED,
            "The server budget does not permit external research tools",
            port="execute_plan",
        ))

    # Plan A7: article-centred research with run-scoped budgeted tools.
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

    policy = BudgetPolicy.from_budget_profile(prepared.context.budget_profile)
    guard = BudgetGuard(budget or PolicyBudgetStore(policy), policy, run_id)
    events = []
    try:
        request = await guard.prepare_model_request(_compose_prompt(prepared))

        async def on_delta(chunk: str) -> None:
            # Canlı parça: GENERATION_DELTA olarak akar; sink arızası üretimi kesmez.
            await _publish_delta(progress, run_id, chunk)

        async def generate(_attempt: int) -> CallResult:
            response = await model.stream_complete(request, cancel=cancel, on_delta=on_delta)
            return CallResult(value=response, usage=response.usage, request=request,
                              estimated=response.usage_estimated)

        guarded = await guard.guarded(action_id="general:generate", kind=BudgetKind.MODEL_CALL,
            call=generate, cancel=cancel, deadline=Deadline(policy.max_duration_seconds),
            token_estimate=estimate_model_tokens(request), events_sink=events)
        response = guarded.value
    except PortError as error:
        outcome = _terminal_outcome(prepared, started_at, error)
        return outcome.model_copy(update={"usage": usage_record_from_events(run_id, events,
            duration_seconds=max((_utcnow() - started_at).total_seconds(), 0.0))})

    usage = usage_record_from_events(run_id, events,
        duration_seconds=max((_utcnow() - started_at).total_seconds(), 0.0))
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


class _DeadlineBoundedModel:
    """Resume'da deadline'ı model çağrısı sınırına taşıyan ince sarmalayıcı (A8).

    Plan A2 ilkesinin devam ettirilen çalışmaya uygulanması: iptal ve deadline
    kontrolleri çağrı sınırlarına konur. Çağrı öncesi süre denetlenir; çağrı
    kalan süreyle yarıştırılır ve aşılırsa ``PortError(timeout)`` üretilir —
    süreç asılı kalmaz [PY-ASYNCIO#C2] (iç görev iptal edilir, istisna
    bastırılmaz).
    """

    def __init__(self, inner: ModelProvider, deadline: Deadline) -> None:
        self._inner = inner
        self._deadline = deadline

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        self._deadline.raise_if_exceeded()
        try:
            return await asyncio.wait_for(
                self._inner.complete(request, cancel=cancel),
                timeout=self._deadline.remaining(),
            )
        except asyncio.TimeoutError:
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"devam ettirilen çalışmanın süre sınırı doldu "
                f"({self._deadline.elapsed():.3f}s geçti, kalan yok)",
                port="resume",
            ) from None

    async def stream_complete(
        self,
        request: ModelRequest,
        *,
        cancel: CancellationToken | None = None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """``complete`` ile aynı deadline disiplini: kalan süreyle yarıştırılır."""
        self._deadline.raise_if_exceeded()
        try:
            return await asyncio.wait_for(
                self._inner.stream_complete(request, cancel=cancel, on_delta=on_delta),
                timeout=self._deadline.remaining(),
            )
        except asyncio.TimeoutError:
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"devam ettirilen çalışmanın süre sınırı doldu "
                f"({self._deadline.elapsed():.3f}s geçti, kalan yok)",
                port="resume",
            ) from None


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
    web_tools: WebTools | None = None,
    profile_repository=None,
    project_repository=None,
    article_catalog: list[ArticleCatalogEntry] | None = None,
    profile_knowledge: ProfileKnowledgeRepository | None = None,
    profile_retriever=None,
) -> AgentOutcome:
    """Duraklatılmış çalışmayı checkpoint'ten sürdürür; rota kararı yeniden hesaplanmaz.

    A8 davranışları:

    - Checkpoint zarfı denetlenir: bilinmeyen zarf şema sürümü, başka run ve
      uyuşmayan yürütme kimliği bağlaması ANLAŞILIR ``validation_error`` ile
      reddedilir. Zarfsız (A1 dönemi ham payload) checkpoint'ler geriye dönük
      uyumlulukla aynen yüklenir.
    - ``current_context`` verildiyse revizyon kapsamı değerlendirilir:
      ``NOT_RESUMABLE`` (içerik kaldırma/gerileme/başka makale) ``stale_snapshot``
      ile reddedilir; ``EVIDENCE_STALE`` çalışma GÜNCEL bağlamla sürdürülür —
      checkpoint'teki makaleye bağlı sonuçların yeniden kullanılmadığı ilerleme
      olayında bildirilir; ``FULL_REUSE`` checkpoint bağlamıyla sürer.
    - İptal ve deadline devam ettirilen çalışmada da uygulanır: iptal sinyali
      her koşulda geçirilir; ``deadline_seconds`` verildiyse model çağrıları
      kalan süreyle sınırlandırılır.

    Raises:
        PortError: ``not_found`` — run için checkpoint yok; ``validation_error``
            — payload bozuk, başka run'a/yürütülmeye ait, zarf veya state şema
            sürümü uyumsuz; ``stale_snapshot`` — revizyon kapsamı devamı
            engelliyor (kaldırma/gerileme). A9: iş birliği devamında
            ``validation_error`` — bilinmeyen alan, öneri olmayan yerde
            düzenleme/onay, proposal sürüm uyuşmazlığı veya sonucuz onay.
    """
    _check_cancel(cancel)
    started_at = _utcnow()

    _envelope, payload = await load_resume_payload(
        checkpoint,
        request.run_id,
        request.checkpoint_id,
        execution_id=request.execution_id,
    )

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
    if (
        request.execution_id is not None
        and prepared.execution_id is not None
        and prepared.execution_id != request.execution_id
    ):
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "yürütme kimliği bağlaması uyuşmuyor: "
            f"checkpoint={prepared.execution_id}, istenen={request.execution_id}",
            port="resume",
        )

    # A8: revizyon kapsamı — kaldırılan/gerileyen içerikte checkpoint'ten devam edilmez.
    scope_note = ""
    if request.current_context is not None:
        verify_snapshot_binding(request.current_context)
        evaluation = evaluate_resume(
            checkpoint_context=prepared.context, current_context=request.current_context
        )
        if evaluation.scope is ResumeScope.NOT_RESUMABLE:
            raise PortError(
                AgentErrorCode.STALE_SNAPSHOT,
                f"checkpoint'ten devam edilemez: {'; '.join(evaluation.reasons)}",
                port="resume",
            )
        if evaluation.scope is ResumeScope.EVIDENCE_STALE:
            prepared = prepared.model_copy(update={"context": request.current_context})
            scope_note = (
                "; kapsam: evidence_stale — tamamlanmış makale kanıtları/bulguları "
                "yeniden kullanılmaz, güncel revizyonla sürülüyor"
            )
        else:
            scope_note = "; kapsam: full_reuse"

    deadline = None
    if request.deadline_seconds is not None:
        try:
            deadline = Deadline(request.deadline_seconds)
        except ValueError as error:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"deadline_seconds geçersiz: {error}",
                port="resume",
            ) from error
        try:
            deadline.raise_if_exceeded()
        except PortError as error:
            return _terminal_outcome(prepared, started_at, error)
        model = _DeadlineBoundedModel(model, deadline)  # type: ignore[assignment]

    await _publish(
        progress, request.run_id, ProgressKind.RUN_RESUMED,
        f"çalışma checkpoint'ten sürdürüldü (mod: {prepared.route.selected_mode.value}"
        f"{scope_note})",
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
        profile_repository=profile_repository,
        project_repository=project_repository,
        article_catalog=article_catalog,
        checkpoint=checkpoint,
        collab_input=request.collab_input,
        validated_result=request.validated_result,
        profile_knowledge=profile_knowledge,
        profile_retriever=profile_retriever,
    )
