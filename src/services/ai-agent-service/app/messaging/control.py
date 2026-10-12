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
- Resume / ActionResult: B9'un graph devam ettirme bağlantısı BURADA
  BAŞLATILMAZ; B7'nin sorumluluğu kimlik/tür doğrulaması, idempotent kayıt ve
  bilinmeyen run'ın sessiz döngüye girmeden DLQ'ya düşürülmesidir. Bilinen
  run'da teslim ACK edilir (komut iş verisiyle kalıcı job üstünde değerlenir;
  bu fazda aksiyon üretilmez — sınır faz raporunda).

ACK, depo commit'inden SONRA normal dönüşle verilir (B2 consumer tabanı);
commit öncesi istisna teslimi ACK'sız bırakır ve DLX'e gider.

Kaynaklar: [RMQ-CONFIRMS#C2] ACK işleme tamamlandıktan sonra; [PY-ASYNCIO#C2]
iptal isteği kesin garanti değildir — terminal kararının kalıcı depoda
atomikleşmesinin nedeni budur.
"""

from __future__ import annotations

import logging
from typing import Any

from aio_pika.abc import AbstractIncomingMessage

from .contracts import Direction, ParsedEnvelope, parse_envelope
from .contracts.errors import AgentContractError
from .control_store import ControlStore
from .retry import PermanentContractError

__all__ = [
    "ControlConsumerService",
    "ControlPolicyError",
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


class ControlConsumerService:
    """``agent.control.q`` teslimlerini kalıcı kontrol kaydına çeviren servis."""

    def __init__(
        self,
        store: ControlStore,
        *,
        consumer_name: str = "control",
    ) -> None:
        self._store = store
        self._consumer_name = consumer_name

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
        """Resume / ActionResult: B9 bağlantı noktasına kadar kalıcı olarak ACK'lanır.

        - İş kaydı YOK: komut değerlendirilemez; sessiz döngü kurulmaz — kalıcı
          ihlal sayılıp DLQ'ya düşer (operatör görür).
        - İş kaydı VAR: B7 kaydı ACK'lar; graph devamı B9'un resume sözleşmesiyle
          bağlanır (bu fazda yürütme tetiklenmez).
        """

        envelope = parsed.envelope
        assert envelope.run_id is not None
        state = await self._store.job_state(envelope.run_id)
        if state is None:
            raise ControlPolicyError(
                f"run {envelope.run_id} için iş kaydı yok; {envelope.message_type} değerlendirilemez"
            )
        logger.info(
            "kontrol komutu kalıcı kayda alındı (B9 bağlantısı bekliyor): type=%s run_id=%s message_id=%s",
            envelope.message_type,
            envelope.run_id,
            envelope.message_id,
        )
        return {"outcome": "recorded", "message_type": envelope.message_type}

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
) -> Any:
    """Kontrol kuyruğu consumer'ını retry sarmalayıcısıyla kurar (gecikici import yok).

    ``retry_publisher``: retry exchange'leri üzerinde yetkili confirm'lu
    ``BrokerPublisher`` (exchanges=tuple(blog.agent.retry.{tier}s)).
    """

    from .retry import RetryAwareBrokerConsumer, TransportRetryService
    from .topology import CONTROL_QUEUE

    service = ControlConsumerService(store)
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
