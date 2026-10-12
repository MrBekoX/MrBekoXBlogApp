"""Kontrol deposu (B7): iptal niyeti ve terminal-öncelik kurallarının agent DB karşılığı.

ORTAK STORE SÖZLEŞMESİ (entegrasyon sahibi tanımı; B6/B7 buna uyar):

- B6 tarafı (``job_store.py`` additive + ``worker.py`` — PARALEL sahiplik):
  ``claim_next_job`` / ``renew_lease`` / ``complete_job`` / ``fail_job``;
  ``complete_job`` guard'ı: status='running' VE fencing eş VE aktif cancel
  intent YOK → completed; aksi 'rejected'.
- B7 tarafı (bu modül):
  - ``record_cancel_intent(run_id, requested_by)``: cancel_intents INSERT +
    outbox olayı TEK transaction'da; iş zaten terminal ise 'already_terminal'
    (terminal kazanır); iş yürütme BAŞLAMAMIŞ bekleyen durumdaysa
    ('accepted' | 'queued') execute hiç başlamadan iptal tamamlanır
    (pending→cancelled + terminal olay — execute-öncesi cancel engeli); iş
    'running' ise yalnız niyet kaydedilir ('recorded'; cancel intent kaydı
    TERMINAL DEĞİLDİR).
  - ``mark_cancelled_if_running(run_id)``: status='running' VE cancel intent
    VAR koşullu ATOMİK UPDATE → cancelled + terminal olay; aksi dokunmaz.
- Terminal-öncelik kuralı: completed commit'i cancel intent insert'ünden önce
  ise tamamlanma kazanır ('already_terminal'); intent önce kaydedildiyse
  complete_job 'rejected' döner (B6 tarafı) ve mark_cancelled_if_running
  cancelled üretir.

İş durumu kümesi B6 sözleşmesidir: accepted|queued|running|completed|
partially_completed|failed|cancelled (agent.jobs, run_id PK; migration 0003
ck_jobs_status). Tabloların migration'ı B6'ya aittir (alembic 0003); B7
testleri kendi scratch DB'sinde sözleşmenin bir alt kümesini kurar
(``tests/control/conftest.py``).

Terminal olay zarfları (agent.run.cancelled / agent.run.failed) B1 sözleşme
modelleriyle kurulur ve ``event_sequence`` B5'in ``run_event_sequences``
tablosundan atomik tahsis edilir (aynı tablo, aynı desen). Outbox kaydı ile
durum değişikliği AYNI transaction'dadır (B5 kuralının devamı).

Kaynaklar: [PG-ISOLATION#C2] Read Committed'ta koşullu UPDATE'in atomikliği;
[ENG-OUTBOX#C1] durum değişikliği ile olayın tek transaction'da yazımı.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import asyncpg

from .contracts import (
    SCHEMA_VERSION,
    AgentEnvelope,
    AgentRunCancelledV1,
    MESSAGE_TYPE_REGISTRY,
    Producer,
)

__all__ = [
    "ControlStore",
    "CancelIntentOutcome",
    "CancelIntentResult",
    "BackpressureSnapshot",
    "TERMINAL_JOB_STATUSES",
    "ACTIVE_JOB_STATUSES",
    "PENDING_JOB_STATUSES",
]

logger = logging.getLogger(__name__)

#: B6 sözleşmesindeki terminal iş durumları.
TERMINAL_JOB_STATUSES: tuple[str, ...] = ("completed", "failed", "cancelled")

#: Aktif (terminal olmayan) iş durumları: B4 kabulünün yazdığı 'accepted' DA
#: bekleyendir (job_store.CLAIMABLE_JOB_STATUSES ile aynı küme — W5
#: bütünleştirme bulgusu 1a). 'accepted' burada yoksa niyetli kabul işi ne
#: claim edilir ne reaper'ca kapatılır ve sonsuz 'accepted' asılı kalır.
ACTIVE_JOB_STATUSES: tuple[str, ...] = ("accepted", "queued", "running")

#: Yürütme BAŞLAMAMIŞ bekleyen durumlar: cancel niyeti bu işleri anında
#: terminal yapar (execute-öncesi engel). 'queued' ortak sözleşmenin, 'accepted'
#: B4 kabulünün bekleyen karşılığıdır; üretimde kabul 'accepted' yazar.
PENDING_JOB_STATUSES: tuple[str, ...] = ("accepted", "queued")


class CancelIntentOutcome:
    """record_cancel_intent sonuç sabitleri."""

    ALREADY_TERMINAL = "already_terminal"
    RECORDED = "recorded"
    QUEUED_CANCELLED = "queued_cancelled"


@dataclass(frozen=True)
class CancelIntentResult:
    """Tek cancel isteğinin depo sonucu."""

    outcome: str  # CancelIntentOutcome sabitleri
    intent_created: bool  # cancel_intents satırı bu çağrıda yazıldı mı
    job_status: str | None = None  # çağrı sonrası iş durumu
    outbox_message_id: str | None = None  # üretilen terminal olayın message_id'si


@dataclass(frozen=True)
class BackpressureSnapshot:
    """Kabul edilmiş iş backlog'u ölçümü (plan satır 422).

    Kuyruk derinliği broker tarafıdır (``control.BackpressureProbe`` ekler);
    buradaki alanlar kalıcı iş kaydının kendi ölçümüdür: kabullenilmiş ama
    henüz terminalleşmemiş iş sayısı ('accepted' + 'queued' + 'running') ve
    en eski işin yaşı.
    """

    accepted_backlog: int  # accepted + queued + running
    queued: int
    running: int
    oldest_active_age_seconds: float | None  # aktif en eski iş; aktif yoksa None
    oldest_active_run_id: str | None


class ControlStore:
    """``agent.cancel_intents`` + ``agent.jobs`` üzerinde B7 kontrol işlemleri.

    ``ControlStore`` yalnız ortak sözleşmedeki kolonları koşullu güncellemelerde
    kullanır (run_id, status, deadline_at, execution_attempt); terminal olay
    zarfı için gereken conversation/correlation bağlamı ÇAĞRANDAN ALINIR
    (kontrol komut zarfından) — store bu kimlikleri uydurmaz.
    """

    def __init__(self, pool: asyncpg.Pool, schema: str = "agent") -> None:
        self._pool = pool
        self._schema = schema

    # ------------------------------------------------------------- cancel niyeti

    async def record_cancel_intent(
        self,
        run_id: str,
        requested_by: str,
        *,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None = None,
        reason: str | None = None,
        requested_at: datetime | None = None,
        new_message_id: Callable[[], uuid.UUID] | None = None,
    ) -> CancelIntentResult:
        """Cancel intent + outbox olayını TEK transaction'da yazar.

        - İş yok (execute henüz gelmedi): yalnız niyet kalır; iş kabulünde
          başlatma engeli niyetin kendisidir (reaper finalize eder).
        - İş terminal: 'already_terminal' — terminal kazanır, durum değişmez.
        - İş yürütme başlamamış bekleyen ('accepted' | 'queued'):
          pending→cancelled + agent.run.cancelled olayı (aynı transaction) —
          execute hiç başlamadan biter ('accepted' dahil; bulgu 1a).
        - İş running: 'recorded' — niyet kaydı terminal değildir; worker B6
          ``complete_job``'in 'rejected' dönüşünden sonra
          ``mark_cancelled_if_running`` ile terminali üretir.
        """

        if not requested_by:
            raise ValueError("requested_by boş olamaz (istek sahibi kaydedilir)")
        uuid_fn = new_message_id or uuid.uuid4
        at = requested_at or datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchval(
                    f"INSERT INTO {self._schema}.cancel_intents (run_id, requested_at, requested_by) "
                    "VALUES ($1, $2, $3) ON CONFLICT (run_id) DO NOTHING RETURNING run_id",
                    uuid.UUID(run_id),
                    at,
                    requested_by,
                )

                job = await conn.fetchrow(
                    f"SELECT status, execution_attempt FROM {self._schema}.jobs "
                    "WHERE run_id = $1 FOR UPDATE",
                    uuid.UUID(run_id),
                )
                if job is None:
                    return CancelIntentResult(
                        outcome=CancelIntentOutcome.RECORDED,
                        intent_created=inserted is not None,
                        job_status=None,
                    )
                if job["status"] in TERMINAL_JOB_STATUSES:
                    return CancelIntentResult(
                        outcome=CancelIntentOutcome.ALREADY_TERMINAL,
                        intent_created=inserted is not None,
                        job_status=str(job["status"]),
                    )

                if job["status"] in PENDING_JOB_STATUSES:
                    message_id = await self._finalize_cancelled(
                        conn,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        correlation_id=correlation_id,
                        causation_id=causation_id,
                        reason=reason,
                        execution_attempt=int(job["execution_attempt"] or 0) or None,
                        occurred_at=at,
                        new_message_id=uuid_fn,
                    )
                    return CancelIntentResult(
                        outcome=CancelIntentOutcome.QUEUED_CANCELLED,
                        intent_created=inserted is not None,
                        job_status="cancelled",
                        outbox_message_id=message_id,
                    )

                return CancelIntentResult(
                    outcome=CancelIntentOutcome.RECORDED,
                    intent_created=inserted is not None,
                    job_status=str(job["status"]),
                )

    async def mark_cancelled_if_running(
        self,
        run_id: str,
        *,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None = None,
        reason: str | None = None,
        occurred_at: datetime | None = None,
        new_message_id: Callable[[], uuid.UUID] | None = None,
    ) -> str:
        """status='running' VE cancel intent VAR → cancelled (+ olay), aksi dokunulmaz.

        Koşullu UPDATE atomiktir: complete_job'in 'rejected' döndürdüğü yarışta
        terminali BURASI üretir; tamamlanmış/hiç koşmamış işe dokunmaz.
        Dönüş: 'cancelled' | 'untouched'.
        """

        uuid_fn = new_message_id or uuid.uuid4
        at = occurred_at or datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET status = 'cancelled' "
                    "WHERE run_id = $1 AND status = 'running' "
                    f"AND EXISTS (SELECT 1 FROM {self._schema}.cancel_intents WHERE run_id = $1) "
                    "RETURNING execution_attempt",
                    uuid.UUID(run_id),
                )
                if updated is None:
                    return "untouched"
                message_id = await self._finalize_cancelled(
                    conn,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    reason=reason,
                    execution_attempt=int(updated["execution_attempt"] or 0) or None,
                    occurred_at=at,
                    new_message_id=uuid_fn,
                )
        logger.info("running iş cancel intent ile iptal edildi: run_id=%s olay=%s", run_id, message_id)
        return "cancelled"

    async def has_cancel_intent(self, run_id: str) -> bool:
        """Aktif iptal niyeti var mı (worker başlangıç/DLQ replay doğrulaması okur)."""

        async with self._pool.acquire() as conn:
            return (
                await conn.fetchval(
                    f"SELECT 1 FROM {self._schema}.cancel_intents WHERE run_id = $1",
                    uuid.UUID(run_id),
                )
                is not None
            )

    # ------------------------------------------------------------------ inbox

    async def record_inbox_seen(
        self,
        *,
        consumer_name: str,
        envelope: AgentEnvelope,
        status: str = "accepted",
    ) -> bool:
        """Kontrol tüketici idempotency kaydı; True = bu çağrı ilk gören."""

        async with self._pool.acquire() as conn:
            inserted = await conn.fetchrow(
                f"INSERT INTO {self._schema}.inbox_messages "
                "(consumer_name, message_id, message_type, status, run_id) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (consumer_name, message_id) DO NOTHING "
                "RETURNING consumer_name",
                consumer_name,
                uuid.UUID(envelope.message_id),
                envelope.message_type,
                status,
                uuid.UUID(envelope.run_id) if envelope.run_id else None,
            )
            return inserted is not None

    # -------------------------------------------------------------- gözlem

    async def job_state(self, run_id: str) -> dict[str, Any] | None:
        """Durum + payload_hash + deadline (DLQ replay guard'ının sözleşmesi)."""

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT status, payload_hash, deadline_at, execution_attempt "
                f"FROM {self._schema}.jobs WHERE run_id = $1",
                uuid.UUID(run_id),
            )
        if row is None:
            return None
        return {
            "status": str(row["status"]),
            "payload_hash": str(row["payload_hash"]),
            "deadline_at": row["deadline_at"],
            "execution_attempt": int(row["execution_attempt"] or 0),
        }

    async def backpressure(self) -> BackpressureSnapshot:
        """Kabul edilmiş iş backlog'u + en eski aktif iş yaşı (plan satır 422)."""

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT "
                f"count(*) FILTER (WHERE status = ANY($1::text[])) AS backlog, "
                f"count(*) FILTER (WHERE status = 'queued') AS queued, "
                f"count(*) FILTER (WHERE status = 'running') AS running, "
                f"EXTRACT(EPOCH FROM (now() - min(accepted_at) FILTER (WHERE status = ANY($1::text[])))) AS oldest_age, "
                f"(array_agg(run_id ORDER BY accepted_at) FILTER (WHERE status = ANY($1::text[])))[1] AS oldest_run "
                f"FROM {self._schema}.jobs",
                list(ACTIVE_JOB_STATUSES),
            )
        assert row is not None
        return BackpressureSnapshot(
            accepted_backlog=int(row["backlog"] or 0),
            queued=int(row["queued"] or 0),
            running=int(row["running"] or 0),
            oldest_active_age_seconds=float(row["oldest_age"]) if row["oldest_age"] is not None else None,
            oldest_active_run_id=str(row["oldest_run"]) if row["oldest_run"] is not None else None,
        )

    # ---------------------------------------------------------- iç adımlar

    async def _finalize_cancelled(
        self,
        conn: asyncpg.Connection,
        *,
        run_id: str,
        conversation_id: str,
        correlation_id: str,
        causation_id: str | None,
        reason: str | None,
        execution_attempt: int | None,
        occurred_at: datetime,
        new_message_id: Callable[[], uuid.UUID],
    ) -> str:
        """İşi cancelled yapar (satır kilidi çağırandadır) + terminal olayı yazar."""

        await conn.execute(
            f"UPDATE {self._schema}.jobs SET status = 'cancelled' WHERE run_id = $1",
            uuid.UUID(run_id),
        )
        sequence = await self._allocate_sequence(conn, run_id)
        payload_model = AgentRunCancelledV1(
            **_clean(
                event_sequence=sequence,
                execution_attempt=execution_attempt,
                reason=reason,
            )
        )
        envelope = self._envelope(
            message_type="agent.run.cancelled",
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            payload=payload_model.model_dump(exclude_none=True),
            new_message_id=new_message_id,
        )
        await self._insert_outbox(conn, envelope=envelope, created_at=occurred_at)
        return envelope.message_id

    async def close_expired_job(
        self,
        run_id: str,
        *,
        conversation_id: str,
        correlation_id: str,
        terminal_status: str,
        payload: dict[str, Any],
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
        new_message_id: Callable[[], uuid.UUID] | None = None,
    ) -> bool:
        """Süresi geçmiş AKTİF işi terminal yapar (+ olay aynı transaction'da).

        ``reaper.py`` kullanır; koşul aktif durum kümesidir ('accepted' |
        'queued' | 'running') — bu arada worker tamamladıysa UPDATE satır
        bulamaz ve False döner (terminal kazanır, olay üretilmez).
        """

        if terminal_status not in TERMINAL_JOB_STATUSES:
            raise ValueError(f"terminal olmayan durum kapatılamaz: {terminal_status}")
        uuid_fn = new_message_id or uuid.uuid4
        at = occurred_at or datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET status = $2 "
                    "WHERE run_id = $1 AND status = ANY($3::text[]) "
                    "RETURNING execution_attempt",
                    uuid.UUID(run_id),
                    terminal_status,
                    list(ACTIVE_JOB_STATUSES),
                )
                if updated is None:
                    return False
                sequence = await self._allocate_sequence(conn, run_id)
                payload = dict(payload)
                payload["event_sequence"] = sequence
                message_type = f"agent.run.{terminal_status}"
                envelope = self._envelope(
                    message_type=message_type,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    occurred_at=at,
                    payload=payload,
                    new_message_id=uuid_fn,
                )
                await self._insert_outbox(conn, envelope=envelope, created_at=at)
        return True

    async def expired_active_jobs(self, *, limit: int = 50) -> list[asyncpg.Record]:
        """Deadline'ı geçmiş aktif işler (reaper adayı; SKIP LOCKED'sız okuma).

        ``correlation_id`` jobs tablosunda KOLON DEĞİLDİR (gerçek migration 0001);
        B4 kabul zarfının jsonb gövdesinden okunur — ``job_store``'un
        ``fail_expired_jobs_beyond_attempts`` ile aynı kaynak kuralı.
        """

        async with self._pool.acquire() as conn:
            return await conn.fetch(
                f"SELECT run_id, conversation_id, envelope->>'correlation_id' AS correlation_id, "
                f"status, deadline_at, execution_attempt "
                f"FROM {self._schema}.jobs "
                "WHERE status = ANY($1::text[]) AND deadline_at < now() "
                "ORDER BY deadline_at LIMIT $2",
                list(ACTIVE_JOB_STATUSES),
                limit,
            )

    async def pending_jobs_with_cancel_intent(self, *, limit: int = 50) -> list[asyncpg.Record]:
        """Cancel intent'i olan yürütme-başlamamış işler (accepted|queued).

        Execute-öncesi engel finalizer'ının adayları: üretim kabulü 'accepted'
        yazdığı için sorgu yalnız 'queued' sayarsa niyetli kabul işi sonsuza dek
        açık kalır (W5 bulgusu 1a). ``correlation_id`` kabul zarfından okunur
        (jobs kolonu değildir; gerçek migration 0001 şeması).
        """

        async with self._pool.acquire() as conn:
            return await conn.fetch(
                f"SELECT j.run_id, j.conversation_id, j.envelope->>'correlation_id' AS correlation_id, "
                f"j.execution_attempt "
                f"FROM {self._schema}.jobs j "
                f"JOIN {self._schema}.cancel_intents c ON c.run_id = j.run_id "
                "WHERE j.status = ANY($1::text[]) ORDER BY j.accepted_at LIMIT $2",
                list(PENDING_JOB_STATUSES),
                limit,
            )

    async def _allocate_sequence(self, conn: asyncpg.Connection, run_id: str) -> int:
        """Run başına atomik event_sequence (B5 tablosu, aynı desen)."""

        row = await conn.fetchrow(
            f"INSERT INTO {self._schema}.run_event_sequences (run_id, last_sequence, updated_at) "
            "VALUES ($1, 1, now()) "
            f"ON CONFLICT (run_id) DO UPDATE SET "
            f"last_sequence = {self._schema}.run_event_sequences.last_sequence + 1, "
            "updated_at = now() "
            "RETURNING last_sequence",
            uuid.UUID(run_id),
        )
        return int(row["last_sequence"]) if row else 1

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
        new_message_id: Callable[[], uuid.UUID],
    ) -> AgentEnvelope:
        spec_entry = MESSAGE_TYPE_REGISTRY[message_type]  # sözleşme dışı tür reddedilir
        # Payload B1 modeliyle doğrulanır: şema dışı terminal olay üretilemez.
        validated = spec_entry.payload_model.model_validate(payload)
        return AgentEnvelope(
            **_clean(
                message_id=str(new_message_id()),
                message_type=message_type,
                schema_version=SCHEMA_VERSION,
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=_utc(occurred_at),
                producer=Producer.AGENT_PY,
                payload=validated.model_dump(exclude_none=True),
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


def _clean(**kwargs: Any) -> dict[str, Any]:
    """None değerli anahtarları atar (TransportModel null taşınmaz kuralı)."""

    return {key: value for key, value in kwargs.items() if value is not None}


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
