"""Confirm'lu ve mandatory yayın (B2).

Kurallar:
- Publisher confirms broker kabulünü gösterir; agent işinin bitmesini değil
  (plan satır 16; [RMQ-CONFIRMS#C1]). Sonuç ``PublishResult`` ile ayrı raporlanır.
- ``mandatory=True``: bağlanamayan routing key basic.return ile fark edilir;
  routable olmayan mesaj başarı sayılmaz (plan satır 261). aio-pika kanalı
  ``on_return_raises=True`` ile açılır; return ``DeliveryError`` olarak gelir.
- Önemli mesajlar persistent (delivery_mode=2) ve durable exchange'lere gider
  ([RMQ-RELIABILITY#C2]).
- AMQP properties zarf ile tutarlı set edilir: message_id, correlation_id,
  content_type=application/json, type=machine-adı (B1 amqp eşlemesi; timestamp
  bilinçli taşınmaz).
- Exchange'ler pasif alınır (K3: declarer backend); publish ömrü kanal
  üzerinden robust bağlantıyla yönetilir, her mesaj için bağlantı açılmaz
  ([RMQ-DOTNET#C1] karşılığı aio-pika robust kullanım).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import DeliveryError
from aiormq import spec

from messaging.contracts import (
    AgentEnvelope,
    Direction,
    MAX_PAYLOAD_BYTES,
    lookup_spec,
)

from .settings import BrokerSettings

__all__ = ["BrokerPublisher", "PublishResult"]


@dataclass(frozen=True)
class PublishResult:
    """Tek yayının broker tarafı sonucu."""

    confirmed: bool
    returned: bool = False
    detail: str = ""


class BrokerPublisher:
    """Uzun ömürlü publisher: tek confirm kanalı + pasif exchange kolları.

    ``exchanges`` yayınlama yetkisinin sahibi olduğu exchange kümesidir ve
    açıkça verilir: backend için commands+content, agent için events. RabbitMQ
    4.x'te pasif declare'da kullanıcının hedef kaynağa en az bir izni olmalıdır
    (resmî access-control kuralı); bu yüzden küme rol bazlıdır.
    """

    def __init__(
        self,
        connection: AbstractRobustConnection,
        exchanges: tuple[str, ...],
        settings: BrokerSettings | None = None,
    ) -> None:
        self._connection = connection
        self._exchanges_names = tuple(exchanges)
        self._settings = settings or BrokerSettings()
        self._channel: Any = None
        self._exchanges: dict[str, Any] = {}

    async def start(self) -> None:
        """Confirm + mandatory kanalını ve pasif exchange kollarını açar."""

        self._channel = await self._connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        for name in self._exchanges_names:
            self._exchanges[name] = await self._channel.declare_exchange(
                name, type=ExchangeType.TOPIC, durable=True, passive=True
            )

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._exchanges = {}

    async def publish_envelope(self, envelope: AgentEnvelope) -> PublishResult:
        """Sözleşme kaydına göre exchange/routing key seçip zarfı yayınlar.

        Yalnız ``agent_to_backend`` yönü ve izinli üretici yayınlanabilir;
        yön/üretici uyuşmazlığı ValueError ile reddedilir (B1 producer kuralı).
        Kayıt zarfın kendi sürümünden seçilir (K4): v2 olayı ``.v2`` routing
        key'iyle, v1 olayı ``.v1`` ile yayınlanır.
        """

        spec_entry = lookup_spec(envelope.schema_version, envelope.message_type)
        if spec_entry is None:
            raise ValueError(
                f"Bilinmeyen mesaj türü/sürümü: {envelope.message_type} v{envelope.schema_version}"
            )
        if spec_entry.direction is not Direction.AGENT_TO_BACKEND:
            raise ValueError(
                f"{envelope.message_type} agent yayın yönünde değil: "
                f"{spec_entry.direction}"
            )
        body = envelope.model_dump_json(exclude_none=True).encode("utf-8")
        self._check_payload_size(envelope, body)
        return await self._publish(
            spec_entry.exchange,
            spec_entry.routing_key,
            body,
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            type_name=envelope.message_type,
        )

    async def publish_raw(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        *,
        message_id: str | None = None,
        correlation_id: str | None = None,
        type_name: str | None = None,
    ) -> PublishResult:
        """Registry dışı yayın (retry yönlendirme, test ve B3 outbox kullanır)."""

        return await self._publish(
            exchange,
            routing_key,
            body,
            message_id=message_id,
            correlation_id=correlation_id,
            type_name=type_name,
        )

    def _check_payload_size(self, envelope: AgentEnvelope, body: bytes) -> None:
        payload_size = len(json.dumps(envelope.payload, ensure_ascii=False).encode())
        if payload_size > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"payload {payload_size} bayt; sözleşme üst sınırı {MAX_PAYLOAD_BYTES}"
            )

    async def _publish(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        *,
        message_id: str | None,
        correlation_id: str | None,
        type_name: str | None,
    ) -> PublishResult:
        if self._channel is None:
            raise RuntimeError("BrokerPublisher.start() çağrılmadan yayın yapılmaz")
        message = Message(
            body,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=message_id,
            correlation_id=correlation_id,
            type=type_name,
        )
        try:
            confirmation = await self._exchanges[exchange].publish(
                message, routing_key, mandatory=True
            )
        except DeliveryError as exc:  # mandatory unroutable: basic.return geldi
            return PublishResult(
                confirmed=False,
                returned=True,
                detail=f"unroutable: {routing_key} -> {exchange}: {exc}",
            )
        confirmed = isinstance(confirmation, spec.Basic.Ack)
        return PublishResult(
            confirmed=confirmed,
            returned=False,
            detail="" if confirmed else f"beklenmeyen onay: {confirmation!r}",
        )
