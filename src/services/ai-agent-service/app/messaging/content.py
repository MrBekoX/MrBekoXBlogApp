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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from .contracts import ArticleContentChangedV1, ContentSnapshotBatchV1, ContentSnapshotCompletedV1, ParsedEnvelope, ProjectContentChangedV1, ProfileContentChangedV1, parse_envelope
from .consumer import BrokerConsumer
from .settings import BrokerSettings
from .topology import CONTENT_QUEUE

__all__ = [
    "CONTENT_MESSAGE_TYPES",
    "ContentApplyOutcome",
    "ContentIndexProjector",
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
    completed: bool = False
    completed_item_count: int | None = None
    completed_message_id: str | None = None


class _ContentBodyFetcher(Protocol):
    """(article_id, revision) → makale gövdesi köprüsü (K7: içerik mesajda taşınmaz).

    B8'de opsiyoneldir: verilirse updated olayı ve senkron referansı gerçek indeksleme
    üretir; verilmezse yalnız revizyon durumu uygulanır (indeksleme yürütme anındaki
    doğrulanmış snapshot ile A4 akışında olur).
    """

    async def fetch(self, article_id: str, article_revision: int) -> Any:
        ...


class ContentIndexProjector:
    """İçerik durumunu A3 indeksine yansıtan köprü (opsiyonel).

    - Tombstone → ``remove_article``: parçalar + makale önbelleği tek çağrıda düşer.
    - updated/senkron referansı → gövde köprüsü varsa ``index_article``; yoksa salt
      revizyon durumu (``state_only``). Gövde hash'i olay hash'iyle doğrulanır;
      uyuşmazlık çatışma kaydıyla görünür olur.
    """

    def __init__(
        self,
        index: Any,
        *,
        embedding_provider: Any,
        model_config: Any,
        content_fetcher: _ContentBodyFetcher | None = None,
        canonical_url_template: str | None = None,
    ) -> None:
        self._index = index
        self._embedding_provider = embedding_provider
        self._model_config = model_config
        self._content_fetcher = content_fetcher
        self._canonical_url_template = canonical_url_template

    async def on_article_applied(
        self,
        state: ContentSyncState,
        article_id: str,
        revision: int,
        content_hash: str,
        *,
        message_id: str = "",
    ) -> str:
        if self._content_fetcher is None:
            return "state_only"
        snapshot = await self._content_fetcher.fetch(article_id, revision)
        if str(snapshot.content_hash) != content_hash:
            state.record_conflict(
                article_id=article_id,
                revision=revision,
                known_hash=content_hash,
                incoming_hash=str(snapshot.content_hash),
                message_id=message_id or "content_fetch",
            )
            return "hash_mismatch"
        result = await self._index.index_article(
            snapshot,
            embedding_provider=self._embedding_provider,
            model_config=self._model_config,
            canonical_url_template=self._canonical_url_template,
        )
        return f"indexed:{result.chunk_count}"

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
                and sync.completed_item_count != sync.applied_items
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
        mismatch = sync.completed_item_count != sync.applied_items
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
            self.record_conflict(
                article_id=article_id, revision=revision,
                known_hash=current.content_hash, incoming_hash=content_hash, message_id=message_id,
            )
            return ContentApplyOutcome("content.article.changed", False, "revision_conflict", article_id, revision)
        self._articles[article_id] = _ArticleState(revision=revision, content_hash=content_hash)
        if sync is not None:
            sync.applied_items += 1
        return ContentApplyOutcome("content.article.changed", True, "applied", article_id, revision)

    def _apply_removal(self, article_id: str, revision: int, *, message_id: str = "") -> ContentApplyOutcome:
        current = self._articles.get(article_id)
        if current is not None and revision < current.revision:
            # Makale kaldırmadan SONRA yeniden yayımlanmış; eski kaldırma geçersizdir.
            return ContentApplyOutcome("content.article.changed", False, "stale_revision", article_id, revision)
        removal = self._removals.get(article_id)
        if removal is not None and revision <= removal:
            # Tekrar teslim/idempotent: aynı veya daha eski kaldırma; indeks zaten boş.
            return ContentApplyOutcome("content.article.changed", False, "duplicate_removal", article_id, revision)
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
        return await self.handle_parsed(parsed, message_id=_safe_message_id(message))

    async def handle_parsed(self, parsed: ParsedEnvelope, *, message_id: str = "") -> ContentApplyOutcome:
        message_type = parsed.spec.message_type
        if message_type not in CONTENT_MESSAGE_TYPES:
            raise ContentPolicyError(
                f"içerik kuyruğu yalnız içerik olayları kabul eder; gelen: {message_type}"
            )

        payload = parsed.payload
        if isinstance(payload, ArticleContentChangedV1):
            outcome = self._state.apply_article_changed(payload, message_id=message_id)
            await self._project_article(outcome, payload, message_id=message_id)
            return outcome
        if isinstance(payload, ContentSnapshotBatchV1):
            return self._state.apply_snapshot_batch(payload, message_id=message_id)
        if isinstance(payload, ContentSnapshotCompletedV1):
            return self._state.apply_snapshot_completed(payload, message_id=message_id)
        if isinstance(payload, ProfileContentChangedV1):
            return self._state.apply_profile_changed(payload, message_id=message_id)
        if isinstance(payload, ProjectContentChangedV1):
            return self._state.apply_project_changed(payload, message_id=message_id)
        raise ContentPolicyError(f"içerik kuyruğunda beklenmeyen payload türü: {type(payload).__name__}")

    async def _project_article(
        self,
        outcome: ContentApplyOutcome,
        payload: ArticleContentChangedV1,
        *,
        message_id: str,
    ) -> None:
        if self._projector is None or not outcome.applied:
            return
        if outcome.reason == "removed":
            removed, chunks = await self._projector.on_article_removed(
                str(payload.article_id), int(payload.article_revision)
            )
            # removed=False: makale indeks hiç girmedi veya zaten düşmüş — yine idempotent.
            logger.info(
                "tombstone indeks etkisi: article=%s removed=%s chunks=%s",
                payload.article_id, removed, chunks,
            )
            return
        effect = await self._projector.on_article_applied(
            self._state,
            str(payload.article_id),
            int(payload.article_revision),
            str(payload.content_hash),
            message_id=message_id,
        )
        logger.info(
            "updated indeks etkisi: article=%s revision=%s effect=%s",
            payload.article_id, payload.article_revision, effect,
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
