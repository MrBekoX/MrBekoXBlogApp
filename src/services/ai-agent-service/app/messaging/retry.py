"""Transport retry ve DLQ politikası (B7, plan satır 412-423).

Üç hata sınıfının AYRIMI (plan: "Transport hatası, kalıcı sözleşme hatası ve
graph yürütme hatasını ayır"):

- ``TransportError``: geçici altyapı hatası (DB kopması, broker yayın hatası,
  zaman aşımı). Kademeli gecikmeli retry kuyruklarıyla tekrar denenir.
- ``AgentContractError`` / ``ControlPolicyError`` / ``JobPayloadConflict``:
  KALICI sözleşme/politika hatası. Tekrar çalıştırma ANLAMSIZDIR: mesaj
  doğrudan DLX'e düşer (sürekli nack/requeue döngüsü yok, şema hatalı mesaj
  tekrar çalıştırılmaz — plan maddeleri).
- ``GraphExecutionError``: graph yürütmesi başarısız. Broker retry BUNA
  DOKUNMAZ: iş kalıcı job kaydı üstünde retry/recovery politikasına (B6
  worker) aittir; teslim yine de ACK edilir ("ACK verilmiş bir işin
  çalıştırma hatası broker requeue ile değil, kalıcı job retry/recovery
  politikasıyla ele alınır" — plan B6).

Retry mekanizması: hedefe özel TTL'li kuyruklar (B2 topology'de hazır:
``agent.<q>.retry.<tier>s.q``, TTL dolunca mesaj orijinal exchange'e korunan
routing key ile döner). Kademeler: 10 sn / 30 sn / 2 dk (B7 başlangıç önerisi);
son denemede DLQ.

Kritik güvenilirlik kuralı (plan satır 416): retry mesajı yeni hedefe
yayınlarken CONFIRM gelmeden eski teslim ACK EDİLMEZ; aynı mantıksal
message_id korunur. Confirm gelmezse teslim ACK'sız bırakılır (broker tekrar
teslim eder) ve mesaj kaybolmaz.

Kaynaklar: [RMQ-DLX#C1] DLX reddetme/TTL/kuyruk sınırı durumlarında yönlendirme
yapar; [RMQ-DLX#C2] varsayılan dead-letter aktarımı kayıpsız teslim garantisi
VERMEZ (quorum at-least-once seçeneği ayrıca doğrulanmalı) — bu yüzden B7
confirm'lu yeniden yayın + confirm-öncesi-ACK-yok kuralını kullanır;
[RMQ-RELIABILITY#C2] persistent mesaj; [PY-ASYNCIO#C1] yapılandırılmış
eşzamanlılık.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from aio_pika.abc import AbstractIncomingMessage

from .contracts import ParsedEnvelope, parse_envelope
from .contracts.errors import AgentContractError
from .consumer import BrokerConsumer as _BrokerConsumerBase
from .job_store import JobPayloadConflict
from .publisher import BrokerPublisher, PublishResult
from .topology import DEAD_EXCHANGE

__all__ = [
    "TransportError",
    "GraphExecutionError",
    "PermanentContractError",
    "RetryAction",
    "RetryDecision",
    "TransportRetryService",
    "RetryAwareBrokerConsumer",
    "RetryTierPolicy",
    "DEFAULT_RETRY_TIERS",
    "DlqReplayService",
    "ReplayDecision",
    "ReplayGuard",
    "classify_exception",
    "next_retry_tier",
]

logger = logging.getLogger(__name__)

#: B7 başlangıç kademeleri (saniye) — plan satır 414 önerisi; testler kısa
#: kademelerle parametrik koşar (topology build_topology(retry_tier_seconds=...)).
DEFAULT_RETRY_TIERS: tuple[int, ...] = (10, 30, 120)


class TransportError(Exception):
    """Geçici altyapı hatası: kademeli retry kuyruğuna gönderilir."""


class GraphExecutionError(Exception):
    """Graph yürütme hatası: broker retry'sız; kalıcı job politikası (B6) ele alır."""


class PermanentContractError(Exception):
    """Kalıcı sözleşme/politika ihlali: doğrudan DLQ'ya; tekrar çalıştırılmaz."""


# Kalıcı ihlal sayılan istisnalar: bunlar retry'DAN GEÇMEZ.
PERMANENT_ERRORS: tuple[type[BaseException], ...] = (
    AgentContractError,
    PermanentContractError,
    JobPayloadConflict,
)


def classify_exception(exc: BaseException) -> str:
    """İstisnayı üç sınıftan birine ayırır: ``transport`` | ``contract`` | ``graph``.

    Kalıcı sözleşme/politika istisnaları önce eşlenir; ``TransportError``
    transport; ``GraphExecutionError`` graph; bilinmeyen istisna GÜVENLI TARAFDA
    transport sayılmaz — bilinmeyen hatalar kalıcı kabul edilir (kör retry
    döngüsü kurulmaz; plan: "Sürekli nack/requeue döngüsü oluşturma"). DB/Broker
    altyapı istisnaları çağıran katman tarafından ``TransportError`` ile
    sarılır.
    """

    if isinstance(exc, PERMANENT_ERRORS):
        return "contract"
    if isinstance(exc, GraphExecutionError):
        return "graph"
    if isinstance(exc, TransportError):
        return "transport"
    return "contract"  # bilinmeyen hata kör retry üretmesin: DLQ'da görünür olur


@dataclass(frozen=True)
class RetryTierPolicy:
    """Hedefe özel gecikme kademeleri; deneme sayacı zarf delivery_attempt'tir."""

    tiers: tuple[int, ...] = DEFAULT_RETRY_TIERS

    def next_tier(self, failed_attempt: int) -> int | None:
        """Başarısız olan denemenin (0 tabanlı delivery_attempt) sonraki kademesi.

        0. deneme başarısız → tiers[0]; son kademeden sonraki başarısızlık None
        döner (DLQ). Böylece toplam yürütme denemesi len(tiers)+1 ile sınırlıdır:
        sürekli retry döngüsü kurulamaz.
        """

        if failed_attempt < 0:
            raise ValueError("delivery_attempt negatif olamaz")
        if failed_attempt >= len(self.tiers):
            return None
        return self.tiers[failed_attempt]

    @property
    def max_attempts(self) -> int:
        return len(self.tiers) + 1


#: Basit kademe hesabı (RetryTierPolicy().next_tier kısayolu).
def next_retry_tier(failed_attempt: int, tiers: tuple[int, ...] = DEFAULT_RETRY_TIERS) -> int | None:
    return RetryTierPolicy(tiers=tiers).next_tier(failed_attempt)


class RetryAction:
    """Consumer tabanına iletilen teslim kararı."""

    ACK = "ack"
    NACK = "nack"  # requeue=False → DLX/DLQ
    HOLD = "hold"  # ne ACK ne NACK: broker tekrar teslim eder (confirm beklenemedi)


@dataclass(frozen=True)
class RetryDecision:
    """Tek teslimin retry servisi kararı (gözlemlenebilirlik için)."""

    action: str  # RetryAction sabitleri
    outcome: str  # completed | retry_tier | dead_lettered | contract_dead_letter | graph_ack | publish_unconfirmed
    tier_seconds: int | None = None
    detail: str = ""


Handler = Callable[[bytes, AbstractIncomingMessage], Awaitable[Any]]


class TransportRetryService:
    """Teslim kararlarını hata sınıfına göre veren sarmalayıcı.

    ``handler`` işini bitirince ACK; kalıcı sözleşme hatasında NACK(requeue=False)
    → DLQ; ``TransportError``da zarf delivery_attempt+1 ile AYNI message_id'yi
    koruyarak kademeye yayınlar ve CONFIRM gelince eski teslimi ACK'lar.
    """

    def __init__(
        self,
        handler: Handler,
        publisher: BrokerPublisher,
        *,
        queue_name: str,
        tiers: tuple[int, ...] = DEFAULT_RETRY_TIERS,
    ) -> None:
        self._handler = handler
        self._publisher = publisher
        self._queue_name = queue_name
        self._policy = RetryTierPolicy(tiers=tuple(tiers))

    async def handle_delivery(self, raw: bytes, message: AbstractIncomingMessage) -> RetryDecision:
        try:
            await self._handler(raw, message)
            return RetryDecision(action=RetryAction.ACK, outcome="completed")
        except BaseException as exc:  # sınıflandırma bilinçli olarak geniştir
            classification = classify_exception(exc)
            if classification == "contract":
                logger.warning(
                    "kalıcı sözleşme ihlali → DLQ: kuyruk=%s message_id=%s hata=%s",
                    self._queue_name,
                    getattr(message, "message_id", None),
                    exc,
                )
                return RetryDecision(
                    action=RetryAction.NACK,
                    outcome="contract_dead_letter",
                    detail=str(exc),
                )
            if classification == "graph":
                # Graph yürütme hatası broker'da tekrarlanmaz; kalıcı job
                # politikası (B6) sonucu üretir. Teslim ACK'lanır.
                logger.warning(
                    "graph yürütme hatası → ACK (kalıcı job politikası): kuyruk=%s message_id=%s",
                    self._queue_name,
                    getattr(message, "message_id", None),
                )
                return RetryDecision(action=RetryAction.ACK, outcome="graph_ack", detail=str(exc))

            tier = await self._republish_to_tier(raw, message)
            if tier is None:
                return RetryDecision(
                    action=RetryAction.NACK,
                    outcome="dead_lettered",
                    detail=f"retry kademeleri tükendi: {exc}",
                )
            return tier

    async def _republish_to_tier(self, raw: bytes, message: AbstractIncomingMessage) -> RetryDecision:
        """Kademeye confirm'lu yeniden yayın; confirm gelmeden ACK verilmez."""

        try:
            parsed = parse_envelope(raw)
        except AgentContractError as exc:
            # Retry sırasında çözülemeyen gövde kalıcı ihlaldür: DLQ.
            return RetryDecision(
                action=RetryAction.NACK, outcome="contract_dead_letter", detail=f"retry öncesi zarf çözümlemedi: {exc}"
            )

        failed_attempt = parsed.envelope.delivery_attempt
        tier = self._policy.next_tier(failed_attempt)
        if tier is None:
            return RetryDecision(action=RetryAction.NACK, outcome="dead_lettered")

        retry_body = _with_delivery_attempt(parsed, failed_attempt + 1)
        exchange = f"blog.agent.retry.{tier}s"
        # Yedek routing key zarfın kendi sürümünün kaydından (K4: .v1/.v2).
        routing_key = message.routing_key or parsed.spec.routing_key
        result: PublishResult = await self._publisher.publish_raw(
            exchange,
            routing_key,
            retry_body,
            message_id=parsed.envelope.message_id,  # AYNI mantıksal kimlik korunur
            correlation_id=parsed.envelope.correlation_id,
            type_name=parsed.envelope.message_type,
        )
        if not result.confirmed:
            # Yeni hedefe confirm gelmedi: eski teslim ACK EDİLMEZ (plan satır 416);
            # ACK'sız teslim broker tarafından tekrar verilir, mesaj kaybolmaz.
            logger.error(
                "retry yayını confirm alamadı; teslim ACK'lanmadı: kuyruk=%s kademe=%ss message_id=%s detail=%s",
                self._queue_name,
                tier,
                parsed.envelope.message_id,
                result.detail,
            )
            return RetryDecision(
                action=RetryAction.HOLD,
                outcome="publish_unconfirmed",
                tier_seconds=tier,
                detail=result.detail,
            )
        logger.info(
            "transport hatası kademeye yayınlandı: kuyruk=%s kademe=%ss attempt=%s→%s message_id=%s",
            self._queue_name,
            tier,
            failed_attempt,
            failed_attempt + 1,
            parsed.envelope.message_id,
        )
        return RetryDecision(action=RetryAction.ACK, outcome="retry_tier", tier_seconds=tier)


def _with_delivery_attempt(parsed: ParsedEnvelope, attempt: int) -> bytes:
    """Gövdeyi yalnız delivery_attempt güncellenmiş olarak yeniden serileştirir.

    message_id dahil diğer tüm zarf alanları korunur (.NET ``WithDeliveryAttempt``
    kuralının Python karşılığı; plan satır 301).
    """

    updated = parsed.envelope.model_copy(update={"delivery_attempt": attempt})
    return updated.model_dump_json(exclude_none=True).encode("utf-8")


class RetryAwareBrokerConsumer(_BrokerConsumerBase):
    """``BrokerConsumer`` alt sınıfı: teslim kararını ACK/NACK/HOLD'a çevirir.

    Temel sınıf normal dönüşte ACK atar; retry kararları üç yolludur — NACK
    (requeue=False → DLX), HOLD (ne ACK ne NACK: confirm alınamayan yeniden
    yayın sonrası broker tekrar teslim eder) ve ACK. HOLD yolu temel sınıfta
    ifade edilemediği için ``_on_message`` ezilir.
    """

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        decision = await self._handler(message.body, message)
        if decision.action == RetryAction.NACK:
            # DLX (ana kuyruğun x-dead-letter-exchange'i); requeue döngüsü yok.
            await message.nack(requeue=False)
            return
        if decision.action == RetryAction.HOLD:
            # Confirm gelmeden ACK verilmez; kanal/bağlantı toparlanınca broker
            # teslimi tekrar eder (retry yayını kaybolmaz).
            return
        await message.ack()


# --------------------------------------------------------------------------- DLQ


class ReplayGuard(Protocol):
    """DLQ replay öncesi kalıcı durum sorgusu (``ControlStore`` uygular)."""

    async def job_state(self, run_id: str) -> dict[str, Any] | None:
        """run_id → {'status': str, 'payload_hash': str, 'deadline_at': datetime} | None."""
        ...  # pragma: no cover

    async def has_cancel_intent(self, run_id: str) -> bool:
        ...  # pragma: no cover


@dataclass(frozen=True)
class ReplayDecision:
    """Tek DLQ mesajının replay kararı."""

    message_id: str
    # replayed | already_terminal | deadline_exceeded | cancel_requested |
    # identity_mismatch | poison | replay_unconfirmed
    outcome: str
    detail: str = ""


class DlqReplayService:
    """DLQ'dan kontrollü replay (plan satır 420-421).

    Her mesaj için yeniden doğrulama sırası:
    1. Zarf sözleşmesi (şema hatalı mesaj replay EDİLMEZ — DLQ'da kalır).
    2. Kimlik/payload: iş kaydı varsa payload_hash eşleşmeli.
    3. Mevcut terminal: iş terminal ise replay edilmez (terminal kazanır).
    4. İptal: cancel intent varsa replay edilmez; iş running ise cancelled'a
       çekilir (``finalize_cancel``).
    5. Deadline: süresi geçmiş iş körlemesine başlatılmaz.
    Kalan mesaj orijinal kuyruğa AYNI message_id ile confirm'lu yayınlanır ve
    DLQ teslimi ancak confirm SONRASI ACK'lanır.
    """

    def __init__(
        self,
        connection: Any,
        guard: ReplayGuard,
        publisher: BrokerPublisher,
        *,
        queue_name: str,
        origin_exchange: str | None = None,
    ) -> None:
        self._connection = connection
        self._guard = guard
        self._publisher = publisher
        self._queue_name = queue_name
        self._origin_exchange = origin_exchange
        self._finalize_cancel: Callable[[str], Awaitable[bool]] | None = None

    def set_cancel_finalizer(self, finalize: Callable[[str], Awaitable[bool]]) -> None:
        """İptalli replay'de çağrılır: ``ControlStore.mark_cancelled_if_running``."""

        self._finalize_cancel = finalize

    async def replay_batch(self, *, limit: int = 10, connection: Any = None) -> list[ReplayDecision]:
        """DLQ'dan en fazla ``limit`` mesajı değerlendirip kararları döndürür.

        ``connection`` verilmezse kurucudaki bağlantı kullanılır; kısa ömürlü
        araç çağrıları kendi bağlantısını geçebilir.
        """

        conn = connection or self._connection
        if conn is None:
            raise RuntimeError("DlqReplayService bağlantısı yok: kurucudan veya çağrıdan verilmeli")
        decisions: list[ReplayDecision] = []
        channel = await conn.channel(publisher_confirms=False)
        try:
            queue = await channel.declare_queue(self._queue_name, durable=True, passive=True)
            for _ in range(limit):
                message = await queue.get(no_ack=False, fail=False)
                if message is None:
                    break
                decisions.append(await self._replay_one(message))
        finally:
            await channel.close()
        return decisions

    async def _replay_one(self, message: Any) -> ReplayDecision:
        message_id = message.message_id if isinstance(message.message_id, str) else ""
        try:
            parsed = parse_envelope(message.body)
        except AgentContractError as exc:
            # Zehirli gövde DLQ'da kalır (ACK/NACK verilmez; kanal kapanışı
            # mesajı yerine koyar) — operatör müdahalesi görünür olur.
            return ReplayDecision(message_id=message_id, outcome="poison", detail=str(exc))

        run_id = parsed.envelope.run_id
        if run_id is None:
            return ReplayDecision(message_id=message_id, outcome="poison", detail="run_id yok")

        state = await self._guard.job_state(run_id)
        if state is not None:
            if state["status"] in ("completed", "failed", "cancelled"):
                # Mevcut terminal yeniden doğrulandı: replay gereksiz, teslim düşürülür.
                await message.ack()
                return ReplayDecision(
                    message_id=message_id, outcome="already_terminal", detail=f"iş {state['status']}"
                )
            from .job_store import compute_payload_hash

            if state.get("payload_hash") and state["payload_hash"] != compute_payload_hash(parsed.envelope.payload):
                # Kimlik doğrulaması: aynı run farklı payload → replay edilmez.
                await message.ack()
                return ReplayDecision(message_id=message_id, outcome="identity_mismatch")

        if await self._guard.has_cancel_intent(run_id):
            if state is not None and state["status"] == "running" and self._finalize_cancel is not None:
                await self._finalize_cancel(run_id)
            await message.ack()
            return ReplayDecision(message_id=message_id, outcome="cancel_requested")

        deadline = state.get("deadline_at") if state is not None else None
        if deadline is not None and _expired(deadline):
            # Süresi geçmiş iş DLQ'dan körlemesine başlatılmaz; mesaj ACK/NACK
            # verilmeden bırakılır: kanal kapanışıyla DLQ'da kalır, operatör
            # görür (DLQ'nun DLX'i yoktur; nack mesajı DÜŞÜRÜRDÜ).
            return ReplayDecision(
                message_id=message_id,
                outcome="deadline_exceeded",
                detail=f"deadline_at={deadline.isoformat()}",
            )

        exchange = self._origin_exchange or _default_origin_exchange(self._queue_name)
        # Yedek routing key zarfın kendi sürümünün kaydından (K4: .v1/.v2).
        routing_key = message.routing_key or parsed.spec.routing_key
        result = await self._publisher.publish_raw(
            exchange,
            routing_key,
            message.body,  # bayt-birebir aynı gövde; message_id zaten zarf içinde korunur
            message_id=parsed.envelope.message_id,
            correlation_id=parsed.envelope.correlation_id,
            type_name=parsed.envelope.message_type,
        )
        if not result.confirmed:
            return ReplayDecision(
                message_id=message_id,
                outcome="replay_unconfirmed",
                detail=f"replay yayını confirm alamadı: {result.detail}",
            )
        await message.ack()  # confirm SONRASI ACK
        return ReplayDecision(message_id=message_id, outcome="replayed", detail=f"{exchange}/{routing_key}")


def _expired(deadline: Any) -> bool:
    from datetime import datetime, timezone

    if isinstance(deadline, datetime):
        value = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
        return value <= datetime.now(timezone.utc)
    return False


def _default_origin_exchange(queue_name: str) -> str:
    """Kuyruğun mesajlarının döndüğü ana exchange (topology kurallarıyla aynı)."""

    from .topology import BACKEND_EVENTS_QUEUE, COMMANDS_EXCHANGE, CONTENT_EXCHANGE, CONTENT_QUEUE

    if queue_name.endswith(".dlq"):
        queue_name = queue_name[: -len(".dlq")]
    if queue_name == BACKEND_EVENTS_QUEUE:
        return DEAD_EXCHANGE  # backend olay kuyruğunun replay'i bu fazda kapsam dışı
    if queue_name == CONTENT_QUEUE:
        return CONTENT_EXCHANGE
    return COMMANDS_EXCHANGE
