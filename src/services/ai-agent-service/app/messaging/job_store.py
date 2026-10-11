"""Kalıcı iş kabulü deposu (B4): inbox + job + outbox tek transaction'da.

Plan B4 transaction adımlarının DB karşılığı:

1. Envelope/payload doğrulama çağıran taraftadır (``intake.handle_delivery``;
   B1 ``parse_envelope`` sözleşmeleri — DONMUŞ).
2. Producer/tür politikası çağıran taraftadır; burada yalnız kabul edilmiş
   execute komutu işlenir.
3. ``message_id`` için consumer kapsamlı inbox benzersizliği:
   ``agent.inbox_messages`` PK (consumer_name, message_id).
4. ``run_id + payload_hash`` için idempotent iş kabulü: ``agent.jobs.run_id``
   UNIQUE; aynı run_id farklı payload_hash → ``JobPayloadConflict``.
5. AgentJob + accepted olayı outbox kaydı AYNI transaction'da.
6. Commit bu modülün transaction bloğunun sonunda yapılır.
7. ACK çağıran taraftadır: commit döndükten SONRA broker'a ack verilir
   (``intake.handle_delivery`` normal döner; B2 consumer base ack eder).

Inbox satırına "görüldü" işaretiyle tamamlanma yazılmaz: satır yalnız iş kabulü
ile atomik doğar (plan: "Job kalıcı olarak oluşmadan mesajın sorumluluğu
devralınmış sayılmasın"). Commit öncesi çökme rollback ile kurtarılır (satır
yok); commit sonrası çökmede tekrar teslim inbox/job'a çarpar ve yeni iş
yaratmadan ACK alır.

Kaynaklar: [ENG-OUTBOX#C1] iş verisiyle mesajın aynı transaction'da
saklanması; [ENG-OUTBOX#C2] relay tekrarlarına karşı consumer idempotency;
[PG-ISOLATION#C2] Read Committed'ta eşzamanlı yazan işlemi bekleme ve güncel
satırı yeniden değerlendirme davranışı: farklı message_id ile gelen aynı
run_id'li paralel teslimde ikinci INSERT unique endeksde engellenir, hata
yakalanır ve mevcut job yeniden okunarak hash karşılaştırması yapılır.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import asyncpg

from .contracts import (
    AgentEnvelope,
    MESSAGE_TYPE_REGISTRY,
    ParsedEnvelope,
    Producer,
    SCHEMA_VERSION,
)

__all__ = [
    "JobStore",
    "AcceptOutcome",
    "JobPayloadConflict",
    "compute_payload_hash",
    "build_accepted_envelope",
    "ACCEPTED_MESSAGE_TYPE",
    "JOB_STATUS_ACCEPTED",
]

logger = logging.getLogger(__name__)

ACCEPTED_MESSAGE_TYPE = "agent.run.accepted"

#: Job durum makinesinin B4'teki tek değeri; B6 lease/execution durumlarını
#: yeni migration ile genişletir (bkz. ck_jobs_status).
JOB_STATUS_ACCEPTED = "accepted"

INBOX_STATUS_ACCEPTED = "accepted"
INBOX_STATUS_CONFLICT = "conflict"


class JobPayloadConflict(Exception):
    """Aynı run_id farklı payload ile kabul edilmeye çalışıldı (plan B4: çatışma raporlanır)."""

    def __init__(self, run_id: str, existing_hash: str, incoming_hash: str) -> None:
        self.run_id = run_id
        self.existing_hash = existing_hash
        self.incoming_hash = incoming_hash
        super().__init__(
            f"run_id {run_id} için iş zaten farklı payload ile kabul edilmiş "
            f"(mevcut {existing_hash[:12]}…, gelen {incoming_hash[:12]}…)"
        )


@dataclass(frozen=True)
class AcceptOutcome:
    """Tek teslimin kabul sonucu; normal dönüş ACK ile, çatışma istisnası DLQ ile sonuçlanır."""

    outcome: str  # "created" | "duplicate_inbox" | "duplicate_job"
    job_id: uuid.UUID | None = None
    outbox_id: uuid.UUID | None = None
    detail: str = ""


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """Payload'ın kanonik JSON SHA-256 özeti (anahtar sırasından bağımsız)."""

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def format_utc(dt: datetime) -> str:
    """UtcIsoString sözleşme biçimi ('Z' sonekli UTC ISO 8601)."""

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_accepted_envelope(
    parsed: ParsedEnvelope,
    *,
    accepted_at: datetime,
    new_message_id: Callable[[], uuid.UUID],
) -> AgentEnvelope:
    """Kabul edilen işin ``agent.run.accepted`` olay zarfını üretir.

    Yeni mantıksal mesaj: yeni message_id; correlation_id zinciri korunur,
    causation_id bu olayı doğuran komutun message_id'sidir. event_sequence 0
    intake'in ilk olayıdır; B5 run başına atomik sıra üretimini devralır
    (plan satır 237: transport tekrarı ile yürütme denemesi ayrıdır).
    """

    return AgentEnvelope(
        message_id=str(new_message_id()),
        message_type=ACCEPTED_MESSAGE_TYPE,
        schema_version=SCHEMA_VERSION,
        run_id=parsed.envelope.run_id,
        conversation_id=parsed.envelope.conversation_id,
        correlation_id=parsed.envelope.correlation_id,
        causation_id=parsed.envelope.message_id,
        occurred_at=format_utc(accepted_at),
        producer=Producer.AGENT_PY,
        payload={
            "event_sequence": 0,
            "accepted_at": format_utc(accepted_at),
        },
    )


class JobStore:
    """``agent`` schema'sı üzerinde iş kabulü ve outbox erişimi (D011 sahipliği)."""

    def __init__(self, pool: asyncpg.Pool, schema: str = "agent") -> None:
        self._pool = pool
        self._schema = schema

    # ------------------------------------------------------------------ kabul

    async def accept_execution(
        self,
        parsed: ParsedEnvelope,
        *,
        consumer_name: str,
        now: Callable[[], datetime] | None = None,
        new_uuid: Callable[[], uuid.UUID] | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> AcceptOutcome:
        """Execute komutunu idempotent olarak kabul eder (B4 transaction 3→6).

        ``on_event`` yalnız çökme senaryosu testine yönelik kansız kancadır:
        "pre_commit" transaction İÇİNDE çağrılır (yükseltirse rollback),
        "post_commit" commit'ten sonra (yükseltirse teslim ACK'sız kalır ve
        broker tekrar teslim eder). Üretimde None kalır.
        """

        envelope = parsed.envelope
        if envelope.run_id is None or envelope.conversation_id is None:
            raise ValueError("execute komutu run kimliği taşımalıdır (parse_envelope bunu zorunlu kılar)")
        now_fn = now or (lambda: datetime.now(timezone.utc))
        uuid_fn = new_uuid or uuid.uuid4
        incoming_hash = compute_payload_hash(envelope.payload)
        accepted_at = now_fn()

        # Hızlı yol: bu mesaj daha önce tamamen işlendi mi? (B4 adım 3)
        existing = await self._fetch_inbox(consumer_name, envelope.message_id)
        if existing is not None:
            return AcceptOutcome(outcome="duplicate_inbox", detail="inbox kaydı mevcut")

        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    inbox_inserted = await self._insert_inbox(
                        conn,
                        consumer_name=consumer_name,
                        envelope=envelope,
                        status=INBOX_STATUS_ACCEPTED,
                        now=accepted_at,
                    )
                    if not inbox_inserted:
                        # Eşzamanlı ikinci teslim inbox'ı doldurdu: işlenmiş sayılır.
                        return AcceptOutcome(
                            outcome="duplicate_inbox", detail="inbox paralel dolduruldu"
                        )

                    job = await self._fetch_job_for_update(conn, envelope.run_id)
                    if job is not None:
                        if job["payload_hash"] != incoming_hash:
                            raise _ConflictSignal(job["payload_hash"], incoming_hash)
                        return AcceptOutcome(
                            outcome="duplicate_job",
                            job_id=job["job_id"],
                            detail="aynı run_id ve payload_hash; mevcut iş yeni graph başlatılmadan onaylanır",
                        )

                    if on_event is not None:
                        on_event("pre_commit")  # test kancası: rollback penceresi

                    job_id = uuid_fn()
                    await self._insert_job(
                        conn,
                        job_id=job_id,
                        envelope=envelope,
                        payload_hash=incoming_hash,
                        accepted_at=accepted_at,
                    )
                    accepted_event = build_accepted_envelope(
                        parsed, accepted_at=accepted_at, new_message_id=uuid_fn
                    )
                    outbox_id = await self._insert_outbox_event(
                        conn, envelope=accepted_event, created_at=accepted_at
                    )
                # Bağlam çıkışı = COMMIT (adım 6).
            if on_event is not None:
                on_event("post_commit")  # test kancası: ACK kaybı/çökme penceresi
            return AcceptOutcome(outcome="created", job_id=job_id, outbox_id=outbox_id)
        except _ConflictSignal as signal:
            await self._record_conflict(
                consumer_name=consumer_name,
                envelope=envelope,
                incoming_hash=incoming_hash,
                existing_hash=signal.existing_hash,
                now=now_fn(),
            )
            raise JobPayloadConflict(
                envelope.run_id, signal.existing_hash, signal.incoming_hash
            ) from None
        except asyncpg.exceptions.UniqueViolationError:
            # Farklı message_id ile aynı run_id'yi paralel kabul yarışı: ikinci
            # INSERT unique endekste engellendi ([PG-ISOLATION#C2] bekleme ve
            # hata davranışı). Mevcut job yeniden okunup hash karşılaştırılır.
            job = await self._fetch_job(envelope.run_id)
            if job is not None and job["payload_hash"] == incoming_hash:
                await self._record_duplicate_inbox(consumer_name, envelope, now_fn())
                return AcceptOutcome(
                    outcome="duplicate_job",
                    job_id=job["job_id"],
                    detail="paralel kabul yarışında mevcut iş bulundu",
                )
            existing_hash = job["payload_hash"] if job is not None else ""
            await self._record_conflict(
                consumer_name=consumer_name,
                envelope=envelope,
                incoming_hash=incoming_hash,
                existing_hash=existing_hash,
                now=now_fn(),
            )
            raise JobPayloadConflict(
                envelope.run_id, existing_hash, incoming_hash
            ) from None

    # ------------------------------------------------------- yardımcı sorgular

    async def _fetch_inbox(self, consumer_name: str, message_id: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT consumer_name, message_id, status FROM {self._schema}.inbox_messages "
                "WHERE consumer_name = $1 AND message_id = $2",
                consumer_name,
                uuid.UUID(message_id),
            )

    async def _insert_inbox(
        self,
        conn: asyncpg.Connection,
        *,
        consumer_name: str,
        envelope: AgentEnvelope,
        status: str,
        now: datetime,
    ) -> bool:
        inserted = await conn.fetchrow(
            f"INSERT INTO {self._schema}.inbox_messages "
            "(consumer_name, message_id, message_type, status, run_id, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (consumer_name, message_id) DO NOTHING "
            "RETURNING consumer_name",
            consumer_name,
            uuid.UUID(envelope.message_id),
            envelope.message_type,
            status,
            uuid.UUID(envelope.run_id) if envelope.run_id else None,
            now,
        )
        return inserted is not None

    async def _record_duplicate_inbox(
        self, consumer_name: str, envelope: AgentEnvelope, now: datetime
    ) -> None:
        """Kabul yarışını kaybeden teslim için inbox kaydını tamamlar (idempotent)."""

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._insert_inbox(
                    conn,
                    consumer_name=consumer_name,
                    envelope=envelope,
                    status=INBOX_STATUS_ACCEPTED,
                    now=now,
                )

    async def _fetch_job_for_update(self, conn: asyncpg.Connection, run_id: str) -> asyncpg.Record | None:
        return await conn.fetchrow(
            f"SELECT job_id, payload_hash FROM {self._schema}.jobs "
            "WHERE run_id = $1 FOR UPDATE",
            uuid.UUID(run_id),
        )

    async def _fetch_job(self, run_id: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT job_id, payload_hash FROM {self._schema}.jobs WHERE run_id = $1",
                uuid.UUID(run_id),
            )

    async def _insert_job(
        self,
        conn: asyncpg.Connection,
        *,
        job_id: uuid.UUID,
        envelope: AgentEnvelope,
        payload_hash: str,
        accepted_at: datetime,
    ) -> None:
        await conn.execute(
            f"INSERT INTO {self._schema}.jobs "
            "(job_id, run_id, conversation_id, origin_message_id, payload_hash, "
            "payload, envelope, status, deadline_at, accepted_at) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)",
            job_id,
            uuid.UUID(envelope.run_id),
            uuid.UUID(envelope.conversation_id),
            uuid.UUID(envelope.message_id),
            payload_hash,
            json.dumps(envelope.payload, ensure_ascii=False),
            envelope.model_dump_json(exclude_none=True),
            JOB_STATUS_ACCEPTED,
            _parse_iso(envelope.deadline_at) if envelope.deadline_at else accepted_at,
            accepted_at,
        )

    async def _insert_outbox_event(
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

    async def _record_conflict(
        self,
        *,
        consumer_name: str,
        envelope: AgentEnvelope,
        incoming_hash: str,
        existing_hash: str,
        now: datetime,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._insert_inbox(
                    conn,
                    consumer_name=consumer_name,
                    envelope=envelope,
                    status=INBOX_STATUS_CONFLICT,
                    now=now,
                )
        logger.warning(
            "job kabul çatışması raporlandı: run_id=%s mevcut_hash=%s gelen_hash=%s message_id=%s",
            envelope.run_id,
            existing_hash,
            incoming_hash,
            envelope.message_id,
        )

    # ------------------------------------------------------------------ outbox

    async def claim_outbox_batch(
        self, *, limit: int, lease_seconds: float = 30.0
    ) -> list[asyncpg.Record]:
        """Yayınlamayı bekleyen kayıtları lease ile ayırır (FOR UPDATE SKIP LOCKED).

        Aynı kaydı birden fazla relay'in kontrolsüz almasını engeller; relay
        çökmesinde kayıt ``claimed_until`` bitiminde tekrar alınır. Confirm
        gelmeyen kayıt beklemede kalır (plan B3 publisher kuralı).
        """

        async with self._pool.acquire() as conn:
            return await conn.fetch(
                f"UPDATE {self._schema}.outbox_events SET "
                "publish_attempts = publish_attempts + 1, "
                "claimed_until = now() + make_interval(secs => $2) "
                "WHERE outbox_id IN ("
                f"  SELECT outbox_id FROM {self._schema}.outbox_events "
                "  WHERE published_at IS NULL AND (claimed_until IS NULL OR claimed_until < now()) "
                "  ORDER BY created_at "
                "  LIMIT $1 "
                "  FOR UPDATE SKIP LOCKED) "
                "RETURNING outbox_id, message_id, message_type, exchange, routing_key, envelope",
                limit,
                lease_seconds,
            )

    async def mark_outbox_published(self, outbox_id: uuid.UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {self._schema}.outbox_events SET published_at = now(), "
                "claimed_until = NULL, last_error = NULL WHERE outbox_id = $1",
                outbox_id,
            )

    async def record_outbox_failure(self, outbox_id: uuid.UUID, error: str) -> None:
        """Confirm kaybı/yayın hatası: kayıt beklemede kalır, hata görünür yazılır."""

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {self._schema}.outbox_events SET last_error = $2, "
                "claimed_until = NULL WHERE outbox_id = $1",
                outbox_id,
                error,
            )

    # ------------------------------------------------------------- gözlem için

    async def fetch_job(self, run_id: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT job_id, run_id, payload_hash, status, accepted_at "
                f"FROM {self._schema}.jobs WHERE run_id = $1",
                uuid.UUID(run_id),
            )

    async def count_jobs(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(f"SELECT count(*) FROM {self._schema}.jobs")

    async def count_outbox(self, *, pending_only: bool = False) -> int:
        async with self._pool.acquire() as conn:
            where = "WHERE published_at IS NULL" if pending_only else ""
            return await conn.fetchval(f"SELECT count(*) FROM {self._schema}.outbox_events {where}")

    async def count_inbox(self, *, status: str | None = None) -> int:
        async with self._pool.acquire() as conn:
            if status:
                return await conn.fetchval(
                    f"SELECT count(*) FROM {self._schema}.inbox_messages WHERE status = $1", status
                )
            return await conn.fetchval(f"SELECT count(*) FROM {self._schema}.inbox_messages")


class _ConflictSignal(Exception):
    """accept_execution içinden çatışma sinyali; dışarı JobPayloadConflict olarak çıkar."""

    def __init__(self, existing_hash: str, incoming_hash: str) -> None:
        self.existing_hash = existing_hash
        self.incoming_hash = incoming_hash


def _parse_iso(value: str) -> datetime:
    raw_format = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(value, raw_format).replace(tzinfo=timezone.utc)
