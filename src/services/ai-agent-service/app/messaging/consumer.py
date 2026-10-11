"""Robust consumer tabanı (B2): sınırlı prefetch, manuel ACK, DLX'e nack.

Kurallar:
- Manuel ACK + sınırlı prefetch ile açık teslim sayısı kontrol edilir
  ([RMQ-CONFIRMS#C2]); ACK yalnız işleme tamamlandıktan sonra, teslimin geldiği
  kanal üzerinden verilir (aio-pikaIncomingMessage kendi kanalına ack eder).
- Handler istisnası mesajı ``nack(requeue=False)`` ile DLX'e yönlendirir;
  sürekli requeue döngüsü kurulmaz (plan B7 kuralının B2 tabanı).
- Callback gövdesi bytes olarak zaten tam bellekte gelir (aio-pika); handler
  sonrası kullanılacak veri handler içinde ayrıştırılır.
- QoS ve consumer kaydı robust kanalda bağlantı toparlanmasında yeniden
  uygulanır (aio-pika RobustChannel._on_open); kuyruk pasif declare edilir
  (K3: declarer backend, agent pasif doğrular).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from .errors import TopologyError
from .settings import BrokerSettings

__all__ = ["BrokerConsumer"]

Handler = Callable[[bytes, AbstractIncomingMessage], Awaitable[None]]


class BrokerConsumer:
    """Tek kuyruk tüketen robust consumer; ömür: start() -> stop()."""

    def __init__(
        self,
        connection: AbstractRobustConnection,
        queue_name: str,
        handler: Handler,
        settings: BrokerSettings | None = None,
        *,
        consumer_tag: str | None = None,
    ) -> None:
        self._connection = connection
        self._queue_name = queue_name
        self._handler = handler
        self._settings = settings or BrokerSettings()
        self._consumer_tag = consumer_tag
        self._channel: Any = None
        self._queue: Any = None
        self.running = False

    async def start(self) -> None:
        """QoS'i sınırla, kuyruğu pasif doğrula, tüketimi başlat."""

        self._channel = await self._connection.channel(publisher_confirms=False)
        await self._channel.set_qos(prefetch_count=self._settings.prefetch_count)
        try:
            self._queue = await self._channel.declare_queue(
                self._queue_name, durable=True, passive=True
            )
        except aio_pika.exceptions.ChannelNotFoundEntity as exc:
            raise TopologyError([f"queue:{self._queue_name}"]) from exc
        await self._queue.consume(
            self._on_message, no_ack=False, consumer_tag=self._consumer_tag
        )
        self.running = True

    async def stop(self) -> None:
        """Tüketimi nazikçe durdurur: kanal kapanışı consumer'ı iptal eder."""

        if self._channel is not None:
            await self._channel.close()
        self._channel = None
        self._queue = None
        self.running = False

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        try:
            await self._handler(message.body, message)
        except Exception:
            # İşleme hatası: requeue yok, DLX (ana kuyruğun x-dead-letter-exchange'i)
            # hedefine gider. ACK verilmediği için mesaj tekrar teslim edilmez.
            await message.nack(requeue=False)
            return
        await message.ack()
