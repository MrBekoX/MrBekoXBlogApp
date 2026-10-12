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

Kaynaklar: [LG-PERSISTENCE#C2] kalıcı checkpointer, süreç restart'ında
checkpoint korunur; [PY-ASYNCIO#C2] iptal istisnası bastırılmaz;
[PG-ISOLATION#C2] Read Committed'ta koşullu UPDATE güncel satırda
değerlendirilir (fencing guard'ının dayanağı).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent_core.checkpoint.resume import load_resume_payload
from agent_core.checkpoint.store import FileCheckpointStore
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
    ConversationTurn,
    ExecutionContext,
    ModePreference,
    ProgressKind,
    RunStatus,
    SourceReference,
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

from .contracts import AgentEnvelope, Producer, SCHEMA_VERSION
from .contracts.payloads import (
    AgentActionProposalContent,
    AgentExecutionRequestedV1,
    AgentRunCompletedV1,
    AgentRunFailedV1,
    AgentRunPartiallyCompletedV1,
    AgentSourceReference,
    AgentUsageRecord,
)
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
    ``config_error`` döner (kayıtsız modele düşmez).
    """

    model: ModelProvider
    router_model: ModelProvider | None = None
    retriever: Any | None = None
    content: Any | None = None
    budget: BudgetStore | None = None
    web_tools: dict[str, Any] | None = None
    checkpoint_store: CheckpointStorePort | None = None
    content_state: Any | None = None
    profile_repository: Any | None = None
    project_repository: Any | None = None
    article_catalog: Any | None = None


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


class _WorkerProgressSink(ProgressSink):
    """DomainProgress → B5 olay yayıncısı + lease heartbeat."""

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
    ) -> None:
        self._ids = (run_id, conversation_id, correlation_id, causation_id)
        self._attempt = execution_attempt
        self._publisher = publisher
        self._watch = watch

    async def publish(self, event: Any) -> None:
        await self._watch.heartbeat()  # lease ilerlemeye bağlı (plan B6)
        if self._publisher is None:
            return
        run_id, conversation_id, correlation_id, causation_id = self._ids
        kind = event.kind if isinstance(event.kind, str) else event.kind.value
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
        result = await self._publisher.publish_progress(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            kind=kind,
            message=event.message,
            execution_attempt=self._attempt,
            causation_id=causation_id,
        )
        if isinstance(result, ThrottledProgress):
            logger.debug("ilerleme seyrekleştirildi: run=%s kind=%s", run_id, kind)


def _to_transport_citation(citation: SourceReference) -> AgentSourceReference:
    """Domain ``SourceReference`` → B1 ``AgentSourceReference`` (alan kümeleri birebir)."""

    accessed = citation.accessed_at
    return AgentSourceReference(
        kind=citation.kind,
        article_id=citation.article_id,
        article_revision=citation.article_revision,
        chunk_index=citation.chunk_index,
        url=citation.url,
        title=citation.title,
        accessed_at=(
            accessed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if accessed is not None
            else None
        ),
    )


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


def _to_transport_outcome_dataclass(kind: str, outcome: AgentOutcome) -> TransportAgentOutcome:
    """Domain sonucunu B5 yayıncısının veri sınıfına çevirir (scope kontrolü için).

    Yalnız ``AgentEventPublisher._check_source_scope``'un okuduğu alanlar
    doldurulur; kuralın tek kaynağı events.py'de kalır (kopyalanmaz).
    """

    return TransportAgentOutcome(
        kind=kind,  # type: ignore[arg-type]
        selected_mode=outcome.selected_mode.value,
        source_scope=outcome.source_scope.value if outcome.source_scope else None,
        citations=tuple(_to_transport_citation(c) for c in outcome.citations),
    )


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

        try:
            return await self._execute_claimed(
                claimed,
                collab_input=collab_input,
                validated_result=validated_result,
            )
        except WorkerAborted as abort:
            logger.warning("yürütme terminal'siz bırakıldı: run=%s (%s)", claimed.run_id, abort)
            return CycleResult(
                run_id=claimed.run_id,
                action=abort.args[0] if abort.args else "aborted",
                detail=str(abort),
                execution_attempt=claimed.execution_attempt,
                fencing_token=claimed.fencing_token,
                recovered=claimed.recovered,
            )

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

            payload_model = AgentExecutionRequestedV1.model_validate(claimed.payload)
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
            )

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
                    checkpoint=self._checkpoint,
                    execution_id=stable_execution_id(run_id),
                )
                if (
                    prepared.route.selected_mode is AgentMode.DEEP_RESEARCH
                    and claimed.queue_class != QUEUE_CLASS_RESEARCH
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

            return await self._finish_outcome(claimed, outcome=outcome, metered=metered)
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

    async def _try_resume(
        self,
        claimed: ClaimedJob,
        *,
        metered: _MeteredModel,
        sink: _WorkerProgressSink,
        cancel: _WorkerCancel,
        collab_input: Any | None = None,
        validated_result: Any | None = None,
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
        try:
            _envelope, payload = await load_resume_payload(
                self._checkpoint, claimed.run_id, None, execution_id=execution_id
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
        if (
            stored.route.selected_mode is AgentMode.DEEP_RESEARCH
            and claimed.queue_class != QUEUE_CLASS_RESEARCH
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
        outcome = await resume(
            ResumeRequest(
                run_id=claimed.run_id,
                execution_id=execution_id,
                deadline_seconds=remaining,
                collab_input=collab_input,
                validated_result=validated_result,
            ),
            checkpoint=self._checkpoint,
            model=metered,
            retriever=self._deps.retriever,
            content=self._deps.content,
            budget=self._deps.budget,
            progress=sink,
            cancel=cancel,
            web_tools=self._deps.web_tools,
            profile_repository=self._deps.profile_repository,
            project_repository=self._deps.project_repository,
            article_catalog=self._deps.article_catalog,
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
        return await execute_plan(
            prepared,
            model=metered,
            retriever=self._deps.retriever,
            content=self._deps.content,
            budget=self._deps.budget,
            progress=sink,
            cancel=cancel,
            web_tools=self._deps.web_tools,
            profile_repository=self._deps.profile_repository,
            project_repository=self._deps.project_repository,
            article_catalog=self._deps.article_catalog,
            collab_input=collab_input,
            validated_result=validated_result,
        )

    # ------------------------------------------------- iptal terminali + guard

    def _ensure_execution_allowed(self, payload: AgentExecutionRequestedV1) -> None:
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
        self, claimed: ClaimedJob, *, outcome: AgentOutcome, metered: _MeteredModel
    ) -> CycleResult:
        """Domain sonucunu transport terminaline çevirip guard'la yazar."""

        run_id = claimed.run_id
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

        if kind in ("completed", "partially_completed"):
            # B5 yayın kuralının TEK kaynağına delegasyon: scope/citation
            # uyuşmazlığında terminal completed YAYINLANMAZ; iş anlaşılır
            # validation_error ile failed kapanır (sonuç çekirdekten bozuk
            # geldiğinde sessiz yayın yok).
            try:
                AgentEventPublisher._check_source_scope(
                    _to_transport_outcome_dataclass(kind, outcome)
                )
            except EventPublishError as error:
                return await self._fail_now(
                    claimed,
                    error_code="validation_error",
                    error_message=f"terminal sonuç yayın kuralına aykırı: {error}",
                )

        terminal_envelope = self._terminal_envelope(claimed, transport_outcome)
        result_json = self._result_json(claimed, transport_outcome, metered)

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
        self, claimed: ClaimedJob, *, error_code: str, error_message: str
    ) -> CycleResult:
        """Yürütme başlamadan/orta yolda anlaşılır terminal failed üretir."""

        envelope = AgentEnvelope(
            message_id=str(uuid.uuid4()),
            message_type="agent.run.failed",
            schema_version=SCHEMA_VERSION,
            run_id=claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
            occurred_at=_utcnow_str(),
            producer=Producer.AGENT_PY,
            payload=AgentRunFailedV1(
                event_sequence=0,
                execution_attempt=claimed.execution_attempt,
                fencing_token=str(claimed.fencing_token),
                error_code=error_code,
                error_message=error_message,
            ).model_dump(exclude_none=True),
        )
        result_json = {
            "outcome": "failed",
            "error_code": error_code,
            "error_message": error_message,
            "execution_id": stable_execution_id(claimed.run_id),
            "execution_attempt": claimed.execution_attempt,
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
        """Execute payload'ını çekirdek ``ExecutionContext``'ine çevirir.

        Konuşma geçmişi backend snapshot'ından AYNEN taşınır (plan B6:
        "konuşma cevap geçmişini backend snapshot'ına göre koruma"); worker
        tur eklemez/çıkarmaz. ``article_snapshot`` bilinçli None'dur (K7):
        çekirdek yalnız referansla çalışır; içerik getirmesi B8 pgvector
        entegrasyonundan sonra retriever bağlanarak etkinleşir.
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
        )

    def _terminal_envelope(self, claimed: ClaimedJob, transport: "_TransportOutcome") -> AgentEnvelope:
        """Terminal olay zarfını B1 payload modeliyle kurar (sıra DB'de tahsis edilir)."""

        domain = transport.domain
        common: dict[str, Any] = {
            "event_sequence": 0,  # gerçek değer complete/fail transaction'ında yazılır
            "execution_attempt": claimed.execution_attempt,
            "fencing_token": str(claimed.fencing_token),
        }
        usage = _to_transport_usage(claimed.run_id, domain.usage)
        citations = [_to_transport_citation(c) for c in domain.citations]
        if transport.kind == "completed":
            payload_model: Any = AgentRunCompletedV1(
                **_clean(
                    **common,
                    selected_mode=domain.selected_mode.value,
                    answer=domain.answer,
                    report=domain.report,
                    citations=citations,
                    source_scope=domain.source_scope.value,
                    unresolved_questions=list(domain.unresolved_questions),
                    usage=usage,
                    action_proposal=None,
                )
            )
        elif transport.kind == "partially_completed":
            payload_model = AgentRunPartiallyCompletedV1(
                **_clean(
                    **common,
                    selected_mode=domain.selected_mode.value,
                    answer=domain.answer,
                    report=domain.report,
                    citations=citations,
                    source_scope=domain.source_scope.value,
                    unresolved_questions=list(domain.unresolved_questions),
                    usage=usage,
                )
            )
        else:
            payload_model = AgentRunFailedV1(
                **_clean(
                    **common,
                    error_code=domain.error_code.value if domain.error_code else "provider_error",
                    error_message=domain.error_message,
                    selected_mode=domain.selected_mode.value,
                    usage=usage,
                )
            )
        return AgentEnvelope(
            message_id=str(uuid.uuid4()),
            message_type=f"agent.run.{transport.kind}",
            schema_version=SCHEMA_VERSION,
            run_id=claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
            occurred_at=_utcnow_str(),
            producer=Producer.AGENT_PY,
            payload=payload_model.model_dump(exclude_none=True),
        )

    def _nonterminal_envelope(
        self, message_type: str, claimed: ClaimedJob, **payload_fields: Any
    ) -> AgentEnvelope:
        return AgentEnvelope(
            message_id=str(uuid.uuid4()),
            message_type=message_type,
            schema_version=SCHEMA_VERSION,
            run_id=claimed.run_id,
            conversation_id=claimed.conversation_id,
            correlation_id=claimed.envelope.correlation_id,
            causation_id=claimed.origin_message_id,
            occurred_at=_utcnow_str(),
            producer=Producer.AGENT_PY,
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
        self, claimed: ClaimedJob, transport: "_TransportOutcome", metered: _MeteredModel
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


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(value: datetime) -> str:
    """Domain zamanını B1 ``UtcIsoString``'e çevirir (null taşınmaz kuralı)."""

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
