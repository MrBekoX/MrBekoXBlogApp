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

Wire sürümü (K4, migration 0005): kabul edilen işin ``wire_version``'ı execute
zarfının ``schema_version``'ıdır ve run boyunca değişmez; accepted olayı, deneme
tükenmesi kapanışı ve worker'ın terminal olayları bu sürümle kurulur, outbox
satırının routing key'i zarfın kendi sürümünden gelir (``wire.outbox_route``).
``payload_hash`` mesaj başınadır: aynı run_id'nin farklı sürümlü payload'ı
çatışmadır. Claim yalnız bu kodun yürütebildiği sürümleri seçer
(``wire_version <= WORKER_WIRE_MAX``); eski worker'ı DB tetikleyicisi dışlar.

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
    WIRE_VERSION_V1,
    AgentEnvelope,
    ParsedEnvelope,
)
from .wire import (
    WORKER_WIRE_MAX,
    WORKER_WIRE_MAX_SETTING,
    compose_run_envelope,
    normalize_wire_version,
    outbox_route,
)

__all__ = [
    "JobStore",
    "AcceptOutcome",
    "JobPayloadConflict",
    "compute_payload_hash",
    "build_accepted_envelope",
    "ACCEPTED_MESSAGE_TYPE",
    "JOB_STATUS_ACCEPTED",
    # B6: lease / fencing / terminal guard (ADDITIVE)
    "ClaimedJob",
    "TerminalWriteResult",
    "JOB_STATUS_QUEUED",
    "JOB_STATUS_RUNNING",
    "CLAIMABLE_JOB_STATUSES",
    "QUEUE_CLASS_FAST",
    "QUEUE_CLASS_RESEARCH",
]

logger = logging.getLogger(__name__)

ACCEPTED_MESSAGE_TYPE = "agent.run.accepted"

#: Job durum makinesinin B4'teki tek değeri; B6 lease/execution durumlarını
#: yeni migration ile genişletir (bkz. ck_jobs_status).
JOB_STATUS_ACCEPTED = "accepted"

# --- B6: iş durum makinesinin genişletilmesi (migration 0003) -----------------

#: Bekleyen iş (ortak sözleşmedeki karşılık); claim edilebilir.
JOB_STATUS_QUEUED = "queued"
#: Claim edilmiş, lease sahibi worker'da yürütülüyor.
JOB_STATUS_RUNNING = "running"

#: Claim'in seçtiği bekleyen durumlar: B4 kabulünün yazdığı 'accepted' KORUNUR
#: (mevcut kabul yazımı değişmez — additive kural) ve sözleşmedeki 'queued'
#: değeri de bekleyen sayılır (B7 test double'ları bu değeri yazar).
CLAIMABLE_JOB_STATUSES = (JOB_STATUS_ACCEPTED, JOB_STATUS_QUEUED)

#: Yürütme kapasitesi sınıfları (plan B6: derin araştırma ayrı kapasite).
QUEUE_CLASS_FAST = "fast"
QUEUE_CLASS_RESEARCH = "research"

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


# --- B6: claim / lease / fencing veri tipleri (ADDITIVE) ----------------------


@dataclass(frozen=True)
class ClaimedJob:
    """``claim_next_job`` sonucu: worker'a devredilmiş iş.

    ``fencing_token`` global ``agent.job_fencing_seq`` dizisinden claim anında
    tahsis edilir; her yeni claim'de KESİN artar. Eski denemenin token'ı ile
    terminal yazımı guard'da reddedilir (plan B6: "Eski worker'ın yeni
    denemenin sonucunu ezmesini fencing kontrolüyle engelle").
    """

    job_id: uuid.UUID
    run_id: str
    conversation_id: str
    #: Execute komutunun message_id'si; olay zincirinde causation_id kaynağı.
    origin_message_id: str
    #: Execute komut payload'ı (sözleşme doğrulaması intake'te yapıldı).
    payload: dict[str, Any]
    #: Kabul zarfı (B4'te saklanan; kimlik alanlarının tek kaynağı).
    envelope: AgentEnvelope
    queue_class: str
    deadline_at: datetime | None
    execution_attempt: int
    fencing_token: int
    accepted_at: datetime
    started_at: datetime | None
    #: Bu claim bir recovery mi? (önceki denemenin lease'i bitmiş.)
    recovered: bool = False
    #: Run'ın wire sürümü (``agent.jobs.wire_version``); tüm run mesajları bununla kurulur.
    wire_version: int = WIRE_VERSION_V1


@dataclass(frozen=True)
class TerminalWriteResult:
    """``complete_job``/``fail_job`` sonucu.

    ``outcome`` 'completed'/'failed' ise terminal yazımı ve (verildiyse)
    terminal olay outbox'a AYNI transaction'da yazıldı demektir. 'rejected'
    ise ``reason`` gerekçeyi taşır: ``not_found`` | ``not_running`` (iş
    terminalde) | ``fencing_mismatch`` (eski deneme) | ``cancel_requested``
    (aktif iptal niyeti var — terminal 'cancelled' geçişini B7 üretir) |
    ``wire_isolated`` (iş, oturumun ``agent.worker_wire_max`` değerinden yüksek
    sürümde; 0005 tetikleyicisi güncellemeyi atladı).
    """

    outcome: str  # "completed" | "failed" | "rejected"
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.outcome != "rejected"


def format_utc(dt: datetime) -> str:
    """UtcIsoString sözleşme biçimi ('Z' sonekli UTC ISO 8601)."""

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_envelope_json(raw: Any) -> AgentEnvelope:
    """asyncpg jsonb kolonunu (str) AgentEnvelope'a çözümler (outbox.py deseni)."""

    if isinstance(raw, (str, bytes, bytearray)):
        data = json.loads(raw)
    else:
        data = raw
    return AgentEnvelope.model_validate(data)


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
    Sürüm, kabul edilen execute komutunun sürümüdür (run wire sürümü, K4).
    """

    assert parsed.envelope.run_id is not None and parsed.envelope.conversation_id is not None
    return compose_run_envelope(
        schema_version=parsed.envelope.schema_version,
        message_type=ACCEPTED_MESSAGE_TYPE,
        run_id=parsed.envelope.run_id,
        conversation_id=parsed.envelope.conversation_id,
        correlation_id=parsed.envelope.correlation_id,
        causation_id=parsed.envelope.message_id,
        occurred_at=format_utc(accepted_at),
        new_message_id=new_message_id,
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
            "payload, envelope, status, deadline_at, accepted_at, wire_version) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11)",
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
            # Run wire sürümü = kabul edilen execute zarfının sürümü (K4; değişmez).
            normalize_wire_version(envelope.schema_version),
        )

    async def _insert_outbox_event(
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
                "  ORDER BY created_at, outbox_id "
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

    # ------------------------------------------------- B6: claim / lease / guard
    #
    # Ortak store sözleşmesi (entegrasyon sahibi tanımı): claim FOR UPDATE SKIP
    # LOCKED ile tek worker'a devreder [PG-ISOLATION#C2]; fencing_token global
    # diziden kesin artar; complete/fail ATOMİK guard'la yalnız sahibini kabul
    # eder. Terminal yazımı ile terminal olayın outbox'a yazımı AYNI
    # transaction'dadır (plan B5 kuralının B6 terminal yoluna uygulanışı).
    #
    # Eski worker'ın yeniden sahiplenilmiş işe yazamaması üç satırla garanti
    # edilir: (1) her claim execution_attempt'i artırır ve YENİ fencing_token
    # alır; (2) complete/fail koşulu status='running' VE fencing eş VE aktif
    # cancel intent yok; (3) koşul bozulursa satır güncellenmez ve 'rejected'
    # döner. [RMQ-RELIABILITY#C1] at-least-once teslimde çift yürütme
    # mükellefiyatının DB tarafındaki karşılığı budur.

    async def claim_next_job(
        self,
        worker_id: str,
        *,
        lease_seconds: float,
        queue_class: str | tuple[str, ...] | list[str] = QUEUE_CLASS_FAST,
        max_execution_attempts: int = 3,
        now: Callable[[], datetime] | None = None,
    ) -> ClaimedJob | None:
        """Bekleyen (veya lease'i bitmiş) bir işi bu worker'a devreder.

        - Seçim ``FOR UPDATE SKIP LOCKED`` ile yapılır: iki worker aynı anda
          claim çağırdığında iş TEK worker'a gider, diğeri kendi sorgusunda
          satırı görmez (kilitlenen satır atlanır).
        - Claim edilen iş ``status='running'`` olur; ``execution_attempt`` bir
          artar; YENİ ``fencing_token`` tahsis edilir.
        - SINIRLI recovery: ``status='running'`` ve ``lease_until`` bitmiş iş
          yalnız ``execution_attempt < max_execution_attempts`` iken yeniden
          claim edilir (plan B6: "süresi geçen işi SINIRLI recovery ile yeniden
          sahiplen"); sınırı aşan işler ``fail_expired_jobs_beyond_attempts``
          ile kapatılır.
        - Süresi geçmiş (``deadline_at <= now()``) iş claim edilmez; terminal
          kapanışı B7 reaper politikasındadır.
        - Aktif iptal niyeti olan iş claim edilmez: iptal, yeni yürütme
          başlatmaz (plan B7: "Execute komutu henüz gelmediyse iptal kaydı
          erken başlatmayı engellesin" ilkesinin recovery karşılığı).
        - Yalnız bu kodun yürütebildiği wire sürümleri seçilir
          (``wire_version <= WORKER_WIRE_MAX``): bilinmeyen gelecek sürüm kuyruğun
          başını tıkamaz. DB tetikleyicisi (0005) aynı sınırı oturum GUC'uyla
          ikinci kez uygular (eski worker kodu v2 satırını güncelleyemez).
        """

        classes = [queue_class] if isinstance(queue_class, str) else list(queue_class)
        async with self._pool.acquire() as conn:
            # CTE, satırı FOR UPDATE SKIP LOCKED ile seçipclaim öncesi durumunu
            # taşır (RETURNING yalnız GÜNCEL satırı gördüğü için "recovery mi?"
            # bilgisi CTE'den gelir); dış UPDATE tek satırı durum geçirir.
            row = await conn.fetchrow(
                f"WITH picked AS ("
                f"  SELECT c.job_id, (c.status = {JOB_STATUS_RUNNING!r}) AS was_recoverable "
                f"  FROM {self._schema}.jobs c "
                "  WHERE c.queue_class = ANY($3::text[]) "
                "    AND ("
                f"      c.status = ANY($4::text[]) "
                f"      OR (c.status = {JOB_STATUS_RUNNING!r} "
                "          AND c.lease_until IS NOT NULL AND c.lease_until < now() "
                "          AND c.execution_attempt < $5) "
                "    ) "
                "    AND (c.deadline_at IS NULL OR c.deadline_at > now()) "
                "    AND NOT EXISTS ("
                f"      SELECT 1 FROM {self._schema}.cancel_intents x WHERE x.run_id = c.run_id) "
                "    AND c.wire_version <= $6 "
                "  ORDER BY c.accepted_at, c.job_id "
                "  LIMIT 1 "
                "  FOR UPDATE SKIP LOCKED"
                ") "
                f"UPDATE {self._schema}.jobs j SET "
                f"status = {JOB_STATUS_RUNNING!r}, "
                "lease_owner = $1, "
                "lease_until = now() + make_interval(secs => $2), "
                "execution_attempt = j.execution_attempt + 1, "
                f"fencing_token = nextval('{self._schema}.job_fencing_seq'), "
                "started_at = COALESCE(j.started_at, now()) "
                "FROM picked p "
                "WHERE j.job_id = p.job_id "
                "RETURNING j.job_id, j.run_id, j.conversation_id, j.origin_message_id, "
                "j.payload, j.envelope, j.queue_class, j.deadline_at, j.execution_attempt, "
                "j.fencing_token, j.accepted_at, j.started_at, j.wire_version, p.was_recoverable",
                worker_id,
                float(lease_seconds),
                classes,
                list(CLAIMABLE_JOB_STATUSES),
                int(max_execution_attempts),
                int(WORKER_WIRE_MAX),
            )
        if row is None:
            return None
        return ClaimedJob(
            job_id=row["job_id"],
            run_id=str(row["run_id"]),
            conversation_id=str(row["conversation_id"]),
            origin_message_id=str(row["origin_message_id"]),
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            envelope=_decode_envelope_json(row["envelope"]),
            queue_class=row["queue_class"],
            deadline_at=row["deadline_at"],
            execution_attempt=int(row["execution_attempt"]),
            fencing_token=int(row["fencing_token"]),
            accepted_at=row["accepted_at"],
            started_at=row["started_at"],
            recovered=bool(row["was_recoverable"]),
            wire_version=normalize_wire_version(row["wire_version"]),
        )

    async def renew_lease(
        self, run_id: str, fencing_token: int, lease_seconds: float
    ) -> bool:
        """Lease'i SADECE sahibiyseniz uzatır (plan B6: "yalnız sahibiyse").

        Fencing token eşleşmezse (iş yeniden claim edilmişse) veya iş artık
        running değilse ``False`` döner; çağıran worker yürütmesini bırakmalıdır.
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE {self._schema}.jobs SET "
                "lease_until = now() + make_interval(secs => $3) "
                "WHERE run_id = $1 AND status = $4 AND fencing_token = $2 "
                "RETURNING job_id",
                uuid.UUID(run_id),
                int(fencing_token),
                float(lease_seconds),
                JOB_STATUS_RUNNING,
            )
        return row is not None

    async def complete_job(
        self,
        run_id: str,
        result_json: dict[str, Any],
        fencing_token: int,
        *,
        outbox_event: AgentEnvelope | None = None,
    ) -> TerminalWriteResult:
        """İşi ATOMİK guard'la tamamlar; terminal olayı aynı transaction'da yazar.

        Guard: ``status='running'`` VE ``fencing_token`` eş VE aktif iptal
        niyeti yok. Koşul sağlanmazsa hiçbir şey yazılmaz ve ``rejected``
        döner (gerekçe ``reason``'da): eski denemenin sonucu yeni denemeyi
        EZMEZ; tamamlanma/iptal yarışında terminal-öncelik kuralı DB
        kısıtlarıyla uygulanır.

        ``outbox_event`` verilirse event_sequence aynı transaction'da tahsis
        edilip payload'a yazılır ve outbox kaydı eklenir — terminal sonuçla
        iş durum değişikliği tek atomik birimdir (plan B5 kuralı).
        """

        return await self._terminal_transition(
            run_id,
            result_json=result_json,
            fencing_token=fencing_token,
            target_status="completed",
            outbox_event=outbox_event,
        )

    async def fail_job(
        self,
        run_id: str,
        result_json: dict[str, Any],
        fencing_token: int,
        *,
        outbox_event: AgentEnvelope | None = None,
    ) -> TerminalWriteResult:
        """İşi ``complete_job`` ile AYNI guard'la başarısız kılar."""

        return await self._terminal_transition(
            run_id,
            result_json=result_json,
            fencing_token=fencing_token,
            target_status="failed",
            outbox_event=outbox_event,
        )

    async def _terminal_transition(
        self,
        run_id: str,
        *,
        result_json: dict[str, Any],
        fencing_token: int,
        target_status: str,
        outbox_event: AgentEnvelope | None,
    ) -> TerminalWriteResult:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # ÖN KİLİT (W5 bütünleştirme yarış düzeltmesi): satırı guard'dan
                # ÖNCE FOR UPDATE ile kilitle. READ COMMITTED'ta UPDATE'in
                # snapshot'ı statement başında alınır; kilit beklemesi sırasında
                # commit olan bir cancel intent guard'ın NOT EXISTS'ine görünmez
                # ve 'intent-önce → complete kazandı' ihlali doğardı. record_
                # cancel_intent de jobs satırını FOR UPDATE ile kilitlediği için
                # ön kilit iki transaction'ı satır üstünde serileştirir: guard
                # HER ZAMAN niyetin commit kararından sonra değerlendirilir.
                locked = await conn.fetchrow(
                    f"SELECT job_id FROM {self._schema}.jobs WHERE run_id = $1 FOR UPDATE",
                    uuid.UUID(run_id),
                )
                if locked is None:
                    return TerminalWriteResult(outcome="rejected", reason="not_found")
                updated = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET "
                    f"status = $4, result_json = $2::jsonb, "
                    "lease_owner = NULL, lease_until = NULL "
                    "WHERE run_id = $1 AND status = $3 AND fencing_token = $5 "
                    "AND NOT EXISTS ("
                    f"  SELECT 1 FROM {self._schema}.cancel_intents c WHERE c.run_id = $1) "
                    "RETURNING job_id",
                    uuid.UUID(run_id),
                    json.dumps(result_json, ensure_ascii=False),
                    JOB_STATUS_RUNNING,
                    target_status,
                    int(fencing_token),
                )
                if updated is None:
                    reason = await self._diagnose_rejection(conn, run_id, fencing_token)
                    return TerminalWriteResult(outcome="rejected", reason=reason)
                if outbox_event is not None:
                    await self._write_outbox_with_sequence(conn, run_id, outbox_event)
                return TerminalWriteResult(outcome=target_status, reason=None)

    async def _diagnose_rejection(
        self, conn: asyncpg.Connection, run_id: str, fencing_token: int
    ) -> str:
        """Red gerekçesini ayırt eder (izlenebilirlik; davranış değişmez)."""

        row = await conn.fetchrow(
            f"SELECT status, fencing_token, wire_version, "
            f"coalesce(nullif(current_setting('{WORKER_WIRE_MAX_SETTING}', true), ''), '1')::int AS wire_max "
            f"FROM {self._schema}.jobs WHERE run_id = $1",
            uuid.UUID(run_id),
        )
        if row is None:
            return "not_found"
        if row["status"] != JOB_STATUS_RUNNING:
            return "not_running"
        if int(row["fencing_token"]) != int(fencing_token):
            return "fencing_mismatch"
        if int(row["wire_version"]) > int(row["wire_max"]):
            # 0005 tetikleyicisi güncellemeyi atladı: oturum bu sürümü bildirmiyor.
            return "wire_isolated"
        return "cancel_requested"

    async def _write_outbox_with_sequence(
        self, conn: asyncpg.Connection, run_id: str, envelope: AgentEnvelope
    ) -> None:
        """Terminal olayı sıra tahsisiyle outbox'a yazar (B5 atomik sıra deseni)."""

        sequence = await self._allocate_event_sequence(conn, run_id)
        payload = dict(envelope.payload)
        payload["event_sequence"] = sequence
        stamped = envelope.model_copy(update={"payload": payload})
        exchange, routing_key = outbox_route(stamped)
        await conn.execute(
            f"INSERT INTO {self._schema}.outbox_events "
            "(outbox_id, message_id, message_type, exchange, routing_key, envelope, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)",
            uuid.uuid4(),
            uuid.UUID(stamped.message_id),
            stamped.message_type,
            exchange,
            routing_key,
            stamped.model_dump_json(exclude_none=True),
            datetime.now(timezone.utc),
        )

    async def _allocate_event_sequence(self, conn: asyncpg.Connection, run_id: str) -> int:
        """Run başına atomik monoton sequence (migration 0002 tablosu)."""

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

    async def requeue_job(
        self,
        run_id: str,
        fencing_token: int,
        *,
        queue_class: str | None = None,
        reset_attempt: bool = False,
    ) -> bool:
        """İşi guard'la bekleyen durumuna döndürür (terminal DEĞİL).

        Kullanımlar: ``needs_input`` terminali (iş beklemeye döner, checkpoint
        korunur — resume talebi yeniden claim eder) ve derin araştırma
        ertelemesi (``queue_class='research'`` — plan B6 ayrı kapasite).
        ``reset_attempt`` erteleme içindir: rota sonrası yürütme BAŞLAMADIYSA
        deneme sayacı recovery sınırını tüketmemeli; fencing_token monoton
        kaldığı için güvenlidir.
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE {self._schema}.jobs SET "
                f"status = {JOB_STATUS_ACCEPTED!r}, lease_owner = NULL, lease_until = NULL, "
                "queue_class = COALESCE($3::text, queue_class), "
                f"execution_attempt = {'0' if reset_attempt else 'execution_attempt'} "
                "WHERE run_id = $1 AND status = $2 AND fencing_token = $4 "
                "RETURNING job_id",
                uuid.UUID(run_id),
                JOB_STATUS_RUNNING,
                queue_class,
                int(fencing_token),
            )
        return row is not None

    async def release_job_lease(self, run_id: str, fencing_token: int) -> bool:
        """Yürütme bırakılırken lease'i hemen kurtarılabilir kılar (terminal yazmaz).

        ``lease_until = now()``: iş running kalır ama claim'in recovery koşulu
        anında eşleşir; transient hatada lease süresi kadar bekleme olmaz.
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE {self._schema}.jobs SET "
                "lease_owner = NULL, lease_until = now() "
                "WHERE run_id = $1 AND status = $3 AND fencing_token = $2 "
                "RETURNING job_id",
                uuid.UUID(run_id),
                int(fencing_token),
                JOB_STATUS_RUNNING,
            )
        return row is not None

    async def claim_job_for_continuation(
        self,
        run_id: str,
        worker_id: str,
        *,
        lease_seconds: float,
    ) -> ClaimedJob | None:
        """Park edilmiş TEK bir işi graph devamı için claim eder (W6 F3).

        Kontrol tüketici sürücüsünün (``control_driver``) hedefli claim'idir:
        ``needs_input`` sonrası bekleyen ('accepted') iş, ``agent.resume.requested``
        / ``agent.action.result`` tesliminin graph devamı için bu worker'a
        geçirilir. ``claim_next_job`` ile AYNI claim sözleşmesi: running geçişi,
        yeni fencing_token, deneme sayacı artışı, lease yazımı.

        Guard'lar: yalnız ``status='accepted'`` (running iş başka sahibin
        aynen kalsın — ``None`` döner, sürücü teslimi ACK'sız bırakır);
        süresi geçmiş iş claim edilmez (terminal B7 reaper'ın); aktif iptal
        niyeti olan iş claim edilmez (B7 kuralının sürücü karşılığı).
        Terminal iş de ``None`` döner: sürücü bunu "zaten sonuçlanmış" olarak
        okuyup idempotent ACK verir (``control_driver._continue``).
        """

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    f"SELECT job_id FROM {self._schema}.jobs "
                    "WHERE run_id = $1 FOR UPDATE",
                    uuid.UUID(run_id),
                )
                if locked is None:
                    return None
                row = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET "
                    f"status = {JOB_STATUS_RUNNING!r}, "
                    "lease_owner = $2, "
                    "lease_until = now() + make_interval(secs => $3), "
                    "execution_attempt = execution_attempt + 1, "
                    f"fencing_token = nextval('{self._schema}.job_fencing_seq'), "
                    "started_at = COALESCE(started_at, now()) "
                    "WHERE run_id = $1 AND status = $4 "
                    "  AND (deadline_at IS NULL OR deadline_at > now()) "
                    "  AND NOT EXISTS ("
                    f"    SELECT 1 FROM {self._schema}.cancel_intents x WHERE x.run_id = $1) "
                    "RETURNING job_id, run_id, conversation_id, origin_message_id, "
                    "payload, envelope, queue_class, deadline_at, execution_attempt, "
                    "fencing_token, accepted_at, started_at, wire_version",
                    uuid.UUID(run_id),
                    worker_id,
                    float(lease_seconds),
                    JOB_STATUS_ACCEPTED,
                )
        if row is None:
            return None
        return ClaimedJob(
            job_id=row["job_id"],
            run_id=str(row["run_id"]),
            conversation_id=str(row["conversation_id"]),
            origin_message_id=str(row["origin_message_id"]),
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            envelope=_decode_envelope_json(row["envelope"]),
            queue_class=row["queue_class"],
            deadline_at=row["deadline_at"],
            execution_attempt=int(row["execution_attempt"]),
            fencing_token=int(row["fencing_token"]),
            accepted_at=row["accepted_at"],
            started_at=row["started_at"],
            recovered=False,
            wire_version=normalize_wire_version(row["wire_version"]),
        )

    async def fail_expired_jobs_beyond_attempts(
        self,
        max_execution_attempts: int,
        *,
        error_code: str = "provider_error",
        error_message: str = "yürütme denemesi sınırı aşıldı; iş recovery ile kapatıldı",
    ) -> list[str]:
        """Lease'i bitmiş, deneme sınırını aşmış işleri kalıcı olarak kapatır.

        SINIRLI recovery'nin diğer yüzü: sınırı aşan iş sonsuz re-claim
        döngüsüne girmez. Guard: ``status='running'`` VE ``lease_until`` bitmiş
        VE ``execution_attempt >= max`` VE aktif iptal niyeti YOK (iptal niyeti
        varsa terminal 'cancelled' geçişini B7'nin koşullu UPDATE'i üretir).
        Terminal başarısızlık olayı iş durumuyla AYNI transaction'da outbox'a
        yazılır (plan B5 kuralı) ve run'ın wire sürümüyle kurulur (K4).
        """

        closed: list[str] = []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT run_id, conversation_id, envelope, origin_message_id, "
                f"execution_attempt, wire_version FROM {self._schema}.jobs c "
                "WHERE status = $1 AND lease_until IS NOT NULL AND lease_until < now() "
                "AND execution_attempt >= $2 "
                "AND NOT EXISTS ("
                f"  SELECT 1 FROM {self._schema}.cancel_intents x WHERE x.run_id = c.run_id)",
                JOB_STATUS_RUNNING,
                int(max_execution_attempts),
            )
            for row in rows:
                run_id = str(row["run_id"])
                attempt = int(row["execution_attempt"])
                # Kimlik alanları kabul zarfından okunur (jobs tablosunda
                # correlation_id kolonu yoktur; zarf tek kaynaktır).
                stored = _decode_envelope_json(row["envelope"])
                async with conn.transaction():
                    updated = await conn.fetchrow(
                        f"UPDATE {self._schema}.jobs SET "
                        "status = $3, result_json = $4::jsonb, "
                        "lease_owner = NULL, lease_until = NULL "
                        "WHERE run_id = $1 AND status = $2 "
                        "AND execution_attempt >= $5 "
                        "AND lease_until IS NOT NULL AND lease_until < now() "
                        "AND NOT EXISTS ("
                        f"  SELECT 1 FROM {self._schema}.cancel_intents c WHERE c.run_id = $1) "
                        "RETURNING job_id",
                        row["run_id"],
                        JOB_STATUS_RUNNING,
                        "failed",
                        json.dumps(
                            {
                                "outcome": "failed",
                                "error_code": error_code,
                                "error_message": error_message,
                                "execution_attempt": attempt,
                            },
                            ensure_ascii=False,
                        ),
                        int(max_execution_attempts),
                    )
                    if updated is None:
                        continue  # eşzamanlı reaper/worker kazandı (ya da sürüm izolasyonu)
                    envelope = compose_run_envelope(
                        schema_version=normalize_wire_version(row["wire_version"]),
                        message_type="agent.run.failed",
                        run_id=run_id,
                        conversation_id=str(row["conversation_id"]),
                        correlation_id=stored.correlation_id,
                        causation_id=str(row["origin_message_id"]),
                        occurred_at=format_utc(datetime.now(timezone.utc)),
                        payload={
                            "event_sequence": 0,
                            "execution_attempt": attempt,
                            "error_code": error_code,
                            "error_message": error_message,
                        },
                    )
                    await self._write_outbox_with_sequence(conn, run_id, envelope)
                closed.append(run_id)
        if closed:
            logger.warning(
                "deneme sınırını aşan %d iş kalıcı başarısızla kapatıldı: %s",
                len(closed),
                closed,
            )
        return closed

    async def has_cancel_intent(self, run_id: str) -> bool:
        """Aktif iptal niyeti var mı? (worker'ın güvenli sınır kontrolü okuması.)"""

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT run_id FROM {self._schema}.cancel_intents WHERE run_id = $1",
                uuid.UUID(run_id),
            )
        return row is not None

    async def fetch_job_full(self, run_id: str) -> asyncpg.Record | None:
        """İş satırının tamamı (lease/attempt/fencing/result dahil) — gözlem ve test."""

        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT job_id, run_id, conversation_id, origin_message_id, payload_hash, "
                "status, queue_class, lease_owner, lease_until, execution_attempt, "
                "fencing_token, result_json, deadline_at, accepted_at, started_at, wire_version "
                f"FROM {self._schema}.jobs WHERE run_id = $1",
                uuid.UUID(run_id),
            )

    async def count_cancel_intents(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(f"SELECT count(*) FROM {self._schema}.cancel_intents")

    async def next_fencing_token(self) -> int:
        """Dizinin güncel değerini okumadan BİR SONRAKİ token'ı tahsis eder (test/gözlem)."""

        async with self._pool.acquire() as conn:
            return int(
                await conn.fetchval(f"SELECT nextval('{self._schema}.job_fencing_seq')")
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
