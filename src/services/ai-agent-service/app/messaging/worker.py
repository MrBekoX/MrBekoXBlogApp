"""Yürütme worker'ı (B6): kalıcı işi claim eder, agent çekirdeğini çalıştırır.

Sorumluluk dağılımı (plan B6 — 02-rabbitmq-haberlesme-plani.md:374-400):

- **Kabul ≠ yürütme:** B4 intake işi kalıcı kabul etti ve ACK verdi; bu
  worker yürütümü ``agent.jobs`` üzerinden DEVRALIR. Broker ACK'ı ile graph
  tamamlanması ayrı sorumluluklardır — yürütme hatası broker requeue ile
  DEĞİL, kalıcı job retry/recovery politikasıyla ele alınır (plan B6:396).
- **Lease/fencing:** claim ``FOR UPDATE SKIP LOCKED`` + ``lease_owner``/
  ``lease_until`` + ``execution_attempt``/``fencing_token`` (``job_store``).
  Eski denemenin sonucu fencing guard'ıyla ezilemez; worker lease'ini
  kaybederse yürütmesini BIRAKIR ve terminal YAZMAZ (yeni sahibin yolu
  açık kalır).
- **İptal terminali (ortak sözleşmenin worker yarısı):** complete/fail
  'cancel_requested' ile reddedilirse worker bağlı ``ControlStore``
  üzerinden ``mark_cancelled_if_running`` çağırır — terminal 'cancelled'
  deadline reaper'ı beklemeden üretilir (W5 bulgusu 1b).
- **Stale komut guard'ı (B8):** komut makale üçlüsü taşıyorsa ve projection
  (``ExecutionDependencies.content_state``) bu makalenin daha yeni bir
  kaldırma revizyonu biliyorsa yürütme ``stale_snapshot`` ile anlaşılır
  terminalde kapanır (plan B8: "eski komutu yürütmesin").
- **Lease yenilemesi graph ilerlemesine bağlıdır:** çekirdek her ilerleme
  sinyalinde heartbeat üretir; ayrıca arka plan yenileme döngüsü güvenlik
  ağıdır. Yenileme reddedilirse (fencing eşleşmez) iptal sinyaliyle
  yürütme kesilir [PY-ASYNCIO#C2: istisna bastırılmaz, cleanup yapılır].
- **Recovery:** lease'i bitmiş iş, deneme sınırı dahilinde yeniden claim
  edilir (SINIRLI recovery); sınırı aşan işler kalıcı kapatılır. Yeniden
  claim'de A8 checkpoint'i varsa iş ``resume`` girişiyle DEVAM ETTİRİLİR:
  rota kararı checkpoint'ten okunur, yeniden model çağrısıyla hesaplanmaz.
- **Checkpoint zinciri:** ``execution_id`` run başına KARARLIDIR
  (``job-{run_id}``); ilk yürütme ve tüm devam ettirmeler aynı kimliğe
  bağlanır (A8 sözleşmesi). Depo ``FileCheckpointStore`` (A8 dev deposu)
  veya enjekte edilmiş ``CheckpointStore``'dur.
- **Kapasite ayrımı:** ``queue_class`` fast|research (migration 0003).
  Router kararı agent çekirdeğinde üretilir; ``deep_research`` çıkan iş
  research kapasitesine ERTELENİR (backend yeniden sınıflandırmaz — plan
  B4 kuralının B6 karşılığı). Hızlı worker'ların kuyruğu uzun araştırma
  işleriyle tıkanmaz.
- **Deadline/bütçe sıfırlanmaz:** ``deadline_at`` iş kaydındadır; recovery
  aynı deadline'ın KALANINDA çalışır. BudgetStore enjekte edilirse aynı
  run_id ile paylaşılır — rezervasyonlar denemeler arasında korunur.
- **Belirsiz maliyet:** kesilen denemelerin dış model çağrı maliyeti
  doğrulanamaz; sonuç kaydına A2'nin belirsiz kullanım işaretiyle
  (``uncertain=True``) yakınır yazılır.
- **Konuşma geçmişi:** ``conversation_history`` backend snapshot'ından
  (execute payload) aynen alınır; worker onayla değiştirmez.
- **Wire sürümü (K4):** claim edilen işin ``wire_version``'ı (migration 0005)
  payload'ın hangi DTO ile yeniden doğrulanacağını (v1/v2) ve worker'ın ürettiği
  her olayın (mode_selected, progress, needs_input, terminal, failed) sürümünü
  belirler. v2 run'ında ``ExecutionContext.conversation_topic``/``profile_snapshot``
  dolar; v1 run'ında konu yoktur (legacy A9 profil yolu).
- **Who am I sınırları (K5, savunma derinliği):** etkin niyet PROFILE olduğunda
  (açık who_am_i konusu veya AUTO→PROFILE) sink ``generation_delta``'yı HİÇ
  yayınlamaz, ilerleme mesajı sabit durum metnine indirgenir ve detail yalnız
  sayaç taşır; web araç kümesi çekirdeğe hiç verilmez (port düzeyi kapatma —
  ``max_web_search_calls=0`` tek başına yetmez). Terminal sonuç kaynak denetimi:
  profil kapsamı yalnız pinlenmiş snapshot'a ait profile kaynağı taşır;
  who_am_i isteği PROFILE dışı niyetle sonuçlanamaz; ihlal ``validation_error``.

Kaynaklar: [LG-PERSISTENCE#C2] kalıcı checkpointer, süreç restart'ında
checkpoint korunur; [PY-ASYNCIO#C2] iptal istisnası bastırılmaz;
[PG-ISOLATION#C2] Read Committed'ta koşullu UPDATE güncel satırda
değerlendirilir (fencing guard'ının dayanağı).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent_core.checkpoint.resume import load_resume_payload
from agent_core.checkpoint.store import FileCheckpointStore
from agent_core.budget.embedding import embedding_budget_scope
from agent_core.collab.models import CollabStage
from agent_core.collab.runner import reconcile_resolved_collaboration
from agent_core.telemetry import set_span_attributes, trace_operation
from agent_core.web.tools import WebTools
from agent_core.entrypoints import (
    PreparedRun,
    ResumeRequest,
    execute_plan,
    prepare_and_route,
    resume,
)
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import (
    AgentMode,
    AgentOutcome,
    BudgetProfile,
    ConversationTopic,
    ConversationTurn,
    ExecutionContext,
    ModePreference,
    ProfileSnapshotRef,
    ProgressKind,
    RunIntent,
    RunStatus,
    SourceReference,
    SourceScope,
)
from agent_core.ports import (
    BudgetStore,
    CancellationToken,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProgressSink,
)
from agent_core.ports.checkpoint import CheckpointStore as CheckpointStorePort

from pydantic import ValidationError

from .contracts import (
    WIRE_VERSION_V2,
    AgentContractError,
    AgentEnvelope,
    AgentExecutionRequestedV2,
    spec_for,
)
from .contracts.payloads import (
    AgentActionProposalContent,
    AgentExecutionRequestedV1,
    AgentSourceReference,
    AgentUsageRecord,
)
from .contracts.payloads_v2 import AgentSourceReferenceV2
from .content import StaleExecutionRejected
from .control_store import ControlStore
from .events import (
    AgentEventPublisher,
    AgentOutcome as TransportAgentOutcome,
    EventPublishError,
    ThrottledProgress,
)
from .job_store import (
    QUEUE_CLASS_FAST,
    QUEUE_CLASS_RESEARCH,
    ClaimedJob,
    JobStore,
)
from .wire import (
    WireVersionMismatch,
    compose_run_envelope,
    to_transport_citation,
    to_transport_profile_snapshot,
    versioned_payload,
)
from agent_core.profile.detection import ProfileIdentity

__all__ = [
    "ExecutionWorker",
    "WorkerSettings",
    "ExecutionDependencies",
    "CycleResult",
    "WORKER_ERROR_CODE",
]

logger = logging.getLogger(__name__)

#: Recovery sınırını aşan işlerin kapatma kodu (fail_expired_jobs_beyond_attempts).
WORKER_ERROR_CODE = "provider_error"


class WorkerAborted(Exception):
    """Yürütmenin terminal'siz bırakıldığı iç sinyal (lease kaybı / iptal niyeti)."""


@dataclass(frozen=True)
class WorkerSettings:
    """Worker davranış ayarları; testler kısa lease ile hızlı senaryo kurar."""

    #: ``agent.jobs.lease_owner``; süreç/yürütücü başına benzersiz.
    worker_id: str
    #: Bu worker'ın çektiği kapasite sınıfları (fast|research).
    queue_classes: tuple[str, ...] = (QUEUE_CLASS_FAST,)
    lease_seconds: float = 60.0
    poll_interval_seconds: float = 0.5
    #: SINIRLI recovery: en fazla bu kadar yürütme denemesi (ilk yürütme dahil).
    max_execution_attempts: int = 3
    #: None → lease/3. Yenileme aralığı lease süresinin üçte birini aşmamalı.
    renew_interval_seconds: float | None = None
    #: Payload'ın ``budget_profile`` çözümlenemediğinde kullanılan profil.
    budget_profile: BudgetProfile | None = None
    #: A8 checkpoint deposu kökü (None → ``FileCheckpointStore`` varsayılanı).
    checkpoint_base_dir: str | None = None

    @property
    def renew_interval(self) -> float:
        if self.renew_interval_seconds is not None:
            return self.renew_interval_seconds
        return max(self.lease_seconds / 3.0, 0.05)


@dataclass
class ExecutionDependencies:
    """Agent çekirdeğinin port bağları; worker transport dönüşümü yapar.

    ``model`` zorunludur (üretimde yapılandırılmış sağlayıcı; testlerde test
    double). ``retriever``/``content``/``web_tools`` A3/A6 gerçekleştirimleri
    bağlanınca geçerlidir; verilmediğinde çekirdeğin geçiş davranışı işler.
    ``content_state`` B8 güncellik projection'udur (``ContentSyncState``);
    bağlandığında yürütme öncesi stale komut denetimi devreye girer
    (``ensure_execution_allowed`` — plan B8: "eski komutu yürütmesin").
    ``profile_repository``/``project_repository``/``article_catalog`` A9
    rehberlik kaynaklarıdır (W6 F3): taze yürütmede ve checkpoint devamında
    çekirdeğe AYNEN aktarılır; bağlı değilken çekirdek dürüst
    ``config_error`` döner (kayıtsız modele düşmez). ``profile_repository``
    legacy A9 (v1 PROFILE) yoludur ve geçiş için açık kalır.
    ``profile_knowledge`` (Who am I, K5): canonical profil deposu
    (``ProfileKnowledgeRepository`` — ``active_snapshot()``/``load(snapshot)``);
    v2 PROFILE niyeti yalnız pinlenmiş sürüme karşı bununla yürür. Bağlı
    değilken çekirdek ``config_error`` üretir (kaynaksız model cevabı yok).
    """

    model: ModelProvider
    router_model: ModelProvider | None = None
    retriever: Any | None = None
    content: Any | None = None
    budget: BudgetStore | None = None
    web_tools: WebTools | None = None
    checkpoint_store: CheckpointStorePort | None = None
    checkpoint_factory: Callable[[CheckpointStorePort, str, int], CheckpointStorePort] | None = None
    content_state: Any | None = None
    profile_repository: Any | None = None
    project_repository: Any | None = None
    article_catalog: Any | None = None
    profile_knowledge: Any | None = None
    profile_retriever: Any | None = None
    budget_factory: Callable[[ExecutionContext, int], BudgetStore] | None = None


@dataclass(frozen=True)
class CycleResult:
    """Tek ``run_once`` çevriminin sonucu (gözlenebilirlik/test iddiaları)."""

    idle: bool = False
    run_id: str | None = None
    action: str = ""  # completed|failed|needs_input|deferred|aborted_lease_lost|aborted_cancel|error_transient
    detail: str = ""
    execution_attempt: int = 0
    fencing_token: int = 0
    recovered: bool = False


def stable_execution_id(run_id: str) -> str:
    """Run'a bağlı KARARLI yürütme kimliği; checkpoint zinciri buna bağlanır."""

    return f"job-{run_id}"


class _WorkerCancel:
    """Worker yönetimli ``CancellationToken``: lease kaybı/iptal niyeti sinyali."""

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None

    def cancel(self, reason: str) -> None:
        self._cancelled = True
        self._reason = reason

    @property
    def lost(self) -> bool:
        return self._cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def reason(self) -> str | None:
        return self._reason

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise PortError(
                AgentErrorCode.CANCELLED,
                self._reason or "yürütme worker tarafından kesildi",
                port="worker",
            )


class _LeaseWatch:
    """Lease yenileme: arka plan döngüsü + graph ilerlemesine bağlı heartbeat."""

    def __init__(self, store: JobStore, run_id: str, fencing_token: int, settings: WorkerSettings) -> None:
        self._store = store
        self._run_id = run_id
        self._fencing_token = fencing_token
        self._settings = settings
        self._interval = settings.renew_interval
        self._last_renew = 0.0
        self.lost = False
        self._task: asyncio.Task[None] | None = None
        self._cancel: _WorkerCancel | None = None

    def start(self, cancel: _WorkerCancel) -> None:
        self._cancel = cancel
        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        try:
            while not self.lost:
                await asyncio.sleep(self._interval)
                await self.renew()
        except asyncio.CancelledError:
            raise  # bastırılmaz [PY-ASYNCIO#C2]

    async def renew(self) -> bool:
        self._last_renew = time.monotonic()
        renewed = await self._store.renew_lease(
            self._run_id, self._fencing_token, self._settings.lease_seconds
        )
        if not renewed:
            self.lost = True
            if self._cancel is not None:
                self._cancel.cancel(
                    "iş lease'i kaybedildi: iş başka bir denemece yeniden sahiplenildi"
                )
        return renewed

    async def heartbeat(self) -> None:
        """Graph ilerlemesi: yarı aralıktan uzun geçtiyse lease'i yenile."""

        if self.lost or (time.monotonic() - self._last_renew) < (self._interval / 2):
            return
        await self.renew()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


class _MeteredModel:
    """Model çağrılarını sayar; kesintide belirsiz maliyet işaretinin kaynağı.

    Sayım SÜREÇ BELLEĞİNDEDİR: worker kesilirse önceki denemelerin çağrı
    sayısı/token harcaması yeni süreççe bilinemez — bu yüzden recovery
    sonucu önceki denemeleri ``uncertain`` olarak işaretler (A2 BudgetGuard
    belirsiz kullanım işaretinin worker karşılığı).
    """

    def __init__(self, inner: ModelProvider) -> None:
        self._inner = inner
        self.calls = 0
        self.total_tokens = 0

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        response = await self._inner.complete(request, cancel=cancel)
        self.calls += 1
        self.total_tokens += response.usage.total_tokens
        return response

    async def stream_complete(
        self,
        request: ModelRequest,
        *,
        cancel: CancellationToken | None = None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        """``complete`` ile aynı sayım disiplini: akış çağrısı da bir model çağrısıdır."""
        response = await self._inner.stream_complete(request, cancel=cancel, on_delta=on_delta)
        self.calls += 1
        self.total_tokens += response.usage.total_tokens
        return response


#: Profil (Who am I) run'larında ilerleme mesajının yerine geçen sabit durum
#: metinleri: ara olaylar chunk, taslak veya biyografi cevabı TAŞIMAZ (K5).
_PROFILE_PROGRESS_TEXT: dict[str, str] = {
    ProgressKind.RUN_STARTED.value: "Çalışma başladı",
    ProgressKind.MODE_SELECTED.value: "Profil sorusu olarak yönlendirildi",
    ProgressKind.RUN_RESUMED.value: "Çalışma sürdürülüyor",
    ProgressKind.RETRIEVAL_STARTED.value: "Profil kaynakları aranıyor",
    ProgressKind.RETRIEVAL_COMPLETED.value: "Profil kaynakları bulundu",
    ProgressKind.GENERATION_STARTED.value: "Yanıt hazırlanıyor",
    ProgressKind.GENERATION_COMPLETED.value: "Yanıt hazırlandı",
    ProgressKind.VALIDATION_COMPLETED.value: "Yanıt kaynaklarla denetlendi",
    ProgressKind.TOOL_ERROR.value: "Bir adım tamamlanamadı",
}
_PROFILE_PROGRESS_DEFAULT = "Profil yanıtı hazırlanıyor"
#: Profil run'ında detail yalnız sayaç (negatif olmayan tam sayı metni) taşır.
_COUNTER_VALUE = re.compile(r"^[0-9]{1,9}$")


class _WorkerProgressSink(ProgressSink):
    """DomainProgress → B5 olay yayıncısı + lease heartbeat.

    ``profile_guard`` (Who am I savunma derinliği, K5): açıkken
    ``GENERATION_DELTA`` HİÇ yayınlanmaz (doğrulanmamış cevap token'ı sızmaz),
    ilerleme mesajı sabit durum metnine indirgenir, detail yalnız sayaç taşır
    ve içerik önerisi olayı düşürülür. Koruma çekirdeğin doğru davranmasına
    BAĞLI DEĞİLDİR; açık who_am_i konusunda baştan, AUTO→PROFILE'da rota
    kararından hemen sonra açılır ve bir daha kapanmaz.
    """

    def __init__(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        causation_id: str,
        execution_attempt: int,
        publisher: AgentEventPublisher | None,
        watch: _LeaseWatch,
        profile_guard: bool = False,
    ) -> None:
        self._ids = (run_id, conversation_id, correlation_id, causation_id)
        self._attempt = execution_attempt
        self._publisher = publisher
        self._watch = watch
        self._profile_guard = profile_guard
        #: Gözlem/test: profil korumasıyla düşürülen delta olayı sayısı.
        self.dropped_deltas = 0

    @property
    def profile_guard(self) -> bool:
        return self._profile_guard

    def enable_profile_guard(self) -> None:
        """Profil korumasını açar (tek yönlü; run boyunca kapanmaz)."""

        self._profile_guard = True

    async def publish(self, event: Any) -> None:
        await self._watch.heartbeat()  # lease ilerlemeye bağlı (plan B6)
        kind = event.kind if isinstance(event.kind, str) else event.kind.value
        if self._profile_guard:
            if kind == ProgressKind.GENERATION_DELTA.value:
                self.dropped_deltas += 1  # biyografi cevabı ara olayla yayınlanmaz
                return
            if kind == ProgressKind.ACTION_PROPOSED.value:
                logger.warning("profil run'ında içerik önerisi olayı düşürüldü: run=%s", self._ids[0])
                return
        if self._publisher is None:
            return
        run_id, conversation_id, correlation_id, causation_id = self._ids
        # W6 F1: A9 öneri olayı sözleşmedeki agent.action.proposed'a çevrilir.
        # Bu olay B9 proposal kaydının (backend agent_proposals) TEK kaynağıdır;
        # agent.run.progressed'e düşürülseydi hat tüketicide işlenmezdi (ölü yol).
        # Sink sözleşme köprüsüdür: domain ActionProposal → B1 transport modeli.
        proposal = getattr(event, "proposal", None)
        if kind == ProgressKind.ACTION_PROPOSED.value and proposal is not None:
            await self._publisher.publish_action_proposed(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                proposal=AgentActionProposalContent(
                    run_id=str(proposal.run_id),
                    proposal_id=str(proposal.proposal_id),
                    article_id=str(proposal.article_id),
                    article_revision=int(proposal.article_revision),
                    base_content_hash=str(proposal.base_content_hash),
                    summary=str(proposal.summary),
                    proposed_content=str(proposal.proposed_content),
                    created_at=_utc(proposal.created_at),
                ),
                execution_attempt=self._attempt,
                causation_id=causation_id,
                occurred_at=event.occurred_at,
            )
            return
        # Streaming sözleşmesi: parçalı üretim metni ÖZEL yoldan akar —
        # seyrekleştirilmez (token akışının yutulması yanlış olur) ve
        # publish_generation_delta 1500 üst sınırını kendisi böler.
        if kind == ProgressKind.GENERATION_DELTA.value:
            await self._publisher.publish_generation_delta(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                text=event.message,
                execution_attempt=self._attempt,
                causation_id=causation_id,
                occurred_at=event.occurred_at,
            )
            return
        message = event.message
        detail = event.detail
        if self._profile_guard:
            message = _PROFILE_PROGRESS_TEXT.get(kind, _PROFILE_PROGRESS_DEFAULT)
            detail = {
                key: value
                for key, value in (detail or {}).items()
                if isinstance(value, str) and _COUNTER_VALUE.match(value)
            }
        result = await self._publisher.publish_progress(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            kind=kind,
            message=message,
            detail=detail,
            execution_attempt=self._attempt,
            causation_id=causation_id,
        )
        if isinstance(result, ThrottledProgress):
            logger.debug("ilerleme seyrekleştirildi: run=%s kind=%s", run_id, kind)


def _to_transport_citation(
    citation: SourceReference, wire_version: int = 1
) -> AgentSourceReference | AgentSourceReferenceV2:
    """Domain ``SourceReference`` → run sürümünün transport kaynak modeli.

    v1: article|web (``source_id`` artık düşürülmez — v1 şeması izin verir);
    v2: article|web|profile (profil sürümü + bölüm/parça + ``/about#`` bağlantısı).
    ``TransportModel`` açık null reddeder; None alanlar kurucuya geçilmez. v1 run'ı
    profile kaynağı taşıyamaz (``WireVersionMismatch``).
    """

    return to_transport_citation(citation, wire_version)


def _to_transport_usage(run_id: str, usage: Any) -> AgentUsageRecord:
    return AgentUsageRecord(
        run_id=run_id,
        model_calls=usage.model_calls,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        tool_calls=usage.tool_calls,
        web_search_calls=usage.web_search_calls,
        duration_seconds=float(usage.duration_seconds),
        recorded_at=usage.recorded_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _to_transport_outcome_dataclass(
    kind: str, outcome: AgentOutcome, run_intent: RunIntent | None = None
) -> TransportAgentOutcome:
    """Domain sonucunu B5 yayıncısının veri sınıfına çevirir (scope kontrolü için).

    Yalnız ``AgentEventPublisher._check_source_scope``'un okuduğu alanlar
    doldurulur (``kind``'ı okunan citation'lar, kapsam, etkin niyet); kuralın tek
    kaynağı events.py'de kalır (kopyalanmaz).
    """

    return TransportAgentOutcome(
        kind=kind,  # type: ignore[arg-type]
        selected_mode=outcome.selected_mode.value,
        source_scope=outcome.source_scope.value if outcome.source_scope else None,
        citations=tuple(outcome.citations),
        run_intent=run_intent.value if run_intent is not None else None,
    )


def planned_source_scope(prepared: PreparedRun) -> SourceScope:
    """Rota kararının planlanan kaynak kapsamı (v2 ``mode_selected.source_scope``).

    PROFILE niyeti daima profil kapsamıdır (web/makale yok); diğerlerinde
    çekirdeğin ``_scope_for`` sırası izlenir — makale bağlamı worker'da referans
    olarak taşındığından (K7) makale bağı ``article_id`` ile anlaşılır.
    """

    route = prepared.route
    if route.intent is RunIntent.PROFILE:
        return SourceScope.PROFILE
    if route.needs_web:
        return SourceScope.ARTICLE_AND_WEB
    if route.source_scope is not None:
        return route.source_scope
    context = prepared.context
    if context.article_snapshot is not None or context.article_id is not None:
        return SourceScope.ARTICLE
    return SourceScope.GENERAL


def is_profile_bound(context: ExecutionContext, intent: RunIntent | None) -> bool:
    """Profil (Who am I) korumaları uygulanır mı: açık who_am_i konusu veya PROFILE niyeti."""

    return context.conversation_topic is ConversationTopic.WHO_AM_I or intent is RunIntent.PROFILE


def audit_profile_outcome(
    *,
    wire_version: int,
    context: ExecutionContext,
    run_intent: RunIntent | None,
    outcome: AgentOutcome,
) -> str | None:
    """Who am I kaynak denetimi (K5/K6 worker yarısı); ihlal metni veya None.

    - v1 run'ı profile kaynağı taşıyamaz (legacy A9 yolu citation'sızdır;
      provenance article/web'e daraltılmaz).
    - Açık who_am_i konusu PROFILE dışı etkin niyetle tamamlanamaz.
    - Profil kapsamı/niyeti: citation'lar yalnız profile türünde ve sonuç
      snapshot'ı, run'a kabulde pinlenen ``context.profile_snapshot``'a eşit;
      worker başka sürüme geçmez.
    """

    profile_citations = [c for c in outcome.citations if c.kind == "profile"]
    if wire_version < WIRE_VERSION_V2:
        if profile_citations:
            return "v1 run'ı profile kaynağı taşıyamaz (legacy profil yolu citation üretmez)"
        return None
    if context.conversation_topic is ConversationTopic.WHO_AM_I and run_intent is not RunIntent.PROFILE:
        return f"who_am_i konusu PROFILE dışı niyetle sonuçlanamaz (etkin niyet: {run_intent})"
    profile_bound = run_intent is RunIntent.PROFILE or outcome.source_scope is SourceScope.PROFILE
    if not profile_bound:
        if profile_citations:
            return "profile kaynağı yalnız profil kapsamlı sonuçta taşınabilir"
        return None
    if outcome.source_scope is not SourceScope.PROFILE:
        return f"profil niyeti yalnız source_scope=profile ile sonuçlanabilir (gelen: {outcome.source_scope})"
    foreign = sorted({c.kind for c in outcome.citations if c.kind != "profile"})
    if foreign:
        return f"profil sonucu profil dışı kaynak taşıyamaz: {', '.join(foreign)}"
    pinned = context.profile_snapshot
    result_snapshot = outcome.profile_snapshot
    if result_snapshot is not None and (pinned is None or not pinned.same_as(result_snapshot)):
        return "profil sonucu run'a pinlenmiş profil sürümüne ait değil"
    for citation in profile_citations:
        if pinned is None or not pinned.same_as(citation.profile_snapshot):
            return "profile citation run'a pinlenmiş profil sürümüne ait değil"
    return None


class ExecutionWorker:
    """``agent.jobs``'ı claim edip agent çekirdeğini çalıştıran adaptör.

    Ömür: ``run_once`` (test/denetim) veya ``run_forever`` (servis döngüsü).
    ``sweep`` recovery sınırını aşan işleri periyodik kapatır.
    """

    def __init__(
        self,
        store: JobStore,
        deps: ExecutionDependencies,
        *,
        settings: WorkerSettings,
        publisher: AgentEventPublisher | None = None,
        checkpoint_store: CheckpointStorePort | None = None,
        control_store: ControlStore | None = None,
    ) -> None:
        self._store = store
        self._deps = deps
        self._settings = settings
        self._publisher = publisher
        self._control = control_store
        self._checkpoint = checkpoint_store or deps.checkpoint_store or FileCheckpointStore(
            settings.checkpoint_base_dir
        )

    # ------------------------------------------------------------------ döngü

    async def run_once(self) -> CycleResult:
        """Bir iş claim eder ve sonucuna kadar yürütür; iş yoksa idle döner."""

        claimed = await self._store.claim_next_job(
            self._settings.worker_id,
            lease_seconds=self._settings.lease_seconds,
            queue_class=self._settings.queue_classes,
            max_execution_attempts=self._settings.max_execution_attempts,
        )
        if claimed is None:
            return CycleResult(idle=True)
        return await self.execute_claimed(claimed)

    async def execute_claimed(
        self,
        claimed: ClaimedJob,
        *,
        collab_input: Any | None = None,
        validated_result: Any | None = None,
    ) -> CycleResult:
        """Claim EDİLMİŞ bir işi girdiyle sonucuna kadar yürütür (W6 F3 girişi).

        ``run_once``'in claim sonrası yarısıdır; kontrol tüketici sürücüsü
        (``control_driver.CollaborationResumeDriver``) hedef run'ı
        ``claim_job_for_continuation`` ile kendisi claim edip BURAYA girdiyle
        (``collab_input``/``validated_result``) gelir — A9 checkpoint devamı
        backend kararını böyle görür. WorkerAborted terminal'siz bırakma
        kararları CycleResult'a çevrilir (run_once ile aynı sözleşme).
        """

        attributes = {"messaging.system": "rabbitmq", "blogapp.execution.attempt": claimed.execution_attempt}
        # A recovered job's age also contains previous execution time, so it is
        # not presented as queue wait. First admission has a precise boundary.
        if claimed.execution_attempt == 1:
            started = claimed.started_at or datetime.now(timezone.utc)
            attributes["messaging.message.queue_time_ms"] = max(0, (started - claimed.accepted_at).total_seconds() * 1000)
        with trace_operation("agent.execute", parent=claimed.envelope.trace_context, attributes=attributes) as span:
            try:
                result = await self._execute_claimed(
                    claimed,
                    collab_input=collab_input,
                    validated_result=validated_result,
                )
            except WorkerAborted as abort:
                logger.warning("yürütme terminal'siz bırakıldı: run=%s (%s)", claimed.run_id, abort)
                result = CycleResult(
                    run_id=claimed.run_id,
                    action=abort.args[0] if abort.args else "aborted",
                    detail=str(abort),
                    execution_attempt=claimed.execution_attempt,
                    fencing_token=claimed.fencing_token,
                    recovered=claimed.recovered,
                )
            set_span_attributes(span, {"blogapp.run.status": "partial" if result.action == "partially_completed" else result.action})
            return result

    async def run_forever(self, *, max_cycles: int | None = None) -> None:
        """Claim-çalıştır bekleme döngüsü; her 8 çevrimde bir sweep."""

        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            try:
                if cycles % 8 == 0:
                    await self.sweep()
                result = await self.run_once()
            except Exception:  # servis döngüsü ölmez; hata loglanır, lease toparlanır
                logger.exception("worker çevrimi başarısız: worker=%s", self._settings.worker_id)
                result = None
            cycles += 1
            if result is not None and getattr(result, "idle", False):
                await asyncio.sleep(self._settings.poll_interval_seconds)

    async def sweep(self) -> list[str]:
        """Deneme sınırını aşmış, lease'i bitmiş işleri kalıcı kapatır."""

        return await self._store.fail_expired_jobs_beyond_attempts(
            self._settings.max_execution_attempts,
            error_code=WORKER_ERROR_CODE,
            error_message=(
                f"yürütme denemesi sınırı aşıldı (max={self._settings.max_execution_attempts}); "
                "iş SINIRLI recovery politikasıyla kapatıldı"
            ),
        )

    # -------------------------------------------------------------- yürütme

    async def _execute_claimed(
        self,
        claimed: ClaimedJob,
        *,
        collab_input: Any | None = None,
        validated_result: Any | None = None,
    ) -> CycleResult:
        run_id = claimed.run_id
        envelope = claimed.envelope
        watch = _LeaseWatch(self._store, run_id, claimed.fencing_token, self._settings)
        cancel = _WorkerCancel()
        watch.start(cancel)
        released = False

        async def _release() -> None:
            nonlocal released
            if not released:
                await self._store.release_job_lease(run_id, claimed.fencing_token)
                released = True  # kayıp lease'te boş döner; tekrar deneme anlamsız

        try:
            # Worker başlangıcında deadline kontrolü (plan B7 kuralının worker
            # yarısı): claim filtresi ile şimdi arasında geçen süre kapanır.
            if claimed.deadline_at is not None and claimed.deadline_at <= datetime.now(timezone.utc):
                return await self._fail_now(
                    claimed,
                    error_code="timeout",
                    error_message="iş kabul anındaki deadline'ı yürütme başlamadan doldu",
                )

            # Güvenli sınır: aktif iptal niyeti varsa yürütme BAŞLAMAZ; terminal
            # 'cancelled' geçişini B7'nin koşullu UPDATE'i üretir.
            if await self._store.has_cancel_intent(run_id):
                await _release()
                raise WorkerAborted("aborted_cancel", "aktif iptal niyeti var; yürütme başlatılmadı")

            # İşin wire sürümünün DTO'suyla yeniden doğrulama (v1 işi v1, v2 işi v2;
            # intake doğrulamasının savunma tekrarı). Bozuk kalıcı payload
            # anlaşılır validation_error terminaliyle kapanır.
            payload_model = self._validate_claimed_payload(claimed)
            # B8 stale komut guard'ı: makale üçlüsü taşıyan komutun snapshot
            # revizyonu, projection'ın bildiği kaldırma revizyonundan eskiyse
            # yürütme başlamaz (ne taze yol ne checkpoint resume).
            self._ensure_execution_allowed(payload_model)
            context = self._build_context(payload_model, claimed)

            metered = _MeteredModel(self._deps.model)
            sink = _WorkerProgressSink(
                run_id=run_id,
                conversation_id=claimed.conversation_id,
                correlation_id=envelope.correlation_id,
                causation_id=claimed.origin_message_id,
                execution_attempt=claimed.execution_attempt,
                publisher=self._publisher,
                watch=watch,
                # Açık who_am_i: koruma rota kararından ÖNCE açılır.
                profile_guard=is_profile_bound(context, None),
            )
            route_state: dict[str, Any] = {"intent": None}

            # A8: checkpoint varsa DEVAM (rota kararı checkpoint'ten okunur).
            # W6 F3: sürücüden gelen collab_input/validated_result devam
            # girdisi checkpoint devamına AKTARILIR — aksi halde agent.action.result
            # agent'a ulaşsa bile A9 onay makinesi sonucu hiç görmezdi.
            resumed = await self._try_resume(
                claimed,
                metered=metered,
                sink=sink,
                cancel=cancel,
                collab_input=collab_input,
                validated_result=validated_result,
                route_state=route_state,
            )
            if isinstance(resumed, CycleResult):
                return resumed
            outcome = resumed

            if outcome is None:
                # Taze yürütme: hazırlık + rota (router kararı çekirdekte üretilir).
                prepared: PreparedRun = await prepare_and_route(
                    context,
                    router_model=self._deps.router_model,
                    progress=sink,
                    cancel=cancel,
                    checkpoint=self._checkpoint_for(claimed),
                    execution_id=stable_execution_id(run_id),
                    profile_identity=self._profile_identity(context),
                )
                route_state["intent"] = prepared.route.intent
                if is_profile_bound(prepared.context, prepared.route.intent):
                    # AUTO→PROFILE dahil: koruma rota kararından hemen sonra açılır.
                    sink.enable_profile_guard()
                if (
                    prepared.route.selected_mode is AgentMode.DEEP_RESEARCH
                    and claimed.queue_class != QUEUE_CLASS_RESEARCH
                    and prepared.route.intent is not RunIntent.PROFILE
                ):
                    # Kapasite ertelemesi: araştırma işi research kuyruğuna döner.
                    # Yürütme (model çağrısı) başlamadığı için deneme sayacı
                    # resetlenir; fencing_token monoton kalır.
                    moved = await self._store.requeue_job(
                        run_id,
                        claimed.fencing_token,
                        queue_class=QUEUE_CLASS_RESEARCH,
                        reset_attempt=True,
                    )
                    if not moved:
                        raise WorkerAborted(
                            "aborted_lease_lost", "erteleme yazımı fencing guard'ına takıldı"
                        )
                    return CycleResult(
                        run_id=run_id,
                        action="deferred",
                        detail="deep_research kararı research kapasitesine ertelendi",
                        execution_attempt=0,
                        fencing_token=claimed.fencing_token,
                        recovered=claimed.recovered,
                    )

                # v2: rota kararı backend'e doğrulanabilir biçimde bildirilir
                # (etkin niyet + planlanan kapsam + pinlenmiş snapshot).
                await self._publish_mode_selected(claimed, prepared, guarded=sink.profile_guard)

                outcome = await self._execute_prepared(
                    claimed,
                    prepared=prepared,
                    metered=metered,
                    sink=sink,
                    cancel=cancel,
                    collab_input=collab_input,
                    validated_result=validated_result,
                )

            # Lease bu yürütme sırasında kaybedildiyse SONUÇ NE OLURSA OLSUN
            # yazılmaz: iş yeni denemenin; terminal onun hakkıdır.
            if watch.lost:
                raise WorkerAborted(
                    "aborted_lease_lost", "lease kaybedildi; sonuç yazılmaz (yeni sahibin yolu açık)"
                )

            return await self._finish_outcome(
                claimed,
                outcome=outcome,
                metered=metered,
                context=context,
                run_intent=outcome.run_intent or route_state["intent"],
            )
        except PortError as error:
            if error.code is AgentErrorCode.CANCELLED:
                if watch.lost:
                    raise WorkerAborted(
                        "aborted_lease_lost", "lease kaybedildi; terminal yazılmaz"
                    ) from None
                await _release()
                raise WorkerAborted(
                    "aborted_cancel", "iptal sinyali; terminal 'cancelled' B7'ye ait"
                ) from None
            # Kalıcı yürütme hatası: terminal failed (guard'lı; iş hâlâ bizimse).
            return await self._fail_now(
                claimed, error_code=error.code, error_message=error.message
            )
        finally:
            await watch.stop()

    def _validate_claimed_payload(self, claimed: ClaimedJob) -> AgentExecutionRequestedV1:
        """Kalıcı execute payload'ını İŞİN wire sürümünün DTO'suyla doğrular.

        v2 eksik-alan kuralı (who_am_i → pinlenmiş snapshot zorunlu) doğrulayıcıda
        olduğundan burada da uygulanır. İhlal ``PortError(validation_error)``:
        ``_fail_now`` anlaşılır terminal üretir (sonsuz recovery döngüsü yok).
        """

        model = spec_for(claimed.wire_version, "agent.execute.requested").payload_model
        try:
            payload = model.model_validate(claimed.payload)
        except ValidationError as error:
            first = error.errors()[0]
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"kalıcı execute payload'ı v{claimed.wire_version} sözleşmesine aykırı: "
                f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}",
                port="worker",
            ) from None
        if (
            isinstance(payload, AgentExecutionRequestedV2)
            and payload.conversation_topic.value == ConversationTopic.WHO_AM_I.value
            and payload.profile_snapshot is None
        ):
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "who_am_i işi pinlenmiş profile_snapshot taşımıyor",
                port="worker",
            )
        return payload  # type: ignore[return-value]

    async def _publish_mode_selected(
        self, claimed: ClaimedJob, prepared: PreparedRun, *, guarded: bool
    ) -> None:
        """v2 ``agent.run.mode_selected``: etkin niyet, planlanan kapsam ve snapshot.

        v1 run'ında yayınlanmaz (v1 davranışı korunur). PROFILE niyeti daima
        ``requires_web_search=false`` + ``source_scope=profile`` + pinlenmiş
        snapshot taşır; snapshot pinlenmemişse olay sözleşmeyle ifade edilemez
        ve atlanır (çekirdek run'ı config_error ile kapatır — K1). Profil
        korumasında gerekçe sabit metindir (ara olay serbest metin taşımaz).
        Sözleşme ihlali yürütmeyi durdurmaz: loglanır, terminal denetimi geçerlidir.
        """

        if self._publisher is None or claimed.wire_version < WIRE_VERSION_V2:
            return
        route = prepared.route
        intent = route.intent
        snapshot = prepared.context.profile_snapshot if intent is RunIntent.PROFILE else None
        if intent is RunIntent.PROFILE and snapshot is None:
            logger.warning(
                "mode_selected atlandı: run=%s PROFILE niyeti pinlenmiş profil sürümü taşımıyor", claimed.run_id
            )
            return
        reason = "Yazar profili sorusu: yalnız onaylı profil kaynağı" if guarded else route.brief_reason[:2000]
        try:
            await self._publisher.publish_mode_selected(
                run_id=claimed.run_id,
                conversation_id=claimed.conversation_id,
                correlation_id=claimed.envelope.correlation_id,
                selected_mode=route.selected_mode.value,
                requires_web_search=bool(route.needs_web and intent is not RunIntent.PROFILE),
                reason=reason,
                execution_attempt=claimed.execution_attempt,
                causation_id=claimed.origin_message_id,
                run_intent=intent.value,
                source_scope=planned_source_scope(prepared).value,
                profile_snapshot=snapshot,
            )
        except (EventPublishError, ValueError) as error:
            logger.error("mode_selected yayınlanamadı: run=%s (%s)", claimed.run_id, error)

    async def _try_resume(
        self,
        claimed: ClaimedJob,
        *,
        metered: _MeteredModel,
        sink: _WorkerProgressSink,
        cancel: _WorkerCancel,
        collab_input: Any | None = None,
        validated_result: Any | None = None,
        route_state: dict[str, Any] | None = None,
    ) -> "AgentOutcome | CycleResult | None":
        """Checkpoint'i arar; bulunursa A8 ``resume`` ile devam ettirir.

        Dönüş: ``None`` (checkpoint yok — taze yol), ``CycleResult``
        (terminal'siz bırakma/erteleme) veya ``AgentOutcome`` (devam sonucu).
        Checkpoint'teki rota ``deep_research`` ise ve bu claim research
        kapasitesinde DEĞİLSE yürütme devam etmez: iş ertelenir (kapasite
        ayrımı checkpoint'li yolda da korunur).

        W6 F3: ``collab_input``/``validated_result`` A9 resume girdisi olarak
        çekirdeğe aynen taşınır (sürücü yolu); rehberlik kaynakları da
        aktarılır — checkpoint'ten devam eden profile/projects/content_suggestion
        çalışması onaylı kaynaklar olmadan ``config_error``'a düşmez.
        """

        execution_id = stable_execution_id(claimed.run_id)
        checkpoint = self._checkpoint_for(claimed)
        try:
            _envelope, payload = await load_resume_payload(
                checkpoint, claimed.run_id, None, execution_id=execution_id
            )
        except PortError as error:
            if error.code is AgentErrorCode.NOT_FOUND:
                return None  # taze yürütme
            if error.code is AgentErrorCode.VALIDATION_ERROR:
                # Uyumsuz/başka çalışmaya ait checkpoint: anlaşılır terminal
                # (plan A8); recovery tekrarları aynı hatayı üretir.
                return await self._fail_now(
                    claimed,
                    error_code=error.code,
                    error_message=f"checkpoint'ten devam edilemedi: {error.message}",
                )
            raise WorkerAborted(
                "error_transient", f"checkpoint deposu arızası: {error.message}"
            ) from None

        stored = PreparedRun.model_validate_json(payload.decode("utf-8"))
        if route_state is not None:
            route_state["intent"] = stored.route.intent
        if is_profile_bound(stored.context, stored.route.intent):
            sink.enable_profile_guard()  # checkpoint'ten devamda da profil sınırları
        if (
            stored.route.selected_mode is AgentMode.DEEP_RESEARCH
            and claimed.queue_class != QUEUE_CLASS_RESEARCH
            and stored.route.intent is not RunIntent.PROFILE
        ):
            moved = await self._store.requeue_job(
                claimed.run_id,
                claimed.fencing_token,
                queue_class=QUEUE_CLASS_RESEARCH,
                reset_attempt=True,
            )
            if not moved:
                raise WorkerAborted(
                    "aborted_lease_lost", "erteleme yazımı fencing guard'ına takıldı"
                )
            return CycleResult(
                run_id=claimed.run_id,
                action="deferred",
                detail="checkpoint deep_research: research kapasitesine ertelendi",
                execution_attempt=0,
                fencing_token=claimed.fencing_token,
                recovered=claimed.recovered,
            )

        remaining = None
        if claimed.deadline_at is not None:
            remaining = (claimed.deadline_at - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return await self._fail_now(
                    claimed,
                    error_code="timeout",
                    error_message="checkpoint'ten devam ederken deadline doldu",
                )
        if (stored.route.intent is RunIntent.COLLABORATION and stored.collab_state is not None
                and stored.collab_state.stage is CollabStage.RESOLVED
                and collab_input is None and validated_result is None and claimed.recovered):
            # A previous owner may have persisted the validated backend result
            # immediately before losing its terminal commit. Reconcile only a
            # trusted lease-recovery claim; public/human resume stays rejected.
            if (stored.context.run_id != claimed.run_id or stored.route.run_id != claimed.run_id
                    or (stored.execution_id is not None and stored.execution_id != execution_id)):
                raise PortError(AgentErrorCode.VALIDATION_ERROR, "Recovered checkpoint identity does not match the claimed job", port="worker")
            if cancel is not None:
                cancel.raise_if_cancelled()
            return reconcile_resolved_collaboration(stored.context, stored.route, stored.collab_state)

        budget = self._budget_for(stored.context, claimed.fencing_token)
        with embedding_budget_scope(stored.context.run_id, budget):
            outcome = await resume(
                ResumeRequest(
                    run_id=claimed.run_id,
                    execution_id=execution_id,
                    deadline_seconds=remaining,
                    collab_input=collab_input,
                    validated_result=validated_result,
                ),
                checkpoint=checkpoint,
                model=metered,
                retriever=self._deps.retriever,
                content=self._deps.content,
                budget=budget,
                progress=sink,
                cancel=cancel,
                # Profil run'ına dış kaynak kapasitesi port düzeyinde verilmez (K5).
                web_tools=None if sink.profile_guard else self._deps.web_tools,
                profile_repository=self._deps.profile_repository,
                project_repository=self._deps.project_repository,
                article_catalog=self._deps.article_catalog,
                profile_knowledge=self._deps.profile_knowledge,
                profile_retriever=self._deps.profile_retriever,
            )
        return outcome

    async def _execute_prepared(
        self,
        claimed: ClaimedJob,
        *,
        prepared: PreparedRun,
        metered: _MeteredModel,
        sink: _WorkerProgressSink,
        cancel: _WorkerCancel,
        collab_input: Any | None = None,
        validated_result: Any | None = None,
    ) -> AgentOutcome:
        budget = self._budget_for(prepared.context, claimed.fencing_token)
        with embedding_budget_scope(prepared.context.run_id, budget):
            return await execute_plan(
                prepared,
                model=metered,
                retriever=self._deps.retriever,
                content=self._deps.content,
                budget=budget,
                progress=sink,
                cancel=cancel,
                # Profil run'ına web/arama/kaynak okuyucu araçları HİÇ verilmez (K5):
                # Profile execution receives no external tool handles at all.
                web_tools=None if sink.profile_guard else self._deps.web_tools,
                profile_repository=self._deps.profile_repository,
                project_repository=self._deps.project_repository,
                article_catalog=self._deps.article_catalog,
                checkpoint=self._checkpoint_for(claimed),
                collab_input=collab_input,
                validated_result=validated_result,
                profile_knowledge=self._deps.profile_knowledge,
                profile_retriever=self._deps.profile_retriever,
            )

    def _budget_for(self, context: ExecutionContext, fencing_token: int) -> BudgetStore | None:
        if self._deps.budget_factory is not None:
            return self._deps.budget_factory(context, fencing_token)
        return self._deps.budget

    def _checkpoint_for(self, claimed: ClaimedJob) -> CheckpointStorePort:
        if self._deps.checkpoint_factory is not None:
            return self._deps.checkpoint_factory(self._checkpoint, claimed.run_id, claimed.fencing_token)
        return self._checkpoint

    # ------------------------------------------------- iptal terminali + guard

    def _profile_identity(self, context: ExecutionContext) -> ProfileIdentity | None:
        repository = self._deps.profile_knowledge
        if repository is None:
            return None
        snapshot = context.profile_snapshot or repository.active_snapshot()
        return ProfileIdentity.from_document(repository.load(snapshot))

    def _ensure_execution_allowed(self, payload: AgentExecutionRequestedV1) -> None:  # v2 alt sınıfı dahil
        """B8 stale komut denetimi: bilinen kaldırma revizyonundan eski snapshot reddedilir.

        Denetim ``content_state.ensure_execution_allowed``'e (``ContentSyncState``)
        delege edilir; projection bağlanmadıysa veya komut makale üçlüsü
        taşımıyorsa (makalesiz genel sorular) denetim yoktur. İhlal anlaşılır
        terminalle kapanır: ``stale_snapshot`` (PortError → ``_fail_now``).
        """

        if self._deps.content_state is None:
            return
        if payload.article_id is None or payload.article_revision is None:
            return
        try:
            self._deps.content_state.ensure_execution_allowed(
                str(payload.article_id), int(payload.article_revision)
            )
        except StaleExecutionRejected as error:
            raise PortError(
                AgentErrorCode.STALE_SNAPSHOT,
                f"eski komut yürütülmedi: {error}",
                port="worker",
            ) from None

    async def _mark_cancelled_terminal(self, claimed: ClaimedJob) -> bool:
        """Terminali 'cancelled' B7 kuralıyla üretir (kontrol deposu bağlıysa).

        Ortak store sözleşmesinin worker yarısı (W5 bulgusu 1b):
        ``mark_cancelled_if_running`` koşullu UPDATE'i intent YOKSA dokunmaz,
        VARSA cancelled + agent.run.cancelled olayını TEK transaction'da üretir.
        Kontrol deposu bağlanmadıysa False döner (davranış değişmez; iş deadline
        reaper'ına kalır).
        """

        if self._control is None:
            return False
        outcome = await self._control.mark_cancelled_if_running(
            claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
        )
        return outcome == "cancelled"

    async def _finalize_cancel_rejection(self, claimed: ClaimedJob, reason: str | None) -> bool:
        """complete/fail 'cancel_requested' ile reddedildiyse terminali üretir.

        Red gerekçesi ``cancel_requested`` ise iş HÂLÂ 'running'dir ve niyet
        kayıtlıdır: terminali yalnız B7 koşullu UPDATE'i yazabilir — worker
        tam burada onu çağırır; aksi halde iş deadline reaper'ına dek 'running'
        asılı kalır (W5 bulgusu 1b). Dönüş: terminal üretildi mi.
        """

        if reason != "cancel_requested":
            return False
        return await self._mark_cancelled_terminal(claimed)

    # ------------------------------------------------------- sonuç yazımı

    async def _finish_outcome(
        self,
        claimed: ClaimedJob,
        *,
        outcome: AgentOutcome,
        metered: _MeteredModel,
        context: ExecutionContext | None = None,
        run_intent: RunIntent | None = None,
    ) -> CycleResult:
        """Domain sonucunu run sürümünün transport terminaline çevirip guard'la yazar."""

        run_id = claimed.run_id
        profile_run = (
            claimed.wire_version >= WIRE_VERSION_V2
            and context is not None
            and is_profile_bound(context, run_intent)
        )
        if outcome.status is RunStatus.NEEDS_INPUT and profile_run:
            # Who am I askıda iş oluşturmaz (K5): bilinmeyen/özel bilgi tamamlanmış
            # kısa cevaptır; collaboration resume akışı bu iş için kullanılmaz.
            return await self._fail_now(
                claimed,
                error_code="validation_error",
                error_message="profil (Who am I) çalışması needs_input üretemez",
                run_intent=run_intent,
                profile_snapshot=context.profile_snapshot if context is not None else None,
            )
        if outcome.status is RunStatus.NEEDS_INPUT:
            # needs_input terminal DEĞİLDİR: iş beklemeye döner (checkpoint
            # korunur); B5 needs_input olayı outbox'a yazılır.
            envelope = self._nonterminal_envelope(
                "agent.run.needs_input",
                claimed,
                unresolved_questions=list(outcome.unresolved_questions),
                usage=_to_transport_usage(run_id, outcome.usage),
            )
            await self._publish_outbox_only(run_id, envelope)
            moved = await self._store.requeue_job(run_id, claimed.fencing_token)
            if not moved:
                raise WorkerAborted("aborted_lease_lost", "needs_input geri yazımı guard'a takıldı")
            return CycleResult(
                run_id=run_id,
                action="needs_input",
                detail="kullanıcı girdisi bekleniyor; iş bekleyen durumuna döndü",
                execution_attempt=claimed.execution_attempt,
                fencing_token=claimed.fencing_token,
                recovered=claimed.recovered,
            )
        if outcome.status is RunStatus.CANCELLED:
            # Çekirdek iptali worker sinyalinden geliyorsa zaten abort edilmiş
            # olmalıdır; buraya düşmesi savunmacıdır: terminal'i B7 üretir.
            released = await self._store.release_job_lease(run_id, claimed.fencing_token)
            finalized = await self._mark_cancelled_terminal(claimed)
            raise WorkerAborted(
                "aborted_cancel",
                "çekirdek cancelled döndürdü "
                f"(lease bırakıldı={released}, terminal üretildi={finalized}); terminal B7'ye ait",
            )

        kind_map = {
            RunStatus.COMPLETED: "completed",
            RunStatus.PARTIAL: "partially_completed",
            RunStatus.FAILED: "failed",
        }
        kind = kind_map[outcome.status]

        transport_outcome = _TransportOutcome(kind=kind, domain=outcome)
        pinned = context.profile_snapshot if context is not None else None

        if kind in ("completed", "partially_completed"):
            # B5 yayın kuralının TEK kaynağına delegasyon: scope/citation
            # uyuşmazlığında terminal completed YAYINLANMAZ; iş anlaşılır
            # validation_error ile failed kapanır (sonuç çekirdekten bozuk
            # geldiğinde sessiz yayın yok).
            try:
                AgentEventPublisher._check_source_scope(
                    _to_transport_outcome_dataclass(kind, outcome, run_intent)
                )
            except EventPublishError as error:
                return await self._fail_now(
                    claimed,
                    error_code="validation_error",
                    error_message=f"terminal sonuç yayın kuralına aykırı: {error}",
                    run_intent=run_intent,
                    profile_snapshot=pinned,
                )
            if context is not None:
                violation = audit_profile_outcome(
                    wire_version=claimed.wire_version,
                    context=context,
                    run_intent=run_intent,
                    outcome=outcome,
                )
                if violation is not None:
                    return await self._fail_now(
                        claimed,
                        error_code="validation_error",
                        error_message=f"profil kaynak denetimi: {violation}",
                        run_intent=run_intent,
                        profile_snapshot=pinned,
                    )

        try:
            terminal_envelope = self._terminal_envelope(
                claimed, transport_outcome, run_intent=run_intent, pinned_snapshot=pinned
            )
        except (AgentContractError, ValidationError, WireVersionMismatch) as error:
            # Sözleşmeye (run sürümünün DTO'su + tüketici çapraz kuralları) aykırı
            # terminal YAYINLANMAZ; iş anlaşılır validation_error ile kapanır.
            detail = (
                f"{error.category.value}: {error.message}" if isinstance(error, AgentContractError) else str(error)
            )
            return await self._fail_now(
                claimed,
                error_code="validation_error",
                error_message=f"terminal sonuç v{claimed.wire_version} sözleşmesine aykırı: {detail}"[:4000],
                run_intent=run_intent,
                profile_snapshot=pinned,
            )
        result_json = self._result_json(claimed, transport_outcome, metered, run_intent=run_intent)

        write = (
            await self._store.complete_job(
                run_id, result_json, claimed.fencing_token, outbox_event=terminal_envelope
            )
            if kind in ("completed", "partially_completed")
            else await self._store.fail_job(
                run_id, result_json, claimed.fencing_token, outbox_event=terminal_envelope
            )
        )
        if not write.accepted:
            if await self._finalize_cancel_rejection(claimed, write.reason):
                # İptal yarışını B7 kazandı: terminal 'cancelled' üretildi; bu
                # denemenin sonucu bilinçli olarak yazılmaz (terminal-öncelik).
                raise WorkerAborted(
                    "aborted_cancel",
                    "terminal yazımı 'cancel_requested' ile reddedildi; "
                    "terminal 'cancelled' B7 kuralıyla üretildi",
                )
            raise WorkerAborted(
                "aborted_lease_lost",
                f"terminal yazımı reddedildi ({write.reason}); iş bu denemenin değil",
            )
        return CycleResult(
            run_id=run_id,
            action=kind,
            execution_attempt=claimed.execution_attempt,
            fencing_token=claimed.fencing_token,
            recovered=claimed.recovered,
        )

    async def _fail_now(
        self,
        claimed: ClaimedJob,
        *,
        error_code: str,
        error_message: str,
        run_intent: RunIntent | None = None,
        profile_snapshot: ProfileSnapshotRef | None = None,
    ) -> CycleResult:
        """Yürütme başlamadan/orta yolda anlaşılır terminal failed üretir (run sürümüyle).

        v2'de bilinen etkin niyet ve pinlenmiş profil sürümü opsiyonel olarak taşınır.
        """

        envelope = compose_run_envelope(
            schema_version=claimed.wire_version,
            message_type="agent.run.failed",
            run_id=claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
            occurred_at=_utcnow_str(),
            payload=versioned_payload(
                claimed.wire_version,
                {
                    "event_sequence": 0,
                    "execution_attempt": claimed.execution_attempt,
                    "fencing_token": str(claimed.fencing_token),
                    "error_code": _code_value(error_code),
                    "error_message": (error_message or "")[:4000] or None,
                },
                {
                    "run_intent": run_intent.value if run_intent is not None else None,
                    "profile_snapshot": to_transport_profile_snapshot(profile_snapshot),
                },
            ),
        )
        result_json = {
            "outcome": "failed",
            "error_code": _code_value(error_code),
            "error_message": error_message,
            "execution_id": stable_execution_id(claimed.run_id),
            "execution_attempt": claimed.execution_attempt,
            "wire_version": claimed.wire_version,
        }
        write = await self._store.fail_job(
            claimed.run_id, result_json, claimed.fencing_token, outbox_event=envelope
        )
        if not write.accepted:
            if await self._finalize_cancel_rejection(claimed, write.reason):
                raise WorkerAborted(
                    "aborted_cancel",
                    "failed yazımı 'cancel_requested' ile reddedildi; "
                    "terminal 'cancelled' B7 kuralıyla üretildi",
                )
            raise WorkerAborted(
                "aborted_lease_lost", f"failed yazımı reddedildi ({write.reason})"
            )
        return CycleResult(
            run_id=claimed.run_id,
            action="failed",
            detail=error_message,
            execution_attempt=claimed.execution_attempt,
            fencing_token=claimed.fencing_token,
            recovered=claimed.recovered,
        )

    # ----------------------------------------------------------- yardımcılar

    def _build_context(
        self, payload: AgentExecutionRequestedV1, claimed: ClaimedJob
    ) -> ExecutionContext:
        """Execute payload'ını (v1 veya v2) çekirdek ``ExecutionContext``'ine çevirir.

        Konuşma geçmişi backend snapshot'ından AYNEN taşınır (plan B6:
        "konuşma cevap geçmişini backend snapshot'ına göre koruma"); worker
        tur eklemez/çıkarmaz. ``article_snapshot`` bilinçli None'dur (K7):
        çekirdek yalnız referansla çalışır; içerik getirmesi B8 pgvector
        entegrasyonundan sonra retriever bağlanarak etkinleşir.

        v2: ``conversation_topic`` ve kabulde pinlenen ``profile_snapshot`` taşınır;
        v1: konu ``None`` (legacy A9 profil yolu). who_am_i konusunda bütçe
        profilinin web/araç limitleri sıfırlanır (araçlar zaten port düzeyinde
        verilmez). Bağlam kuralı ihlali ``PortError(validation_error)``.
        """

        profile = self._settings.budget_profile or BudgetProfile(
            name=payload.budget_profile,
            max_model_calls=16,
            max_total_tokens=32000,
            max_tool_calls=0,
            max_web_search_calls=0,
            max_duration_seconds=600.0,
        )
        history = [
            ConversationTurn(role=turn.role, content=turn.content, created_at=turn.created_at)
            for turn in payload.conversation_history
        ]
        topic: ConversationTopic | None = None
        snapshot: ProfileSnapshotRef | None = None
        if isinstance(payload, AgentExecutionRequestedV2):
            topic = ConversationTopic(payload.conversation_topic.value)
            if payload.profile_snapshot is not None:
                snapshot = ProfileSnapshotRef(
                    profile_id=payload.profile_snapshot.profile_id,
                    revision=payload.profile_snapshot.revision,
                    content_hash=payload.profile_snapshot.content_hash,
                )
        if topic is ConversationTopic.WHO_AM_I and (profile.max_web_search_calls or profile.max_tool_calls):
            profile = profile.model_copy(update={"max_web_search_calls": 0, "max_tool_calls": 0})
        try:
            return ExecutionContext(
                run_id=claimed.run_id,
                conversation_id=claimed.conversation_id,
                question=payload.question,
                language=payload.language,
                mode_preference=ModePreference(payload.mode_preference),
                article_id=payload.article_id,
                article_revision=payload.article_revision,
                article_content_hash=payload.article_content_hash,
                article_snapshot=None,
                selected_text=payload.selected_text,
                conversation_history=history,
                budget_profile=profile,
                conversation_topic=topic,
                profile_snapshot=snapshot,
            )
        except ValidationError as error:
            first = error.errors()[0]
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"yürütme bağlamı kurulamadı: {first['msg']}",
                port="worker",
            ) from None

    def _terminal_envelope(
        self,
        claimed: ClaimedJob,
        transport: "_TransportOutcome",
        *,
        run_intent: RunIntent | None = None,
        pinned_snapshot: ProfileSnapshotRef | None = None,
    ) -> AgentEnvelope:
        """Terminal olay zarfını run sürümünün payload modeliyle kurar (sıra DB'de tahsis edilir).

        v2: ``run_intent`` (completed/partial'da zorunlu) ve ``profile_snapshot``
        taşınır; PROFILE niyetinde citation'sız red/netleştirme cevabı da pinlenmiş
        snapshot'ı taşır. Zarf tüketici doğrulayıcısından geçer
        (``compose_run_envelope``); ihlal çağırana yükselir.
        """

        domain = transport.domain
        version = claimed.wire_version
        common: dict[str, Any] = {
            "event_sequence": 0,  # gerçek değer complete/fail transaction'ında yazılır
            "execution_attempt": claimed.execution_attempt,
            "fencing_token": str(claimed.fencing_token),
        }
        usage = _to_transport_usage(claimed.run_id, domain.usage)
        citations = [_to_transport_citation(c, version) for c in domain.citations]
        intent = domain.run_intent or run_intent
        snapshot = domain.profile_snapshot
        if snapshot is None and intent is RunIntent.PROFILE:
            snapshot = pinned_snapshot
        v2_fields = {
            "run_intent": intent.value if intent is not None else None,
            "profile_snapshot": to_transport_profile_snapshot(snapshot),
        }
        if transport.kind == "completed":
            fields: dict[str, Any] = {
                **common,
                "selected_mode": domain.selected_mode.value,
                "answer": domain.answer,
                "report": domain.report,
                "citations": citations,
                "source_scope": domain.source_scope.value,
                "unresolved_questions": list(domain.unresolved_questions),
                "usage": usage,
            }
        elif transport.kind == "partially_completed":
            fields = {
                **common,
                "selected_mode": domain.selected_mode.value,
                "answer": domain.answer,
                "report": domain.report,
                "citations": citations,
                "source_scope": domain.source_scope.value,
                "unresolved_questions": list(domain.unresolved_questions),
                "usage": usage,
            }
        else:
            fields = {
                **common,
                "error_code": domain.error_code.value if domain.error_code else "provider_error",
                "error_message": domain.error_message,
                "selected_mode": domain.selected_mode.value,
                "usage": usage,
            }
        return compose_run_envelope(
            schema_version=version,
            message_type=f"agent.run.{transport.kind}",
            run_id=claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
            occurred_at=_utcnow_str(),
            payload=versioned_payload(version, fields, v2_fields),
        )

    def _nonterminal_envelope(
        self, message_type: str, claimed: ClaimedJob, **payload_fields: Any
    ) -> AgentEnvelope:
        return compose_run_envelope(
            schema_version=claimed.wire_version,
            message_type=message_type,
            run_id=claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
            occurred_at=_utcnow_str(),
            payload={"event_sequence": 0, **_clean(**payload_fields)},
        )

    async def _publish_outbox_only(self, run_id: str, envelope: AgentEnvelope) -> None:
        """Non-terminal olayı sıra tahsisiyle outbox'a yazar (jobs dokunulmaz).

        ``job_store`` transaction yöntemini yeniden kullanmak için sahte bir
        terminal sonuç kullanılmaz; burada ayrı havuz bağlantısıyla kısa bir
        transaction açılır.
        """

        async with self._store._pool.acquire() as conn:  # noqa: SLF001 - aynı paket içi
            async with conn.transaction():
                await self._store._write_outbox_with_sequence(conn, run_id, envelope)

    def _result_json(
        self,
        claimed: ClaimedJob,
        transport: "_TransportOutcome",
        metered: _MeteredModel,
        *,
        run_intent: RunIntent | None = None,
    ) -> dict[str, Any]:
        """Terminal özeti: kullanım + belirsiz dış maliyet işareti + kimlikler.

        Belirsiz maliyet (plan B6: "Belirsiz dış model çağrısı maliyetlerini
        uygun biçimde kaydet"): bu süreçten ÖNCEKİ denemelerin model çağrıları
        kesilmiştir; harçları doğrulanamaz — A2 ``uncertain`` işaretiyle
        kaydedilir. Sayılar tahmindir, kesinleştirilmez.
        """

        domain = transport.domain
        document: dict[str, Any] = {
            "outcome": transport.kind,
            "selected_mode": domain.selected_mode.value,
            "answer": domain.answer,
            "report": domain.report,
            "error_code": domain.error_code.value if domain.error_code else None,
            "execution_id": stable_execution_id(claimed.run_id),
            "execution_attempt": claimed.execution_attempt,
            "fencing_token": claimed.fencing_token,
            "wire_version": claimed.wire_version,
            "run_intent": (domain.run_intent or run_intent).value if (domain.run_intent or run_intent) else None,
            "profile_snapshot": (
                domain.profile_snapshot.model_dump(mode="json") if domain.profile_snapshot is not None else None
            ),
            "usage": {
                "model_calls": domain.usage.model_calls,
                "prompt_tokens": domain.usage.prompt_tokens,
                "completion_tokens": domain.usage.completion_tokens,
                "total_tokens": domain.usage.total_tokens,
                "tool_calls": domain.usage.tool_calls,
                "web_search_calls": domain.usage.web_search_calls,
                "duration_seconds": domain.usage.duration_seconds,
            },
        }
        if claimed.execution_attempt > 1:
            document["uncertain_usage"] = {
                "uncertain": True,
                "prior_execution_attempts": list(range(1, claimed.execution_attempt)),
                "reason": (
                    "kesintiye uğrayan önceki denemelerin dış model çağrı maliyeti "
                    "bu süreççe doğrulanamaz; ihtiyatla belirsiz işaretlendi (A2)"
                ),
            }
        return {k: v for k, v in document.items() if v is not None}


class _TransportOutcome:
    """Domain ``AgentOutcome``'un worker içi taşıma görünümü."""

    def __init__(self, *, kind: str, domain: AgentOutcome) -> None:
        self.kind = kind
        self.domain = domain

    def __getattr__(self, name: str) -> Any:
        return getattr(self.domain, name)


def _clean(**kwargs: Any) -> dict[str, Any]:
    """None değerli anahtarları atar: ``TransportModel`` açık null taşımaz."""

    return {key: value for key, value in kwargs.items() if value is not None}


def _code_value(code: Any) -> str:
    """``AgentErrorCode`` veya düz metin hata kodu → sözleşme değeri."""

    return str(getattr(code, "value", code))


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(value: datetime) -> str:
    """Domain zamanını B1 ``UtcIsoString``'e çevirir (null taşınmaz kuralı)."""

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
