"""Agent olay yayıncısı (B5): DomainProgress/AgentOutcome → sürümlenmiş broker olayları.

Sorumluluk (plan B5 Python listesi):
- Kritik durum ve terminal sonuç, agent outbox kaydıyla AYNI transaction'da
  saklanır: terminal outcome iş durumunu (``agent.jobs.status``) outbox INSERT'i
  ile tek transaction'da yazar; commit'ten biri başarısızsa ikisi de geri alınır.
- Kaynak/kapsam kontrolü tamamlanmış sonuç yayınlanır: completed/partially_completed
  için ``source_scope`` ile citation ``kind`` uyumu yayıncıda zorlanır (uygunsuz
  kombinasyon ``EventPublishError``; hiçbir kayıt yazılmaz).
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

Payload'lar B1 transport modelleriyle (``contracts.payloads``) kurulur: şema
uyumu model doğrulayıcılarıyla birebir garanti edilir. Envelope'lar
``parse_envelope`` ile geri doğrulanabilir (test kanıtı).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal

import asyncpg

from .contracts import (
    SCHEMA_VERSION,
    AgentEnvelope,
    AgentErrorCode,
    AgentMode,
    AgentRunCancelledV1,
    AgentRunCompletedV1,
    AgentRunFailedV1,
    AgentRunModeSelectedV1,
    AgentRunNeedsInputV1,
    AgentRunPartiallyCompletedV1,
    AgentRunProgressedV1,
    MESSAGE_TYPE_REGISTRY,
    Producer,
    SourceScope,
)
from .contracts.payloads import (
    AgentActionProposalContent,
    AgentSourceReference,
    AgentUsageRecord,
)

__all__ = [
    "AgentEventPublisher",
    "AgentOutcome",
    "EventPublishError",
    "AlreadyTerminal",
    "ThrottledProgress",
    "TERMINAL_JOB_STATUSES",
]

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
    """

    kind: Literal["completed", "partially_completed", "failed", "cancelled"]
    selected_mode: AgentMode | str | None = None
    answer: str | None = None
    report: str | None = None
    citations: tuple[AgentSourceReference, ...] = ()
    source_scope: SourceScope | str | None = None
    unresolved_questions: tuple[str, ...] = ()
    usage: AgentUsageRecord | None = None
    action_proposal: AgentActionProposalContent | None = None
    error_code: AgentErrorCode | str | None = None
    error_message: str | None = None
    cancel_reason: str | None = None

    @property
    def job_status(self) -> str:
        return self.kind  # job status değeri kind ile aynı adı taşır


def _utc(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_of(model: Any) -> dict[str, Any]:
    """B1 modelini sözleşme JSON'una çevirir (null taşınmaz kuralı)."""

    return model.model_dump(exclude_none=True)


def _clean(**kwargs: Any) -> dict[str, Any]:
    """None değerli anahtarları atar: ``TransportModel`` açık null taşınmasını reddeder."""

    return {key: value for key, value in kwargs.items() if value is not None}


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

        payload_model = AgentRunProgressedV1(
            **_clean(
                event_sequence=0,  # gerçek değer DB'de tahsis edilir; gövdeye orada yazılır
                execution_attempt=execution_attempt,
                kind=kind,
                message=message,
                detail=dict(detail or {}),
            )
        )
        return await self._publish_run_event(
            message_type="agent.run.progressed",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            payload_model=payload_model,
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
    ) -> AgentEnvelope:
        """``agent.run.mode_selected``: önemli geçiş; seyrekleştirilmez.

        B1 çapraz kuralı (requires_web_search yalnız deep_research'te true) model
        doğrulayıcısında uygulanır; aykırı girdi ValueError ile reddedilir.
        """

        payload_model = AgentRunModeSelectedV1(
            **_clean(
                event_sequence=0,
                execution_attempt=execution_attempt,
                selected_mode=selected_mode,
                requires_web_search=requires_web_search,
                reason=reason,
            )
        )
        return await self._publish_run_event(
            message_type="agent.run.mode_selected",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            payload_model=payload_model,
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

        payload_model = AgentRunNeedsInputV1(
            **_clean(
                event_sequence=0,
                execution_attempt=execution_attempt,
                unresolved_questions=list(unresolved_questions),
                usage=usage,
            )
        )
        return await self._publish_run_event(
            message_type="agent.run.needs_input",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            payload_model=payload_model,
        )

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
        """

        payload_model = self._build_terminal_payload(outcome, execution_attempt)
        message_type = f"agent.run.{outcome.kind}"
        occurred = occurred_at or datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                sequence = await self._allocate_sequence(conn, run_id)
                payload = _payload_of(payload_model)
                payload["event_sequence"] = sequence

                envelope = self._envelope(
                    message_type=message_type,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    occurred_at=occurred,
                    payload=payload,
                )

                updated = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET status = $2 "
                    f"WHERE run_id = $1 AND status = ANY($3::text[]) "
                    "RETURNING job_id",
                    uuid.UUID(run_id),
                    outcome.job_status,
                    _non_terminal_statuses(),
                )
                if updated is None:
                    job = await conn.fetchrow(
                        f"SELECT status FROM {self._schema}.jobs WHERE run_id = $1",
                        uuid.UUID(run_id),
                    )
                    if job is None:
                        raise EventPublishError(
                            f"run {run_id} için iş kaydı yok; terminal olay yayınlanmaz"
                        )
                    raise AlreadyTerminal(
                        f"run {run_id} zaten terminal ({job['status']}); "
                        "ikinci terminal olay üretilmez"
                    )

                await self._insert_outbox(conn, envelope=envelope, created_at=occurred)
                written_sequence = int(payload["event_sequence"])

        logger.info(
            "terminal olay outbox'a yazıldı: run_id=%s kind=%s sequence=%s",
            run_id,
            outcome.kind,
            written_sequence,
        )
        return envelope

    # ------------------------------------------------------------------ iç adımlar

    def _build_terminal_payload(
        self, outcome: AgentOutcome, execution_attempt: int | None
    ) -> Any:
        """B1 modeliyle terminal payload'ını kurar; uyumsuzluk burada ValueError/EventPublishError olur."""

        self._check_source_scope(outcome)
        common: dict[str, Any] = {
            "event_sequence": 0,
            "execution_attempt": execution_attempt,
        }
        if outcome.kind == "completed":
            if outcome.answer is None and outcome.report is None:
                raise EventPublishError("completed sonucu answer veya report taşımak zorundadır")
            if outcome.source_scope is None or outcome.usage is None or outcome.selected_mode is None:
                raise EventPublishError(
                    "completed sonucu source_scope, usage ve selected_mode taşımak zorundadır"
                )
            return AgentRunCompletedV1(
                **_clean(
                    **common,
                    selected_mode=outcome.selected_mode,
                    answer=outcome.answer,
                    report=outcome.report,
                    citations=list(outcome.citations),
                    source_scope=outcome.source_scope,
                    unresolved_questions=list(outcome.unresolved_questions),
                    usage=outcome.usage,
                    action_proposal=outcome.action_proposal,
                )
            )
        if outcome.kind == "partially_completed":
            if outcome.answer is None and outcome.report is None:
                raise EventPublishError(
                    "partially_completed sonucu answer veya report taşımak zorundadır"
                )
            if outcome.source_scope is None or outcome.usage is None or outcome.selected_mode is None:
                raise EventPublishError(
                    "partially_completed sonucu source_scope, usage ve selected_mode taşımak zorundadır"
                )
            return AgentRunPartiallyCompletedV1(
                **_clean(
                    **common,
                    selected_mode=outcome.selected_mode,
                    answer=outcome.answer,
                    report=outcome.report,
                    citations=list(outcome.citations),
                    source_scope=outcome.source_scope,
                    unresolved_questions=list(outcome.unresolved_questions),
                    usage=outcome.usage,
                )
            )
        if outcome.kind == "failed":
            if outcome.error_code is None:
                raise EventPublishError("failed sonucu error_code taşımak zorundadır")
            return AgentRunFailedV1(
                **_clean(
                    **common,
                    error_code=outcome.error_code,
                    error_message=outcome.error_message,
                    selected_mode=outcome.selected_mode,
                    usage=outcome.usage,
                )
            )
        # cancelled
        return AgentRunCancelledV1(
            **_clean(
                **common,
                reason=outcome.cancel_reason,
                usage=outcome.usage,
            )
        )

    @staticmethod
    def _check_source_scope(outcome: AgentOutcome) -> None:
        """Yayın öncesi kaynak/kapsam kontrolü (plan: 'kaynak ve kapsam kontrolü
        tamamlanmış sonucu yayınla'): scope citation kind ile çelişemez."""

        if outcome.source_scope is None:
            return  # failed/cancelled snapshot'ta scope opsiyoneldir
        scope = SourceScope(outcome.source_scope)
        kinds = {citation.kind for citation in outcome.citations}
        has_article = "article" in kinds
        has_web = "web" in kinds
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

    def _throttle(self, run_id: str, kind: str) -> ThrottledProgress | None:
        now = time.monotonic()
        per_run = self._last_progress_at.setdefault(run_id, {})
        last = per_run.get(kind)
        if last is not None and (now - last) < self._min_interval:
            return ThrottledProgress(run_id=run_id, kind=kind)
        per_run[kind] = now
        return None

    async def _publish_run_event(
        self,
        *,
        message_type: str,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None,
        occurred_at: datetime | None,
        payload_model: Any,
    ) -> AgentEnvelope:
        """Non-terminal run olayı: sıra tahsisi + outbox INSERT tek transaction'da."""

        occurred = occurred_at or datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                sequence = await self._allocate_sequence(conn, run_id)
                payload = _payload_of(payload_model)
                payload["event_sequence"] = sequence
                envelope = self._envelope(
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
        message_type: str,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> AgentEnvelope:
        # MESSAGE_TYPE_REGISTRY erişimi bilinçlidir: tür sözleşmede kayıtlı değilse
        # KeyError ile reddedilir (sözleşme dışı olay üretilmez).
        MESSAGE_TYPE_REGISTRY[message_type]
        return AgentEnvelope(
            **_clean(
                message_id=str(self._new_message_id()),
                message_type=message_type,
                schema_version=SCHEMA_VERSION,
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=_utc(occurred_at),
                producer=Producer.AGENT_PY,
                payload=payload,
            )
        )

    async def _insert_outbox(
        self, conn: asyncpg.Connection, *, envelope: AgentEnvelope, created_at: datetime
    ) -> uuid.UUID:
        spec_entry = MESSAGE_TYPE_REGISTRY[envelope.message_type]
        outbox_id = uuid.uuid4()
        await conn.execute(
            f"INSERT INTO {self._schema}.outbox_events "
            "(outbox_id, message_id, message_type, exchange, routing_key, envelope, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)",
            outbox_id,
            uuid.UUID(envelope.message_id),
            envelope.message_type,
            spec_entry.exchange,
            spec_entry.routing_key,
            envelope.model_dump_json(exclude_none=True),
            created_at,
        )
        return outbox_id
