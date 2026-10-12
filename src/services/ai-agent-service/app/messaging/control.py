"""Kontrol tüketici servisi (B7, plan satır 427-434): ``agent.control.q``.

Üç kontrol komutunun (B1 registry: agent.cancel.requested / agent.resume.requested
/ agent.action.result) ayrı tüketicisi:

- Zarf B1 ``parse_envelope`` ile doğrulanır; ihlal kalıcıdır → DLQ (tekrar
  çalıştırma yok).
- Tür politikası: kuyruğa yalnız üç kontrol komutu kabul edilir; producer/tür
  uyuşmazlığı ``ControlPolicyError`` (kalıcı → DLQ).
- Idempotency: ``agent.inbox_messages`` consumer_name="control" ile kayıt;
  tekrar teslim yeniden işlenmeden ACK ile karşılanır.
- Cancel: ``ControlStore.record_cancel_intent`` — niyet + (queued iş için)
  terminal olay TEK transaction'da; niyet kaydı terminal DEĞİLDİR.
- Resume / ActionResult (B9 ADDITIVE): ``resume_driver`` bağlandığında komut
  artık yalnız kaydedilmez — B6/A8 resume girişi üzerinden graph DEVAM
  ETTİRİLİR. Driver önce çağrılır (en az bir kez anlambilimi), inbox kaydı
  BAŞARI SONRASI yazılır: driver hatası teslimi ACK'sız bırakır ve graph
  devamı kaybolmaz. Driver idempotent olmak zorundadır: çökme/reddetme
  sonrası tekrar teslimde A9 çalışma makinesi sonuçlanmış durumu
  ``validation_error`` ile reddeder (çift graph etkisi üretmez, DLQ'da
  görünür). Driver YOKKEN B7 davranışı aynen korunur (kayıt + ACK).
- Bilinmeyen run her iki yolda da ``ControlPolicyError`` ile DLQ'ya düşer
  (sessiz döngü kurulmaz).

ACK, depo commit'inden SONRA normal dönüşle verilir (B2 consumer tabanı);
commit öncesi istisna teslimi ACK'sız bırakır ve DLX'e gider.

Kaynaklar: [RMQ-CONFIRMS#C2] ACK işleme tamamlandıktan sonra; [PY-ASYNCIO#C2]
iptal isteği kesin garanti değildir — terminal kararının kalıcı depoda
atomikleşmesinin nedeni budur; [LG-INTERRUPTS#C1] resume girdisi Command ile
aynı yürütmeye taşınır (driver'ın graph devamı sözleşmesi).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol, runtime_checkable

from aio_pika.abc import AbstractIncomingMessage

from .contracts import Direction, ParsedEnvelope, parse_envelope
from .contracts.errors import AgentContractError
from .control_store import ControlStore
from .retry import PermanentContractError

__all__ = [
    "ControlConsumerService",
    "ControlPolicyError",
    "ControlResumeDriver",
    "CONTROL_MESSAGE_TYPES",
    "CANCEL_COMMAND_TYPE",
    "RESUME_COMMAND_TYPE",
    "ACTION_RESULT_COMMAND_TYPE",
    "build_control_consumer",
]

logger = logging.getLogger(__name__)

CANCEL_COMMAND_TYPE = "agent.cancel.requested"
RESUME_COMMAND_TYPE = "agent.resume.requested"
ACTION_RESULT_COMMAND_TYPE = "agent.action.result"

#: Kontrol kuyruğunun kabul ettiği kapalı tür kümesi (topology binding ile aynı).
CONTROL_MESSAGE_TYPES: tuple[str, ...] = (
    CANCEL_COMMAND_TYPE,
    RESUME_COMMAND_TYPE,
    ACTION_RESULT_COMMAND_TYPE,
)


class ControlPolicyError(PermanentContractError):
    """Kontrol kuyruğuna tür/üretici/run politikasına aykırı mesaj geldi (kalıcı → DLQ)."""


@runtime_checkable
class ControlResumeDriver(Protocol):
    """B9 graph devam ettirme sözcüsü (ADDITIVE).

    Kontrol tüketicisi resume/action_result komutunu KENDİ yürütmez; B6/A8
    resume girişini (``agent_core.entrypoints.resume`` + A9 çalışma makinesi)
    kompoze eden bileşene delege eder. Driver idempotent olmak zorundadır:
    teslim en az bir kez iletilebilir (driver hatası ACK'yı engeller, tekrar
    teslimde yeniden çağrılır). Dönüş değeri gözlemlenebilirlik içindir
    (ör. ``{"outcome": "continued", "stage": "resolved"}``).
    """

    async def resume_requested(self, *, run_id: str, payload: Any) -> dict[str, Any]:
        """``agent.resume.requested`` teslimi: çalışmayı checkpoint'ten sürdürür."""
        ...

    async def action_result(self, *, run_id: str, payload: Any) -> dict[str, Any]:
        """``agent.action.result`` teslimi: doğrulanmış backend sonucuyla çalışmayı sürdürür."""
        ...


class ControlConsumerService:
    """``agent.control.q`` teslimlerini kalıcı kontrol kaydına çeviren servis."""

    def __init__(
        self,
        store: ControlStore,
        *,
        consumer_name: str = "control",
        resume_driver: ControlResumeDriver | None = None,
    ) -> None:
        self._store = store
        self._consumer_name = consumer_name
        self._resume_driver = resume_driver

    async def handle_delivery(self, raw: bytes, message: AbstractIncomingMessage) -> dict[str, Any]:
        """Tek teslimi işler; normal dönüş = commit yapıldı, ACK alınabilir."""

        try:
            parsed = parse_envelope(raw)
        except AgentContractError as exc:
            logger.warning(
                "control sözleşme reddi: kategori=%s alan=%s message_id=%s",
                exc.category.value,
                exc.field,
                getattr(message, "message_id", None),
            )
            raise

        self._check_policy(parsed)

        # B9: resume/action_result + bağlı driver → graph devamı ÖNCE yürütülür
        # (at-least-once); inbox kaydı başarıdan sonra yazılır. Diğer tüm yollar
        # B7 davranışını aynen korur (inbox-first).
        if (
            parsed.envelope.message_type != CANCEL_COMMAND_TYPE
            and self._resume_driver is not None
        ):
            return await self._handle_continuation(parsed)

        seen = await self._store.record_inbox_seen(
            consumer_name=self._consumer_name, envelope=parsed.envelope
        )
        if not seen:
            return {"outcome": "duplicate", "message_type": parsed.envelope.message_type}

        run_id = parsed.envelope.run_id
        if run_id is None:
            raise ControlPolicyError("kontrol komutu run_id taşımak zorundadır")

        if parsed.envelope.message_type == CANCEL_COMMAND_TYPE:
            return await self._handle_cancel(parsed)
        return await self._handle_deferred(parsed)

    async def _handle_cancel(self, parsed: ParsedEnvelope) -> dict[str, Any]:
        envelope = parsed.envelope
        assert envelope.run_id is not None
        reason = parsed.spec.payload_model.model_validate(envelope.payload).reason  # type: ignore[attr-defined]

        result = await self._store.record_cancel_intent(
            envelope.run_id,
            requested_by=envelope.producer.value,
            conversation_id=envelope.conversation_id or envelope.run_id,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.message_id,
            reason=reason,
        )
        logger.info(
            "cancel intent kaydedildi: run_id=%s sonuc=%s message_id=%s",
            envelope.run_id,
            result.outcome,
            envelope.message_id,
        )
        return {"outcome": result.outcome, "message_type": envelope.message_type}

    async def _handle_deferred(self, parsed: ParsedEnvelope) -> dict[str, Any]:
        """Resume / ActionResult: driver bağlı değilken B7 davranışı — kayıt + ACK.

        - İş kaydı YOK: komut değerlendirilemez; sessiz döngü kurulmaz — kalıcı
          ihlal sayılıp DLQ'ya düşer (operatör görür).
        - İş kaydı VAR: B7 kaydı ACK'lar; graph devamı bağlı driver'la
          (``_handle_continuation``) yürütülür.
        """

        envelope = parsed.envelope
        assert envelope.run_id is not None
        state = await self._store.job_state(envelope.run_id)
        if state is None:
            raise ControlPolicyError(
                f"run {envelope.run_id} için iş kaydı yok; {envelope.message_type} değerlendirilemez"
            )
        logger.info(
            "kontrol komutu kalıcı kayda alındı (driver bağlı değil): type=%s run_id=%s message_id=%s",
            envelope.message_type,
            envelope.run_id,
            envelope.message_id,
        )
        return {"outcome": "recorded", "message_type": envelope.message_type}

    async def _handle_continuation(self, parsed: ParsedEnvelope) -> dict[str, Any]:
        """B9 (ADDITIVE): resume/action_result komutunu graph devamına bağlar.

        Sıra bilinçlidir: (1) tamamlanmış devamın hızlı yolu — inbox okuması
        (sıralı tekrar teslim/ağ tekrarı ikinci driver çağrısını engeller);
        (2) driver; (3) inbox kaydı. Driver hatasında inbox YAZILMAZ ve teslim
        ACK'sız kalır (transport retry yeniden çağırır → en az bir kez devam;
        plan kuralı: ACK kalıcı sorumluluk devrinden sonra verilir). Çift
        graph etkisinden A9 çalışma makinesi korur: sonuçlanmış çalışmaya
        ikinci müdahale ``validation_error`` ile reddedilir (retry sınıflandır
        masında graph-hatası → ACK; yarıştaki ikiz teslim sessizce ACK'lanır).
        """

        envelope = parsed.envelope
        assert envelope.run_id is not None
        assert self._resume_driver is not None

        if await self._continuation_already_done(envelope):
            logger.info(
                "kontrol komutu zaten devam ettirilmiş: type=%s run_id=%s message_id=%s",
                envelope.message_type,
                envelope.run_id,
                envelope.message_id,
            )
            return {"outcome": "duplicate", "message_type": envelope.message_type}

        state = await self._store.job_state(envelope.run_id)
        if state is None:
            raise ControlPolicyError(
                f"run {envelope.run_id} için iş kaydı yok; {envelope.message_type} değerlendirilemez"
            )

        payload = parsed.spec.payload_model.model_validate(envelope.payload)
        if parsed.envelope.message_type == RESUME_COMMAND_TYPE:
            driver_outcome = await self._resume_driver.resume_requested(
                run_id=envelope.run_id, payload=payload
            )
        else:
            driver_outcome = await self._resume_driver.action_result(
                run_id=envelope.run_id, payload=payload
            )

        # İş kaydı başarıdan sonra: yarıştaki ikiz teslim "duplicate" ile ACK'lanır.
        await self._store.record_inbox_seen(
            consumer_name=self._consumer_name, envelope=envelope
        )
        logger.info(
            "kontrol komutu graph devamına bağlandı: type=%s run_id=%s message_id=%s driver=%s",
            envelope.message_type,
            envelope.run_id,
            envelope.message_id,
            driver_outcome,
        )
        return {
            "outcome": "continued",
            "message_type": envelope.message_type,
            "driver_outcome": driver_outcome,
        }

    async def _continuation_already_done(self, envelope: Any) -> bool:
        """Tamamlanmış devamın inbox izi (salt okuma; B7 insert'inin ön okuması).

        ``ControlStore``'un özel alanlarına erişim worker.py'deki aynı paket-içi
        geleneğiyledir (``_publish_outbox_only``); kayıt yazımı yine de yalnız
        ``record_inbox_seen`` üzerinden yapılır.
        """

        # noqa: SLF001 - aynı paket içi
        pool = self._store._pool
        schema = getattr(self._store, "_schema", "agent")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT 1 FROM {schema}.inbox_messages "
                "WHERE consumer_name = $1 AND message_id = $2",
                self._consumer_name,
                uuid.UUID(envelope.message_id),
            )
        return row is not None

    def _check_policy(self, parsed: ParsedEnvelope) -> None:
        spec = parsed.spec
        if spec.message_type not in CONTROL_MESSAGE_TYPES:
            raise ControlPolicyError(
                f"control kuyruğu yalnız {'/'.join(CONTROL_MESSAGE_TYPES)} kabul eder; gelen: {spec.message_type}"
            )
        if spec.direction is not Direction.BACKEND_TO_AGENT:
            raise ControlPolicyError(
                f"{spec.message_type} backend→agent yönünde değil: {spec.direction.value}"
            )


def build_control_consumer(
    connection: Any,
    store: ControlStore,
    retry_publisher: Any,
    settings: Any,
    *,
    tiers: tuple[int, ...],
    consumer_tag: str = "control-b7",
    resume_driver: ControlResumeDriver | None = None,
) -> Any:
    """Kontrol kuyruğu consumer'ını retry sarmalayıcısıyla kurar (gecikici import yok).

    ``retry_publisher``: retry exchange'leri üzerinde yetkili confirm'lu
    ``BrokerPublisher`` (exchanges=tuple(blog.agent.retry.{tier}s)).
    ``resume_driver`` (B9 ADDITIVE): bağlıysa resume/action_result komutları
    graph devamına bağlanır; yoksa B7 davranışı korunur.
    """

    from .retry import RetryAwareBrokerConsumer, TransportRetryService
    from .topology import CONTROL_QUEUE

    service = ControlConsumerService(store, resume_driver=resume_driver)
    retrying = TransportRetryService(
        service.handle_delivery,
        retry_publisher,
        queue_name=CONTROL_QUEUE,
        tiers=tiers,
    )
    return RetryAwareBrokerConsumer(
        connection,
        CONTROL_QUEUE,
        retrying.handle_delivery,
        settings,
        consumer_tag=consumer_tag,
    )
