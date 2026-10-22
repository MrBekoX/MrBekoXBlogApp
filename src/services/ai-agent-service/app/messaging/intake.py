"""Intake consumer servisi (B4): mesajı doğrular, kalıcı işe dönüştürür, ACK verir.

Kurallar (plan B4):
- Consumer callback'i graph'ı ÇALIŞTIRMAZ: ``graph_executor`` yalnız enjekte
  edilmiş gözlemlenebilir bir kancadır (B6 worker kendi sorumluluğudur); B4
  akışında asla çağrılmaz — "LLM çağrıları intake kapasitesini tüketmez".
- Akış: parse_envelope (B1 sözleşmeleri) → producer/tür politikası →
  JobStore.accept_execution (inbox + job + outbox tek transaction) → normal
  dönüş (B2 ``BrokerConsumer`` ACK eder). Kalıcı sözleşme/politika ihlali ve
  kabul çatışması istisna ile DLX'e yönlendirilir (requeue döngüsü yok);
  geçici DB hatası da aynı temel davranışta DLQ'ya düşer — transport retry
  ayrımı B7'nin kapsamıdır (plan B7: "Transport hatası, kalıcı sözleşme
  hatası ve graph yürütme hatasını ayır").
- ACK, commit'ten SONRA gelir: ``handle_delivery`` ancak ``JobStore`` commit
  döndükten sonra normal döner; commit öncesi istisna teslimi ACK'sız bırakır
  ve broker tekrar teslim eder (yeniden teslimde inbox/job idempotency).
- Sürüm (K4): her execute kuyruğu kendi sürümünü kabul eder (``accepted_versions``;
  ``agent.execute.q`` → v1, ``agent.execute.v2.q`` → v2). Kuyruk/sürüm
  uyuşmazlığı kalıcı politika ihlalidir (DLQ). Kabul edilen sürüm işin
  ``wire_version``'ı olur.

Kaynaklar: [RMQ-CONFIRMS#C2] ACK teslimin geldiği kanaldan ve işleme
tamamlandıktan sonra; [RMQ-CONFIRMS#C1] consumer ACK publisher confirm'den
bağımsız sinyaldir; [AIO-PIKA#C1] robust tüketim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from aio_pika.abc import AbstractIncomingMessage

from .contracts import Direction, ParsedEnvelope, parse_envelope
from .contracts.errors import AgentContractError
from .job_store import JobPayloadConflict, JobStore

__all__ = [
    "IntakeService",
    "IntakeOutcome",
    "IntakePolicyError",
    "EXECUTE_COMMAND_TYPE",
]

logger = logging.getLogger(__name__)

EXECUTE_COMMAND_TYPE = "agent.execute.requested"


class IntakePolicyError(Exception):
    """Execute kuyruğuna tür/üretici politikasına aykırı mesaj geldi (kalıcı ihlal → DLQ)."""


@dataclass(frozen=True)
class IntakeOutcome:
    """Bir teslimin işlenme sonucu (ack yolu)."""

    accepted: bool
    outcome: str  # JobStore kabul sonucu: created | duplicate_inbox | duplicate_job
    run_id: str | None = None
    job_id: str | None = None
    detail: str = ""


class IntakeService:
    """``agent.execute.q`` teslimlerini kalıcı işe çeviren servis.

    ``graph_executor``: B6 worker bağlantı noktası. B4'te YALNIZ testlerde
    çağrılmadığının kanıtı için enjekte edilir; kabul akışı onu çağırmaz.

    ``failure_injection``: YALNIZ test amaçlı çökme penceresi simülasyonu;
    JobStore kabul transaction'ına "pre_commit"/"post_commit" fazlarını
    iletir (GATE senaryoları: commit öncesi/sonrası crash). Üretimde None.
    """

    def __init__(
        self,
        store: JobStore,
        *,
        consumer_name: str = "intake",
        graph_executor: Callable[[ParsedEnvelope], Any] | None = None,
        failure_injection: Callable[[str], None] | None = None,
        accepted_versions: tuple[int, ...] | None = None,
    ) -> None:
        self._store = store
        self._consumer_name = consumer_name
        # None: kuyruk/sürüm denetimi yok (geriye dönük kurulum; tüm desteklenen sürümler).
        self._accepted_versions = accepted_versions
        # B6 bağlantı noktası: B4 kabul akışı bunu HİÇ çağırmaz; testler kayıt
        # tutan bir executor enjekte edip çağrılmadığını kanıtlar.
        self._graph_executor = graph_executor
        self._failure_injection = failure_injection

    async def handle_delivery(self, raw: bytes, message: AbstractIncomingMessage) -> IntakeOutcome:
        """Tek broker teslimini işler.

        Dönüş = commit yapıldı, teslim ACK'lanabilir. İstisna = ACK yok:
        ``AgentContractError``/``IntakePolicyError``/``JobPayloadConflict``
        kalıcı ihlaldir ve B2 consumer base mesajı DLX'e yönlendirir.
        """

        try:
            parsed = parse_envelope(raw)
        except AgentContractError as exc:
            logger.warning(
                "intake sözleşme reddi: kategori=%s alan=%s message_id=%s delivery_tag=%s",
                exc.category.value,
                exc.field,
                _safe_message_id(message),
                getattr(message, "delivery_tag", None),
            )
            raise

        self._check_policy(parsed)

        result = await self._store.accept_execution(
            parsed,
            consumer_name=self._consumer_name,
            on_event=self._failure_injection,
        )
        if result.outcome == "created":
            logger.info(
                "iş kabul edildi: job_id=%s run_id=%s outbox_id=%s",
                result.job_id,
                parsed.envelope.run_id,
                result.outbox_id,
            )
        else:
            logger.info(
                "tekrar teslim idempotent karşılandı: outcome=%s run_id=%s detail=%s",
                result.outcome,
                parsed.envelope.run_id,
                result.detail,
            )
        return IntakeOutcome(
            accepted=True,
            outcome=result.outcome,
            run_id=parsed.envelope.run_id,
            job_id=str(result.job_id) if result.job_id else None,
            detail=result.detail,
        )

    def _check_policy(self, parsed: ParsedEnvelope) -> None:
        """Producer ve tür politikası (plan B4 adım 2).

        parse_envelope registry'deki izinli üretici kümesini ve yön kurallarını
        zaten doğrular; burada execute kuyruğunun tür politikası eklenir:
        kuyruğa yalnız execute komutu kabul edilir.
        """

        spec = parsed.spec
        if spec.message_type != EXECUTE_COMMAND_TYPE:
            raise IntakePolicyError(
                f"execute kuyruğu yalnız {EXECUTE_COMMAND_TYPE} kabul eder; gelen: {spec.message_type}"
            )
        if self._accepted_versions is not None and parsed.schema_version not in self._accepted_versions:
            raise IntakePolicyError(
                f"bu execute kuyruğu yalnız v{'/v'.join(str(v) for v in self._accepted_versions)} "
                f"kabul eder; gelen: v{parsed.schema_version}"
            )
        if spec.direction is not Direction.BACKEND_TO_AGENT:
            raise IntakePolicyError(
                f"{spec.message_type} backend→agent yönünde değil: {spec.direction.value}"
            )


def _safe_message_id(message: AbstractIncomingMessage) -> str:
    value = getattr(message, "message_id", None)
    return value if isinstance(value, str) else ""
