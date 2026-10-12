"""Robust broker bağlantısı (B2): uzun ömürlü tek bağlantı, otomatik toparlanma.

``connect_robust`` bağlantı kopmasında ``reconnect_interval`` aralığıyla yeniden
bağlanır (aio-pika robust bağlantı; [AIO-PIKA#C1]). İlk bağlantı kurulumu
başarısızsa hata yükselir: consumer açılışta sessiz kalmez, fail-fast edilir.
"""

from __future__ import annotations

from typing import AsyncIterator

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from contextlib import asynccontextmanager

from .settings import BrokerSettings

__all__ = ["connect_broker", "broker_connection"]


async def connect_broker(settings: BrokerSettings) -> AbstractRobustConnection:
    """Broker'a robust bağlantı açar; bağlantı ömrünü çağıran yönetir."""

    return await aio_pika.connect_robust(
        settings.amqp_url,
        heartbeat=settings.heartbeat_seconds,
        timeout=settings.connection_timeout_seconds,
        client_properties={"connection_name": settings.client_name},
        reconnect_interval=settings.reconnect_interval_seconds,
    )


@asynccontextmanager
async def broker_connection(
    settings: BrokerSettings,
) -> AsyncIterator[AbstractRobustConnection]:
    """Test/yardımcı kullanım için bağlantı aç-kapa bağlamı."""

    connection = await connect_broker(settings)
    try:
        yield connection
    finally:
        await connection.close()
