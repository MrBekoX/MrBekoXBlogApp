"""İçerik tüketimi (B8): ``agent.content.q`` üzerinde makale olayları ve ilk senkron.

Kurallar (plan B8, satır 448-465):
- Consumer yeni revizyonu uygular; ESKİ revizyonu yok sayır (olayların ters gelmesi
  broker teslim sırasıyla değil, backend-atandı monoton ``article_revision`` ile çözülür).
- Aynı revizyon farklı content_hash ile gelirse çatışma GÖRÜNÜR kaydedilir
  (``ContentSyncState.conflicts`` + ``logger.error``); mevcut durum korunur.
- Kaldırma tombstone'u (action=unpublished) A3 indeksinden parça geçersizleme +
  önbellek düşürme üretir (``InMemoryContentIndex.remove_article`` kaldırma iş modeli
  ve arama önbelleğini tek çağrıda düşürür).
- Execution komutunun snapshot'ı, projection'ın bildiği daha yeni bir kaldırma
  revizyonundan eskiyse yürütme reddedilir (``ensure_execution_allowed`` →
  ``StaleExecutionRejected``); kontrol B6 worker bağlantı noktasıdır.
- İlk senkron (ContentSnapshotBatchV1/CompletedV1) referans taşır, içerik gömmez (K7).
  Senkron sürerken olan değişiklikler KAYBOLMAZ: canlı olay daha yüksek revision'lı
  gelir ve batch referansı stale sayılır; tamamlanmamış snapshot (eksik batch veya
  yabancı completed) indeks SİLMEZ — indeks bu fazda additive kalır.
- Taslak içerik bu kuyruğa hiç gelmez: backend yalnız yayımlanmış içerik anı olayı üretir.

Sözleşme sınırı: her teslim ``parse_envelope`` (B1) ile doğrulanır; içerik kuyruğuna
düşen içerik-dışı tür politik ihlalidir (``ContentPolicyError`` → B2 consumer tabanı
DLX'e yönlendirir). ACK, ``BrokerConsumer`` işleme normal tamamlandığında verilir.

Kaynaklar: [ENG-OUTBOX#C2] relay tekrarı consumer idempotentliği gerektirir;
[PG-ISOLATION#C2] eşzamanlı güncellemede son yazanın kazanımı uygulama kuralıdır —
burada "son yayımlanmış an" en yüksek revision'dır.
"""

from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from contextlib import nullcontext
from typing import Any, Callable, Protocol

from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from .contracts import ArticleContentChangedV1, ContentSnapshotBatchV1, ContentSnapshotCompletedV1, ParsedEnvelope, ProjectContentChangedV1, ProfileContentChangedV1, parse_envelope
from .consumer import BrokerConsumer
from .settings import BrokerSettings
from .topology import CONTENT_QUEUE
from agent_core.errors import AgentErrorCode, PortError
from agent_core.budget.embedding import embedding_budget_scope
from agent_core.ports import BudgetStore

__all__ = [
    "CONTENT_MESSAGE_TYPES",
    "ContentApplyOutcome",
    "ContentIndexProjector",
    "ContentProjectionResult",
    "ContentConsumerService",
    "ContentPolicyError",
    "ContentRevisionConflict",
    "ContentSyncState",
    "ContentSyncReport",
    "StaleExecutionRejected",
    "build_content_consumer",
]

logger = logging.getLogger(__name__)

#: ``agent.content.q`` binding'leriyle birebir (B2 topology); diğer türler politika ihlalidir.
CONTENT_MESSAGE_TYPES = frozenset(
    {
        "content.article.changed",
        "content.sync.batch",
        "content.sync.completed",
        "content.profile.changed",
        "content.project.changed",
    }
)


class ContentPolicyError(Exception):
    """İçerik kuyruğuna içerik-dışı/Politika-dışı mesaj geldi (kalıcı ihlal → DLX)."""


class StaleExecutionRejected(Exception):
    """Execution komutunun makale snapshot'ı, projection'ın bildiği kaldırma
    revizyonundan eski; komut yürütülmez (plan B8: "eski komutu yürütmesin")."""

    def __init__(self, article_id: str, command_revision: int, removal_revision: int) -> None:
        super().__init__(
            f"eski komut reddedildi: article {article_id} revision {command_revision}, "
            f"bilinen kaldırma revizyonu {removal_revision}"
        )
        self.article_id = article_id
        self.command_revision = command_revision
        self.removal_revision = removal_revision


@dataclass(frozen=True)
class ContentApplyOutcome:
    """Tek teslimin/batch kaleminin işlenme sonucu (gözlemlenebilirlik için)."""

    message_type: str
    applied: bool
    reason: str
    article_id: str | None = None
    revision: int | None = None


@dataclass(frozen=True)
class ContentRevisionConflict:
    """Aynı revizyonun farklı hash ile gelmesi; durum korunur, çatışma görünürdür."""

    article_id: str
    revision: int
    known_hash: str
    incoming_hash: str
    message_id: str
    detected_at: str


@dataclass(frozen=True)
class ContentSyncReport:
    """Bir senkronun consumer tarafındaki ilerleme özeti."""

    sync_id: str
    total_batches: int
    received_batches: int
    applied_items: int
    stale_items: int
    completed: bool
    incomplete: bool
    item_count_mismatch: bool


@dataclass(frozen=True)
class _ArticleState:
    """Makalenin bilinen son yayımlanmış içerik anı."""

    revision: int
    content_hash: str


@dataclass
class _SyncState:
    """Tek sync_id'nin batch ilerlemesi; referans uygulaması canlı olay kurallarını kullanır."""

    total_batches: int
    received_batches: set[int] = field(default_factory=set)
    applied_items: int = 0
    stale_items: int = 0
    processed_items: int = 0
    completed: bool = False
    completed_item_count: int | None = None
    completed_message_id: str | None = None


class _ContentBodyFetcher(Protocol):
    """Fetch the latest published snapshot for a reference-only content event."""

    async def fetch(self, article_id: str, article_revision: int) -> Any:
        ...


@dataclass(frozen=True)
class ContentProjectionResult:
    """Durably indexed state observed while resolving a content event."""

    effect: str
    revision: int
    content_hash: str | None = None
    removed: bool = False


class ContentIndexProjector:
    """Persist real content embeddings and removal tombstones before ACK.

    Events carry references, so a later backend snapshot may supersede an old
    delivery. The latest snapshot is indexed; equal-revision hash conflicts are
    rejected and never committed to the consumer's revision state.
    """

    def __init__(
        self,
        index: Any,
        *,
        embedding_provider: Any,
        model_config: Any,
        content_fetcher: _ContentBodyFetcher | None = None,
        canonical_url_template: str | None = None,
        embedding_budget_factory: Callable[[Any], tuple[str, BudgetStore]] | None = None,
    ) -> None:
        self._index = index
        self._embedding_provider = embedding_provider
        self._model_config = model_config
        self._content_fetcher = content_fetcher
        self._canonical_url_template = canonical_url_template
        self._embedding_budget_factory = embedding_budget_factory

    async def on_article_applied(
        self,
        state: ContentSyncState,
        article_id: str,
        revision: int,
        content_hash: str,
        *,
        message_id: str = "",
    ) -> ContentProjectionResult:
        if self._content_fetcher is None:
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                "Content projection requires a real content fetcher.",
                port="ContentIndexProjector",
            )
        try:
            snapshot = await self._content_fetcher.fetch(article_id, revision)
        except PortError as error:
            if error.code is not AgentErrorCode.NOT_FOUND:
                raise
            # The backend's current published view is authoritative. Persist a
            # tombstone before acknowledging an obsolete update/sync reference.
            await self.on_article_removed(article_id, revision)
            return ContentProjectionResult("missing_removed", revision, removed=True)
        snapshot_revision = int(snapshot.article_revision)
        if str(snapshot.article_id) != article_id:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "Fetched article does not match the content reference.",
                port="ContentIndexProjector",
            )
        if snapshot_revision < revision:
            raise PortError(
                AgentErrorCode.STALE_SNAPSHOT,
                "Fetched article revision is older than the content event; retry after the backend catches up.",
                port="ContentIndexProjector",
                retryable=True,
            )
        if snapshot_revision == revision and str(snapshot.content_hash) != content_hash:
            state.record_conflict(
                article_id=article_id,
                revision=revision,
                known_hash=content_hash,
                incoming_hash=str(snapshot.content_hash),
                message_id=message_id or "content_fetch",
            )
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "Fetched article hash conflicts with the content event at the same revision.",
                port="ContentIndexProjector",
            )
        scope = (embedding_budget_scope(*self._embedding_budget_factory(snapshot))
                 if self._embedding_budget_factory is not None else nullcontext())
        with scope:
            result = await self._index.index_article(
                snapshot,
                embedding_provider=self._embedding_provider,
                model_config=self._model_config,
                canonical_url_template=self._canonical_url_template,
            )
        effect = "superseded_indexed" if snapshot_revision > revision else "indexed"
        return ContentProjectionResult(
            f"{effect}:{result.chunk_count}", snapshot_revision, str(snapshot.content_hash)
        )

    async def on_article_removed(self, article_id: str, revision: int) -> tuple[bool, int]:
        """Tombstone'u indekse uygular: (removed, removed_chunks) döndürür."""

        result = await self._index.remove_article(article_id, article_revision=revision)
        return result.removed, result.removed_chunks


class ContentSyncState:
    """İçerik projection durumu: makale anları, kaldırmalar, çatışmalar, senkron ilerlemesi.

    Tek yazıcı (consumer döngüsü) varsayımı A3 indeksiyle aynıdır; okuma metotları
    worker'ın stale komut kontrolü içindir.
    """

    def __init__(self) -> None:
        self._articles: dict[str, _ArticleState] = {}
        self._removals: dict[str, int] = {}
        self._conflicts: list[ContentRevisionConflict] = []
        self._syncs: dict[str, _SyncState] = {}
        self._orphan_completions: list[str] = []
        self._profile: _ArticleState | None = None
        self._projects: dict[str, _ArticleState] = {}

    def restore_articles(self, rows: Any) -> None:
        """Restore revision/tombstone guards from the persistent content index.

        Startup invokes this before accepting deliveries. Conflicting restored
        rows fail closed instead of allowing stale commands to bypass removal.
        """
        for row in rows:
            article_id = str(row["article_id"])
            revision = int(row["revision"])
            if revision < 0:
                raise PortError(
                    AgentErrorCode.CONFIG_ERROR,
                    "Persistent content index contains a negative revision.",
                    port="ContentSyncState",
                )
            if row["deleted"]:
                self._apply_removal(article_id, revision)
            else:
                content_hash = row["content_hash"]
                if not isinstance(content_hash, str) or len(content_hash) != 64 or any(
                    value not in "0123456789abcdefABCDEF" for value in content_hash
                ):
                    raise PortError(
                        AgentErrorCode.CONFIG_ERROR,
                        "Persistent content index contains an invalid published content hash.",
                        port="ContentSyncState",
                    )
                outcome = self._apply_published(article_id, revision, content_hash)
                if outcome.reason == "revision_conflict":
                    raise PortError(
                        AgentErrorCode.CONFIG_ERROR,
                        "Persistent content index has conflicting revisions; repair before starting the worker.",
                        port="ContentSyncState",
                    )

    def preview_article_changed(self, payload: ArticleContentChangedV1) -> ContentApplyOutcome:
        """Evaluate delivery ordering without committing an unprojected revision."""
        article_id = str(payload.article_id)
        revision = int(payload.article_revision)
        if payload.action == "unpublished":
            return self._apply_removal(article_id, revision, commit=False)
        return self._apply_published(article_id, revision, str(payload.content_hash), commit=False)

    def begin_snapshot_batch(self, payload: ContentSnapshotBatchV1) -> bool:
        # Keep in-progress metadata so a concurrent completion received between
        # retry attempts remains attached to this sync. No article revision or
        # successful batch receipt is committed here.
        sync = self._syncs.setdefault(str(payload.sync_id), _SyncState(total_batches=int(payload.total_batches)))
        if sync.total_batches != int(payload.total_batches):
            raise ContentPolicyError("Content sync batch count changed for the same sync ID.")
        return int(payload.batch_index) in sync.received_batches

    def record_projected_batch(
        self, payload: ContentSnapshotBatchV1, outcomes: list[ContentApplyOutcome]
    ) -> ContentApplyOutcome:
        """Mark a batch received only after every reference was projected."""
        sync_id = str(payload.sync_id)
        batch_index = int(payload.batch_index)
        sync = self._syncs.setdefault(sync_id, _SyncState(total_batches=int(payload.total_batches)))
        if sync.total_batches != int(payload.total_batches):
            raise ContentPolicyError("Content sync batch count changed for the same sync ID.")
        if batch_index in sync.received_batches:
            return ContentApplyOutcome("content.sync.batch", False, "duplicate_batch", sync_id, batch_index)
        # A replay after a partly successful batch sees already persisted items
        # as duplicates. They still count as successfully processed references.
        applied = sum(outcome.applied or outcome.reason == "duplicate" for outcome in outcomes)
        stale = sum(outcome.reason in {"stale_revision", "stale_after_removal"} for outcome in outcomes)
        sync.applied_items += applied
        sync.stale_items += stale
        sync.processed_items += len(payload.items)
        sync.received_batches.add(batch_index)
        return ContentApplyOutcome(
            "content.sync.batch", True,
            f"batch_index={batch_index} applied={applied} stale={stale}", sync_id, batch_index,
        )

    # -- okuma -----------------------------------------------------------

    @property
    def conflicts(self) -> tuple[ContentRevisionConflict, ...]:
        return tuple(self._conflicts)

    @property
    def orphan_completions(self) -> tuple[str, ...]:
        return tuple(self._orphan_completions)

    def known_revision(self, article_id: str) -> tuple[int, str] | None:
        state = self._articles.get(article_id)
        return (state.revision, state.content_hash) if state else None

    def latest_removal_revision(self, article_id: str) -> int | None:
        return self._removals.get(article_id)

    def sync_report(self, sync_id: str) -> ContentSyncReport | None:
        sync = self._syncs.get(sync_id)
        if sync is None:
            return None
        return ContentSyncReport(
            sync_id=sync_id,
            total_batches=sync.total_batches,
            received_batches=len(sync.received_batches),
            applied_items=sync.applied_items,
            stale_items=sync.stale_items,
            completed=sync.completed,
            incomplete=sync.completed and len(sync.received_batches) < sync.total_batches,
            item_count_mismatch=(
                sync.completed
                and sync.completed_item_count is not None
                and sync.completed_item_count != sync.processed_items
            ),
        )

    def profile_revision(self) -> tuple[int, str] | None:
        return (self._profile.revision, self._profile.content_hash) if self._profile else None

    def project_revision(self, project_id: str) -> tuple[int, str] | None:
        state = self._projects.get(project_id)
        return (state.revision, state.content_hash) if state else None

    # -- komut kontrolü ----------------------------------------------------

    def ensure_execution_allowed(self, article_id: str, article_revision: int) -> None:
        """Execution komutunun snapshot revizyonunu projection'a karşı denetler.

        Bilinen kaldırma revizyonu >= komut revizyonu ise komut yürütülmez: snapshot'ın
        referans verdiği yayımlanmış an, projection'ın bildiği kaldırmadan eski veya o
        kaldırmanın kendisidir (plan B8; main prompt: "yayından kaldırılmış içeriğe
        dayanan geç sonuç sunulmaz").
        """

        removal = self._removals.get(article_id)
        if removal is not None and article_revision <= removal:
            raise StaleExecutionRejected(article_id, article_revision, removal)

    # -- yazma -------------------------------------------------------------

    def record_conflict(
        self,
        *,
        article_id: str,
        revision: int,
        known_hash: str,
        incoming_hash: str,
        message_id: str = "",
    ) -> ContentRevisionConflict:
        conflict = ContentRevisionConflict(
            article_id=article_id,
            revision=revision,
            known_hash=known_hash,
            incoming_hash=incoming_hash,
            message_id=message_id,
            detected_at=datetime.now(timezone.utc).isoformat(),
        )
        self._conflicts.append(conflict)
        logger.error(
            "içerik çatışması: aynı article_revision farklı content_hash ile geldi "
            "(article=%s revision=%s bilinen=%s gelen=%s message_id=%s); mevcut durum korundu",
            article_id, revision, known_hash, incoming_hash, message_id,
        )
        return conflict

    def apply_article_changed(self, payload: ArticleContentChangedV1, *, message_id: str = "") -> ContentApplyOutcome:
        article_id = str(payload.article_id)
        revision = int(payload.article_revision)
        if payload.action == "unpublished":
            return self._apply_removal(article_id, revision, message_id=message_id)
        return self._apply_published(article_id, revision, str(payload.content_hash), message_id=message_id)

    def apply_snapshot_batch(self, payload: ContentSnapshotBatchV1, *, message_id: str = "") -> ContentApplyOutcome:
        sync_id = str(payload.sync_id)
        batch_index = int(payload.batch_index)
        sync = self._syncs.setdefault(sync_id, _SyncState(total_batches=int(payload.total_batches)))
        if batch_index in sync.received_batches:
            return ContentApplyOutcome(
                message_type="content.sync.batch",
                applied=False,
                reason="duplicate_batch",
                article_id=sync_id,
                revision=batch_index,
            )
        sync.received_batches.add(batch_index)
        applied = 0
        stale = 0
        for item in payload.items:
            outcome = self._apply_published(
                str(item.article_id), int(item.article_revision), str(item.content_hash),
                message_id=message_id, sync=sync,
            )
            if outcome.applied:
                applied += 1
            elif outcome.reason == "stale_revision":
                stale += 1
        sync.processed_items += len(payload.items)
        return ContentApplyOutcome(
            message_type="content.sync.batch",
            applied=True,
            reason=f"batch_index={batch_index} applied={applied} stale={stale}",
            article_id=sync_id,
            revision=batch_index,
        )

    def apply_snapshot_completed(self, payload: ContentSnapshotCompletedV1, *, message_id: str = "") -> ContentApplyOutcome:
        sync_id = str(payload.sync_id)
        sync = self._syncs.get(sync_id)
        if sync is None:
            # Yabancı/eksik completed: TAMAMLANMAMIŞ SNAPSHOT INDEKS SİLMEZ (plan B8);
            # görünür kayıt düşer.
            self._orphan_completions.append(sync_id)
            logger.warning(
                "tamamlanmamış senkron completed'ı: sync_id=%s bilinen batch yok; indeks dokunulmadı (message_id=%s)",
                sync_id, message_id,
            )
            return ContentApplyOutcome(
                message_type="content.sync.completed",
                applied=False,
                reason="orphan_completion",
                article_id=sync_id,
                revision=None,
            )
        sync.completed = True
        sync.completed_item_count = int(payload.item_count)
        sync.completed_message_id = message_id
        received = len(sync.received_batches)
        incomplete = received < sync.total_batches
        mismatch = sync.completed_item_count != sync.processed_items
        if incomplete or mismatch:
            logger.warning(
                "senkron eksik kapandı: sync_id=%s batch=%d/%d uygulanan=%d completed_item_count=%d; "
                "indeks additive kalır, silme yapılmaz (message_id=%s)",
                sync_id, received, sync.total_batches, sync.applied_items, sync.completed_item_count, message_id,
            )
        return ContentApplyOutcome(
            message_type="content.sync.completed",
            applied=True,
            reason=f"batches={received}/{sync.total_batches} items={sync.applied_items}"
            + (" incomplete" if incomplete else "")
            + (" item_count_mismatch" if mismatch else ""),
            article_id=sync_id,
            revision=None,
        )

    def apply_profile_changed(self, payload: ProfileContentChangedV1, *, message_id: str = "") -> ContentApplyOutcome:
        revision = int(payload.profile_revision)
        content_hash = str(payload.content_hash)
        current = self._profile
        if current is not None:
            if revision < current.revision:
                return ContentApplyOutcome("content.profile.changed", False, "stale_revision", "profile", revision)
            if revision == current.revision:
                if current.content_hash == content_hash:
                    return ContentApplyOutcome("content.profile.changed", False, "duplicate", "profile", revision)
                self.record_conflict(
                    article_id="profile", revision=revision,
                    known_hash=current.content_hash, incoming_hash=content_hash, message_id=message_id,
                )
                return ContentApplyOutcome("content.profile.changed", False, "revision_conflict", "profile", revision)
        self._profile = _ArticleState(revision=revision, content_hash=content_hash)
        return ContentApplyOutcome("content.profile.changed", True, "applied", "profile", revision)

    def apply_project_changed(self, payload: ProjectContentChangedV1, *, message_id: str = "") -> ContentApplyOutcome:
        project_id = str(payload.project_id)
        revision = int(payload.project_revision)
        content_hash = str(payload.content_hash)
        current = self._projects.get(project_id)
        if current is not None:
            if revision < current.revision:
                return ContentApplyOutcome("content.project.changed", False, "stale_revision", project_id, revision)
            if revision == current.revision:
                if current.content_hash == content_hash:
                    return ContentApplyOutcome("content.project.changed", False, "duplicate", project_id, revision)
                self.record_conflict(
                    article_id=project_id, revision=revision,
                    known_hash=current.content_hash, incoming_hash=content_hash, message_id=message_id,
                )
                return ContentApplyOutcome("content.project.changed", False, "revision_conflict", project_id, revision)
        self._projects[project_id] = _ArticleState(revision=revision, content_hash=content_hash)
        return ContentApplyOutcome("content.project.changed", True, "applied", project_id, revision)

    # -- iç kural: yayımlanmış an uygulaması (canlı olay + senkron referansı ortak) --

    def _apply_published(
        self,
        article_id: str,
        revision: int,
        content_hash: str,
        *,
        message_id: str = "",
        sync: _SyncState | None = None,
        commit: bool = True,
    ) -> ContentApplyOutcome:
        removal = self._removals.get(article_id)
        if removal is not None and revision <= removal:
            # Kaldırılmış an ve öncesi geri getirilemez: makale kaldırmadan sonra
            # yeniden yayımlanmışsa olayı daha yüksek revision ile gelir.
            if sync is not None:
                sync.stale_items += 1
            return ContentApplyOutcome("content.article.changed", False, "stale_after_removal", article_id, revision)
        current = self._articles.get(article_id)
        if current is not None and revision < current.revision:
            if sync is not None:
                sync.stale_items += 1
            return ContentApplyOutcome("content.article.changed", False, "stale_revision", article_id, revision)
        if current is not None and revision == current.revision:
            if current.content_hash == content_hash:
                return ContentApplyOutcome("content.article.changed", False, "duplicate", article_id, revision)
            if commit:
                self.record_conflict(
                    article_id=article_id, revision=revision,
                    known_hash=current.content_hash, incoming_hash=content_hash, message_id=message_id,
                )
            return ContentApplyOutcome("content.article.changed", False, "revision_conflict", article_id, revision)
        if commit:
            self._articles[article_id] = _ArticleState(revision=revision, content_hash=content_hash)
        if sync is not None:
            sync.applied_items += 1
        return ContentApplyOutcome("content.article.changed", True, "applied", article_id, revision)

    def _apply_removal(
        self, article_id: str, revision: int, *, message_id: str = "", commit: bool = True
    ) -> ContentApplyOutcome:
        current = self._articles.get(article_id)
        if current is not None and revision < current.revision:
            # Makale kaldırmadan SONRA yeniden yayımlanmış; eski kaldırma geçersizdir.
            return ContentApplyOutcome("content.article.changed", False, "stale_revision", article_id, revision)
        removal = self._removals.get(article_id)
        if removal is not None and revision <= removal:
            # Tekrar teslim/idempotent: aynı veya daha eski kaldırma; indeks zaten boş.
            return ContentApplyOutcome("content.article.changed", False, "duplicate_removal", article_id, revision)
        if commit:
            self._removals[article_id] = revision
            self._articles.pop(article_id, None)
            logger.info(
                "kaldırma tombstone'u uygulandı: article=%s revision=%s (message_id=%s)",
                article_id, revision, message_id,
            )
        return ContentApplyOutcome("content.article.changed", True, "removed", article_id, revision)


class ContentConsumerService:
    """``agent.content.q`` teslimlerini B1 doğrulamadan geçirip projection'a uygulayan servis.

    ``parse_envelope`` tür kaydındaki üretici (backend-net/test-executor) ve yön
    (backend→agent) kurallarını zaten doğrular; burada kuyruk tür politikası eklenir.
    Kalıcı sözleşme/politika ihlali istisna ile yükselir → B2 ``BrokerConsumer`` mesajı
    DLX'e yönlendirir (requeue döngüsü yok).
    """

    def __init__(
        self,
        state: ContentSyncState,
        *,
        projector: ContentIndexProjector | None = None,
    ) -> None:
        self._state = state
        self._projector = projector
        self._delivery_lock = asyncio.Lock()

    @property
    def state(self) -> ContentSyncState:
        return self._state

    @property
    def projector(self) -> ContentIndexProjector | None:
        return self._projector

    @projector.setter
    def projector(self, value: ContentIndexProjector | None) -> None:
        self._projector = value

    async def handle_delivery(self, raw: bytes, message: AbstractIncomingMessage) -> ContentApplyOutcome:
        parsed = parse_envelope(raw)
        for attempt in range(3):
            try:
                return await self.handle_parsed(parsed, message_id=_safe_message_id(message))
            except PortError as error:
                if not error.retryable or attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise AssertionError("Unreachable content retry state")

    async def handle_parsed(self, parsed: ParsedEnvelope, *, message_id: str = "") -> ContentApplyOutcome:
        # Broker prefetch may dispatch callbacks concurrently. Revision preview,
        # durable projection, and in-memory commit form one serialized operation.
        async with self._delivery_lock:
            return await self._handle_parsed(parsed, message_id=message_id)

    async def _handle_parsed(self, parsed: ParsedEnvelope, *, message_id: str = "") -> ContentApplyOutcome:
        message_type = parsed.spec.message_type
        if message_type not in CONTENT_MESSAGE_TYPES:
            raise ContentPolicyError(
                f"içerik kuyruğu yalnız içerik olayları kabul eder; gelen: {message_type}"
            )

        payload = parsed.payload
        if isinstance(payload, ArticleContentChangedV1):
            return await self._apply_article(payload, message_id=message_id)
        if isinstance(payload, ContentSnapshotBatchV1):
            if self._state.begin_snapshot_batch(payload):
                return ContentApplyOutcome(
                    "content.sync.batch", False, "duplicate_batch", str(payload.sync_id), int(payload.batch_index)
                )
            outcomes = []
            for item in payload.items:
                event = ArticleContentChangedV1(
                    article_id=item.article_id,
                    article_revision=item.article_revision,
                    content_hash=item.content_hash,
                    action="updated",
                )
                outcomes.append(await self._apply_article(event, message_id=message_id))
            return self._state.record_projected_batch(payload, outcomes)
        if isinstance(payload, ContentSnapshotCompletedV1):
            return self._state.apply_snapshot_completed(payload, message_id=message_id)
        if isinstance(payload, ProfileContentChangedV1):
            return self._state.apply_profile_changed(payload, message_id=message_id)
        if isinstance(payload, ProjectContentChangedV1):
            return self._state.apply_project_changed(payload, message_id=message_id)
        raise ContentPolicyError(f"içerik kuyruğunda beklenmeyen payload türü: {type(payload).__name__}")

    async def _apply_article(
        self,
        payload: ArticleContentChangedV1,
        *,
        message_id: str,
    ) -> ContentApplyOutcome:
        if payload.action == "updated" and payload.content_hash is None:
            raise ContentPolicyError("Published content events require a content hash.")
        outcome = self._state.preview_article_changed(payload)
        if not outcome.applied:
            # Applying a no-op records same-revision conflicts without moving
            # the authoritative revision or touching the persistent index.
            committed = self._state.apply_article_changed(payload, message_id=message_id)
            if committed.reason == "revision_conflict":
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    "Content delivery conflicts with the known hash at the same revision.",
                    port="ContentConsumerService",
                )
            return committed
        if self._projector is None:
            raise PortError(
                AgentErrorCode.CONFIG_ERROR,
                "Content consumption requires a persistent index projector.",
                port="ContentConsumerService",
            )
        if outcome.reason == "removed":
            removed, chunks = await self._projector.on_article_removed(
                str(payload.article_id), int(payload.article_revision)
            )
            # removed=False: makale indeks hiç girmedi veya zaten düşmüş — yine idempotent.
            logger.info(
                "tombstone indeks etkisi: article=%s removed=%s chunks=%s",
                payload.article_id, removed, chunks,
            )
            return self._state.apply_article_changed(payload, message_id=message_id)
        receipt = await self._projector.on_article_applied(
            self._state,
            str(payload.article_id),
            int(payload.article_revision),
            str(payload.content_hash),
            message_id=message_id,
        )
        logger.info(
            "updated indeks etkisi: article=%s revision=%s effect=%s",
            payload.article_id, receipt.revision, receipt.effect,
        )
        projected_payload = payload.model_copy(update={
            "article_revision": receipt.revision,
            "content_hash": receipt.content_hash,
            "action": "unpublished" if receipt.removed else "updated",
        })
        committed = self._state.apply_article_changed(projected_payload, message_id=message_id)
        return ContentApplyOutcome(
            committed.message_type, committed.applied, receipt.effect, committed.article_id, committed.revision
        )


def build_content_consumer(
    connection: AbstractRobustConnection,
    service: ContentConsumerService,
    settings: BrokerSettings | None = None,
    *,
    consumer_tag: str | None = "agent-content-consumer",
) -> BrokerConsumer:
    """CONTENT_QUEUE tüketen B2 robust consumer'ı içerik servisiyle bağlar.

    Kuyruk pasif doğrulanır (K3: declarer backend); bulunamazsa ``TopologyError``.
    """

    return BrokerConsumer(
        connection,
        CONTENT_QUEUE,
        service.handle_delivery,
        settings,
        consumer_tag=consumer_tag,
    )


def _safe_message_id(message: AbstractIncomingMessage | None) -> str:
    value = getattr(message, "message_id", None)
    return value if isinstance(value, str) else ""
