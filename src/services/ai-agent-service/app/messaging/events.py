"""Agent olay yayıncısı (B5): DomainProgress/AgentOutcome → sürümlenmiş broker olayları.

Sorumluluk (plan B5 Python listesi):
- Kritik durum ve terminal sonuç, agent outbox kaydıyla AYNI transaction'da
  saklanır: terminal outcome iş durumunu (``agent.jobs.status``) outbox INSERT'i
  ile tek transaction'da yazar; commit'ten biri başarısızsa ikisi de geri alınır.
- Kaynak/kapsam kontrolü tamamlanmış sonuç yayınlanır: completed/partially_completed
  için ``source_scope`` ile citation ``kind`` uyumu yayıncıda zorlanır (uygunsuz
  kombinasyon ``EventPublishError``; hiçbir kayıt yazılmaz). Profil kapsamı yalnız
  profile kaynağı taşır; profile kaynağı profil kapsamı dışında taşınamaz.
- Run başına event_sequence DB tarafında atomik üretilir:
  ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` tek satır kilidi altında
  tahsis eder; eşzamanlı yayıncılar duplicate veya ters sıra ÜRETEMEZ
  (sıra ihlali üretilmez; tüketici tarafındaki guard savunma katmanıdır).
- Sık ilerleme sinyalleri seyrekleştirilir: aynı run'da AYNI ``kind`` progress
  ``min_progress_interval_seconds`` içinde tekrar gelirse yayınlanmaz
  (``ThrottledProgress``). Farklı kind önemli geçiştir; token başına broker
  mesajı bu katmana hiç gelmez (B6 worker token akışını buraya vermez).
- Terminal outcome tek kez yazılır: iş zaten terminal durumdaysa ikinci
  terminal olay ÜRETİLMEZ (``AlreadyTerminal``) ve sıra tahsisi rollback ile
  geri alınır.
- Yayın (broker'a taşıma) B4 ``OutboxRelay``'in işidir: confirm sonrası yayın
  kaydı orada güncellenir; bu modül yalnız outbox'a yazar.

Wire sürümü (karar kaydı K4): HER olay (progress, generation_delta, mode_selected,
needs_input, action_proposed, terminal) run'ın ``agent.jobs.wire_version``
değeriyle kurulur; sürüm, olayın yazıldığı transaction içinde iş satırından okunur
(iş kaydı yoksa v1). v2'ye özgü alanlar (``run_intent``, ``source_scope``,
``profile_snapshot``) yalnız v2 run'ında taşınır; v1 run'ı donmuş v1 şeklinde
kalır ve profile kaynağı TAŞIYAMAZ (provenance daraltılmaz → ``EventPublishError``).

Payload'lar sürümün B1/v2 transport modelleriyle kurulur ve tüketiciyle aynı
doğrulayıcıdan (``parse_envelope``) geçirilir (``wire.compose_run_envelope``).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal, Mapping

import asyncpg

from .contracts import (
    WIRE_VERSION_V1,
    AgentContractError,
    AgentEnvelope,
    AgentErrorCode,
    AgentMode,
    RunIntent,
    SourceScope,
)
from .contracts.payloads import AgentActionProposalContent, AgentUsageRecord
from .wire import (
    WORKER_WIRE_MAX_SETTING,
    WireVersionMismatch,
    compose_run_envelope,
    normalize_wire_version,
    outbox_route,
    to_transport_citation,
    to_transport_profile_snapshot,
    versioned_payload,
)

__all__ = [
    "AgentEventPublisher",
    "AgentOutcome",
    "EventPublishError",
    "AlreadyTerminal",
    "ThrottledProgress",
    "TERMINAL_JOB_STATUSES",
    "MAX_GENERATION_DELTA_CHARS",
]

#: Tek ``generation_delta`` chunk'ının taşıyıcı üst sınırı: ``AgentRunProgressedV1.message``
#: max 2000'dir; 1500'ün üzerine çıkan metin bölünmüş chunk olarak ayrı olaylarla akar
#: (streaming sözleşmesi: "Chunk üretimi 1500 karakteri ASLA aşmasın").
MAX_GENERATION_DELTA_CHARS = 1500

logger = logging.getLogger(__name__)

#: Terminal iş durumları (migration 0002 ck_jobs_status ile aynı küme).
TERMINAL_JOB_STATUSES = ("completed", "partially_completed", "failed", "cancelled")


class EventPublishError(RuntimeError):
    """Run bilinmiyor veya payload sözleşmeye aykırı (yayın reddedilir, kayıt yazılmaz)."""


class AlreadyTerminal(EventPublishError):
    """İş terminal durumda; ikinci terminal olay üretilmez (idempotent terminal)."""


@dataclass(frozen=True)
class ThrottledProgress:
    """Seyrekleştirme kararı: olay ÜRETİLMEDİ, kayıt yazılmadı (sıra tüketilmedi)."""

    run_id: str
    kind: str
    detail: str = "aynı kind sinyali kısa aralıkta tekrar geldi; seyrekleştirildi"


@dataclass(frozen=True)
class AgentOutcome:
    """Terminal çalışma sonucu (A1 AgentOutcome'un taşıma karşılığı).

    ``kind`` mesaj türünü seçer; tam snapshot completed/partially_completed için
    zorunlu alanlarla taşınır (plan B5: "terminal olay tam sonuç snapshot'ı taşır").
    ``run_intent``/``profile_snapshot`` v2 alanlarıdır: v2 run'ında taşınır
    (completed/partial için ``run_intent`` zorunlu), v1 run'ında yok sayılır.
    """

    kind: Literal["completed", "partially_completed", "failed", "cancelled"]
    selected_mode: AgentMode | str | None = None
    answer: str | None = None
    report: str | None = None
    citations: tuple[Any, ...] = ()
    source_scope: SourceScope | str | None = None
    unresolved_questions: tuple[str, ...] = ()
    usage: AgentUsageRecord | None = None
    action_proposal: AgentActionProposalContent | None = None
    error_code: AgentErrorCode | str | None = None
    error_message: str | None = None
    cancel_reason: str | None = None
    run_intent: RunIntent | str | None = None
    profile_snapshot: Any | None = None

    @property
    def job_status(self) -> str:
        return self.kind  # job status değeri kind ile aynı adı taşır


def _utc(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _value(item: Any) -> Any:
    """Enum → değer; diğerleri aynen (payload alanı için)."""

    return getattr(item, "value", item)


def _split_chunk(text: str) -> list[str]:
    """``generation_delta`` metnini taşıyıcı üst sınırına göre böler.

    Boş metin olay ÜRETMEZ (``message`` min_length=1'dir); üst sınırı aşan metin
    soldan sağa eşit parçalara bölünür — hiçbir parça
    ``MAX_GENERATION_DELTA_CHARS``'ı aşmaz.
    """

    if not text:
        return []
    limit = MAX_GENERATION_DELTA_CHARS
    if len(text) <= limit:
        return [text]
    return [text[start : start + limit] for start in range(0, len(text), limit)]


def _non_terminal_statuses() -> list[str]:
    """Terminal yazımının izin verildiği kaynak durumlar.

    ``needs_input`` bilinçli YOKTUR: kullanıcı girdisi bekleme terminal değildir
    ve iş durumu accepted kalır; accepted tek non-terminal değerdir.
    """

    return ["accepted"]


class AgentEventPublisher:
    """Run olaylarını outbox'a aynı-transaction kuralıyla yazar; ömür: pool başına tek."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        schema: str = "agent",
        min_progress_interval_seconds: float = 2.0,
        new_message_id: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        self._pool = pool
        self._schema = schema
        self._min_interval = min_progress_interval_seconds
        self._new_message_id = new_message_id or uuid.uuid4
        # run_id -> {kind: monotonic zaman}; süreç-içi seyrekleştirme kararıdır.
        self._last_progress_at: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ progress

    async def publish_progress(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        kind: str,
        message: str,
        detail: dict[str, str] | None = None,
        execution_attempt: int | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEnvelope | ThrottledProgress:
        """``agent.run.progressed`` olayı; aynı kind kısa aralıkta tekrar gelirse üretilmez."""

        throttle = self._throttle(run_id, kind)
        if throttle is not None:
            return throttle

        return await self._publish_run_event(
            message_type="agent.run.progressed",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            fields={
                "event_sequence": 0,  # gerçek değer DB'de tahsis edilir; gövdeye orada yazılır
                "execution_attempt": execution_attempt,
                "kind": kind,
                "message": message,
                "detail": dict(detail or {}),
            },
        )

    async def publish_mode_selected(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        selected_mode: str,
        requires_web_search: bool,
        reason: str,
        execution_attempt: int | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
        run_intent: RunIntent | str | None = None,
        source_scope: SourceScope | str | None = None,
        profile_snapshot: Any | None = None,
    ) -> AgentEnvelope:
        """``agent.run.mode_selected``: önemli geçiş; seyrekleştirilmez.

        B1 çapraz kuralı (requires_web_search yalnız deep_research'te true) model
        doğrulayıcısında uygulanır; aykırı girdi ValueError ile reddedilir. v2
        run'ında ``run_intent`` + ``source_scope`` zorunludur ve ``profile`` niyeti
        web'siz + profil kapsamlı + pinlenmiş snapshot'lıdır (v2 sözleşme kuralı).
        """

        return await self._publish_run_event(
            message_type="agent.run.mode_selected",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            fields={
                "event_sequence": 0,
                "execution_attempt": execution_attempt,
                "selected_mode": _value(selected_mode),
                "requires_web_search": requires_web_search,
                "reason": reason,
            },
            v2_fields={
                "run_intent": _value(run_intent),
                "source_scope": _value(source_scope),
                "profile_snapshot": to_transport_profile_snapshot(profile_snapshot),
            },
        )

    async def publish_needs_input(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        unresolved_questions: Iterable[str],
        usage: AgentUsageRecord | None = None,
        execution_attempt: int | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEnvelope:
        """``agent.run.needs_input``: terminal değildir; iş durumu accepted kalır."""

        return await self._publish_run_event(
            message_type="agent.run.needs_input",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            fields={
                "event_sequence": 0,
                "execution_attempt": execution_attempt,
                "unresolved_questions": list(unresolved_questions),
                "usage": usage,
            },
        )

    async def publish_action_proposed(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        proposal: AgentActionProposalContent,
        execution_attempt: int | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEnvelope:
        """``agent.action.proposed``: B9 proposal kaydının TEK kaynağı (W6 F1).

        Önemli geçiştir (``mode_selected`` gibi): SEYREKLEŞTİRİLMEZ — seyrekleş
        tirme proposal kaydını tamamen düşürebilirdi (A9→B5 zincirindeki tek
        kayıt olayı budur). Zarf run_id ile payload run_id aynıdır (sözleşme
        kuralı: "run_id zarf run_id ile uyuşmak zorundadır").
        """

        return await self._publish_run_event(
            message_type="agent.action.proposed",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            fields={
                "event_sequence": 0,  # gerçek değer DB'de tahsis edilir; gövdeye orada yazılır
                "execution_attempt": execution_attempt,
                "run_id": run_id,
                "proposal_id": proposal.proposal_id,
                "article_id": proposal.article_id,
                "article_revision": proposal.article_revision,
                "base_content_hash": proposal.base_content_hash,
                "summary": proposal.summary,
                "proposed_content": proposal.proposed_content,
                "created_at": proposal.created_at,
            },
        )

    async def publish_generation_delta(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        text: str,
        execution_attempt: int | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> list[AgentEnvelope]:
        """``agent.run.progressed`` (kind=generation_delta): parçalı üretim metni.

        ``publish_action_proposed`` gibi ÖNEMLİ geçiş sayılır: SEYREKLEŞTİRİLMEZ
        (``_throttle`` çağrılmaz) — seyrekleştirme token akışını kalıcı olarak
        yutardı. Yine de token-başına broker mesajı YASAKTır: çağıran birleştirilmiş
        chunk gönderir; bu metot 1500 karakteri aşarsa BÖLER ve her parçayı sıra
        tahsisli ayrı olay olarak yazar (detail kullanılmaz, payload alanı eklenmez).
        Profil (Who am I) run'larında bu yol worker sink'inde HİÇ çağrılmaz
        (doğrulanmamış biyografi metni yayınlanmaz).
        """
        envelopes: list[AgentEnvelope] = []
        for chunk in _split_chunk(text):
            envelopes.append(
                await self._publish_run_event(
                    message_type="agent.run.progressed",
                    run_id=run_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    occurred_at=occurred_at,
                    fields={
                        "event_sequence": 0,  # gerçek değer DB'de tahsis edilir
                        "execution_attempt": execution_attempt,
                        "kind": "generation_delta",
                        "message": chunk,
                        "detail": {},
                    },
                )
            )
        return envelopes

    # ------------------------------------------------------------------ terminal

    async def publish_outcome(
        self,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        outcome: AgentOutcome,
        execution_attempt: int | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentEnvelope:
        """Terminal sonucu iş durumu değişikliğiyle TEK transaction'da outbox'a yazar.

        - Kaynak/kapsam kontrolü: scope citation kind'larıyla uyuşmalı (uyumsuzluk
          ``EventPublishError``; hiçbir yazım olmaz).
        - İş zaten terminal ise ``AlreadyTerminal``: ikinci terminal olay üretilmez,
          sıra tahsisi transaction rollback'iyle geri alınır.
        - İş kaydı yoksa ``EventPublishError``: yayın yalnız kabul edilmiş run içindir.
        - Zarf iş satırının ``wire_version``'ıyla kurulur (UPDATE ... RETURNING).
        """

        self._check_source_scope(outcome)
        self._check_terminal_shape(outcome)
        message_type = f"agent.run.{outcome.kind}"
        occurred = occurred_at or datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET status = $2 "
                    f"WHERE run_id = $1 AND status = ANY($3::text[]) "
                    "RETURNING job_id, wire_version",
                    uuid.UUID(run_id),
                    outcome.job_status,
                    _non_terminal_statuses(),
                )
                if updated is None:
                    await self._raise_terminal_rejection(conn, run_id)
                version = normalize_wire_version(updated["wire_version"])
                payload = self._build_terminal_payload(outcome, execution_attempt, version)
                payload["event_sequence"] = await self._allocate_sequence(conn, run_id)

                envelope = self._envelope(
                    wire_version=version,
                    message_type=message_type,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    occurred_at=occurred,
                    payload=payload,
                )
                await self._insert_outbox(conn, envelope=envelope, created_at=occurred)
                written_sequence = int(envelope.payload["event_sequence"])

        logger.info(
            "terminal olay outbox'a yazıldı: run_id=%s kind=%s sequence=%s wire=v%s",
            run_id,
            outcome.kind,
            written_sequence,
            envelope.schema_version,
        )
        return envelope

    # ------------------------------------------------------------------ iç adımlar

    async def _raise_terminal_rejection(self, conn: asyncpg.Connection, run_id: str) -> None:
        """Terminal UPDATE satır döndürmedi: gerekçeyi ayırt edip yükseltir."""

        job = await conn.fetchrow(
            f"SELECT status, wire_version, "
            f"coalesce(nullif(current_setting('{WORKER_WIRE_MAX_SETTING}', true), ''), '1')::int AS wire_max "
            f"FROM {self._schema}.jobs WHERE run_id = $1",
            uuid.UUID(run_id),
        )
        if job is None:
            raise EventPublishError(f"run {run_id} için iş kaydı yok; terminal olay yayınlanmaz")
        if str(job["status"]) in _non_terminal_statuses() and int(job["wire_version"]) > int(job["wire_max"]):
            raise EventPublishError(
                f"run {run_id} wire v{job['wire_version']}; bu oturum en fazla v{job['wire_max']} "
                "yürütebilir (sürüm izolasyonu) — terminal olay yayınlanmaz"
            )
        raise AlreadyTerminal(
            f"run {run_id} zaten terminal ({job['status']}); ikinci terminal olay üretilmez"
        )

    @staticmethod
    def _check_terminal_shape(outcome: AgentOutcome) -> None:
        """Sürümden bağımsız terminal zorunlulukları (yazımdan ÖNCE)."""

        if outcome.kind in ("completed", "partially_completed"):
            if outcome.answer is None and outcome.report is None:
                raise EventPublishError(f"{outcome.kind} sonucu answer veya report taşımak zorundadır")
            if outcome.source_scope is None or outcome.usage is None or outcome.selected_mode is None:
                raise EventPublishError(
                    f"{outcome.kind} sonucu source_scope, usage ve selected_mode taşımak zorundadır"
                )
        if outcome.kind == "failed" and outcome.error_code is None:
            raise EventPublishError("failed sonucu error_code taşımak zorundadır")

    def _build_terminal_payload(
        self, outcome: AgentOutcome, execution_attempt: int | None, wire_version: int
    ) -> dict[str, Any]:
        """Run sürümünün terminal payload alanları (doğrulama ``_envelope``'da)."""

        try:
            citations = [to_transport_citation(c, wire_version) for c in outcome.citations]
        except WireVersionMismatch as error:
            raise EventPublishError(f"terminal sonuç run sürümüne aykırı: {error}") from None
        v2_fields = {
            "run_intent": _value(outcome.run_intent),
            "profile_snapshot": to_transport_profile_snapshot(outcome.profile_snapshot),
        }
        common: dict[str, Any] = {"event_sequence": 0, "execution_attempt": execution_attempt}
        if outcome.kind == "completed":
            fields = {
                **common,
                "selected_mode": _value(outcome.selected_mode),
                "answer": outcome.answer,
                "report": outcome.report,
                "citations": citations,
                "source_scope": _value(outcome.source_scope),
                "unresolved_questions": list(outcome.unresolved_questions),
                "usage": outcome.usage,
                "action_proposal": outcome.action_proposal,
            }
            return versioned_payload(wire_version, fields, v2_fields)
        if outcome.kind == "partially_completed":
            fields = {
                **common,
                "selected_mode": _value(outcome.selected_mode),
                "answer": outcome.answer,
                "report": outcome.report,
                "citations": citations,
                "source_scope": _value(outcome.source_scope),
                "unresolved_questions": list(outcome.unresolved_questions),
                "usage": outcome.usage,
            }
            return versioned_payload(wire_version, fields, v2_fields)
        if outcome.kind == "failed":
            fields = {
                **common,
                "error_code": _value(outcome.error_code),
                "error_message": outcome.error_message,
                "selected_mode": _value(outcome.selected_mode),
                "usage": outcome.usage,
            }
            return versioned_payload(wire_version, fields, v2_fields)
        # cancelled
        return versioned_payload(
            wire_version, {**common, "reason": outcome.cancel_reason, "usage": outcome.usage}
        )

    @staticmethod
    def _check_source_scope(outcome: AgentOutcome) -> None:
        """Yayın öncesi kaynak/kapsam kontrolü (plan: 'kaynak ve kapsam kontrolü
        tamamlanmış sonucu yayınla'): scope citation kind ile çelişemez.

        Profil kuralları (v2, sürümden bağımsız denetlenir): profil kapsamı yalnız
        profile kaynağı taşır; profile kaynağı yalnız profil kapsamında bulunur;
        ``run_intent=profile`` sonucu profil kapsamlıdır.
        """

        kinds = {citation.kind for citation in outcome.citations}
        if outcome.source_scope is None:
            if "profile" in kinds:
                raise EventPublishError("profile kaynağı yalnız source_scope=profile sonucunda taşınabilir")
            return  # failed/cancelled snapshot'ta scope opsiyoneldir
        scope = SourceScope(_value(outcome.source_scope))
        has_article = "article" in kinds
        has_web = "web" in kinds
        has_profile = "profile" in kinds
        if scope == SourceScope.ARTICLE and has_web:
            raise EventPublishError(
                "source_scope=article sonuç web kaynağı taşıyamaz; yayın reddedildi"
            )
        if scope == SourceScope.WEB and has_article:
            raise EventPublishError(
                "source_scope=web sonuç makale kaynağı taşıyamaz; yayın reddedildi"
            )
        if scope in (SourceScope.ARTICLE, SourceScope.WEB) and not kinds:
            raise EventPublishError(
                f"source_scope={scope} için en az bir citation zorunludur"
            )
        if scope == SourceScope.PROFILE and (has_article or has_web):
            raise EventPublishError(
                "source_scope=profile sonuç makale/web kaynağı taşıyamaz; yayın reddedildi"
            )
        if has_profile and scope != SourceScope.PROFILE:
            raise EventPublishError(
                f"profile kaynağı source_scope={scope} sonucunda taşınamaz; yayın reddedildi"
            )
        if outcome.run_intent is not None and RunIntent(_value(outcome.run_intent)) is RunIntent.PROFILE:
            if scope != SourceScope.PROFILE:
                raise EventPublishError("run_intent=profile sonucu yalnız source_scope=profile olabilir")

    def _throttle(self, run_id: str, kind: str) -> ThrottledProgress | None:
        now = time.monotonic()
        per_run = self._last_progress_at.setdefault(run_id, {})
        last = per_run.get(kind)
        if last is not None and (now - last) < self._min_interval:
            return ThrottledProgress(run_id=run_id, kind=kind)
        per_run[kind] = now
        return None

    async def _run_wire_version(self, conn: asyncpg.Connection, run_id: str) -> int:
        """Run'ın wire sürümü (transaction içinde); iş kaydı yoksa v1 (önceki davranış)."""

        value = await conn.fetchval(
            f"SELECT wire_version FROM {self._schema}.jobs WHERE run_id = $1",
            uuid.UUID(run_id),
        )
        return WIRE_VERSION_V1 if value is None else normalize_wire_version(value)

    async def _publish_run_event(
        self,
        *,
        message_type: str,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None,
        occurred_at: datetime | None,
        fields: Mapping[str, Any],
        v2_fields: Mapping[str, Any] | None = None,
    ) -> AgentEnvelope:
        """Non-terminal run olayı: sürüm okuma + sıra tahsisi + outbox INSERT tek transaction'da."""

        occurred = occurred_at or datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                version = await self._run_wire_version(conn, run_id)
                payload = versioned_payload(version, fields, v2_fields)
                payload["event_sequence"] = await self._allocate_sequence(conn, run_id)
                envelope = self._envelope(
                    wire_version=version,
                    message_type=message_type,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    occurred_at=occurred,
                    payload=payload,
                )
                await self._insert_outbox(conn, envelope=envelope, created_at=occurred)
        return envelope

    async def _allocate_sequence(self, conn: asyncpg.Connection, run_id: str) -> int:
        """Run başına atomik monoton sequence (migration 0002 tablosu).

        ON CONFLICT DO UPDATE tek satırı kilitler: eşzamanlı çağıranlar 1,2,3...
        alır; duplicate/ters değer ÜRETİLEMEZ.
        """

        row = await conn.fetchrow(
            f"INSERT INTO {self._schema}.run_event_sequences (run_id, last_sequence, updated_at) "
            "VALUES ($1, 1, now()) "
            f"ON CONFLICT (run_id) DO UPDATE SET "
            f"last_sequence = {self._schema}.run_event_sequences.last_sequence + 1, "
            "updated_at = now() "
            "RETURNING last_sequence",
            uuid.UUID(run_id),
        )
        return int(row["last_sequence"])

    def _envelope(
        self,
        *,
        wire_version: int,
        message_type: str,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> AgentEnvelope:
        """(sürüm, tür) kaydı + sürüm DTO'su + tüketici doğrulayıcısı ile zarf.

        Tür sözleşmede (o sürümde) kayıtlı değilse ``UnknownMessageSpec`` (KeyError)
        yükselir: sözleşme dışı olay üretilmez. Çapraz kural ihlali ``EventPublishError``.
        """

        try:
            return compose_run_envelope(
                schema_version=wire_version,
                message_type=message_type,
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=_utc(occurred_at),
                payload=payload,
                new_message_id=self._new_message_id,
            )
        except AgentContractError as error:
            raise EventPublishError(
                f"{message_type} v{wire_version} sözleşmeye aykırı ({error.category.value}, {error.field}): "
                f"{error.message}"
            ) from None

    async def _insert_outbox(
        self, conn: asyncpg.Connection, *, envelope: AgentEnvelope, created_at: datetime
    ) -> uuid.UUID:
        exchange, routing_key = outbox_route(envelope)
        outbox_id = uuid.uuid4()
        await conn.execute(
            f"INSERT INTO {self._schema}.outbox_events "
            "(outbox_id, message_id, message_type, exchange, routing_key, envelope, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)",
            outbox_id,
            uuid.UUID(envelope.message_id),
            envelope.message_type,
            exchange,
            routing_key,
            envelope.model_dump_json(exclude_none=True),
            created_at,
        )
        return outbox_id

