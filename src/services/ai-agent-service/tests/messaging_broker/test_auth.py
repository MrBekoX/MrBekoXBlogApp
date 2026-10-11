"""Yetki kabul ölçütleri: servis kullanıcıları publish/consume yetkileriyle sınırlıdır;
yetkisiz servis yayın yapamaz.

Beklenen broker davranışı gerçek brokerda ölçülmüştür (RabbitMQ 4.2):
- pasif exchange declare izin gerektirmez; aktif declare configure ister,
- pasif kuyruk declare read/configure denetimine tabidir,
- izinsiz kullanıcı vhost bağlantısı Connection.Close ile reddedilir.
"""

from __future__ import annotations

import pytest

from messaging import BACKEND_EVENTS_QUEUE, BrokerConsumer, BrokerPublisher
from messaging.connection import broker_connection

from .conftest import (
    AGENT_USER,
    BACKEND_USER,
    RESTRICTED_USER,
    make_settings,
    run,
)


def test_backend_service_cannot_publish_to_events_exchange() -> None:
    """backend_svc yalnız commands+content exchange'lerine yazar; events'e yazamaz.

    Broker reddi (ACCESS_REFUSED) burada kanıtlanır: exchange kolunu pasif alabilir
    (configure .* → en az bir izin), ama basic.publish write denetiminde düşer.
    """

    async def scenario() -> None:
        async with broker_connection(make_settings(*BACKEND_USER)) as conn:
            publisher = BrokerPublisher(
                conn,
                exchanges=("blog.agent.commands", "blog.content.events", "blog.agent.events"),
            )
            await publisher.start()
            with pytest.raises(Exception, match="ACCESS_REFUSED"):
                await publisher.publish_raw(
                    "blog.agent.events",
                    "agent.run.completed.v1",
                    b'{"probe":"denied"}',
                )
            await publisher.close()

    run(scenario())


def test_backend_service_publishes_commands_within_scope() -> None:
    """Pozitif kontrol: backend_svc kendi yetki alanında (commands) yayın yapabilir."""

    async def scenario() -> None:
        async with broker_connection(make_settings(*BACKEND_USER)) as conn:
            publisher = BrokerPublisher(conn, exchanges=("blog.agent.commands", "blog.content.events"))
            await publisher.start()
            result = await publisher.publish_raw(
                "blog.agent.commands",
                "agent.execute.requested.v1",
                b'{"probe":"backend-scope"}',
            )
            assert result.confirmed is True
            await publisher.close()

    run(scenario())


def test_restricted_service_cannot_even_connect_to_vhost() -> None:
    """İzinsiz kullanıcı vhost'a bile bağlanamaz: yetkisiz servis yayın yapamaz."""

    async def scenario() -> None:
        async def _try_connect() -> None:
            async with broker_connection(make_settings(*RESTRICTED_USER)):
                pass

        with pytest.raises(Exception):
            await _try_connect()

    run(scenario())


def test_agent_service_cannot_consume_backend_events_queue() -> None:
    """agent_svc read yetkisi komut/içerik kuyruklarıyla sınırlı; olay kuyruğunu tüketemez."""

    async def scenario() -> None:
        received: list[bytes] = []

        async def handler(body: bytes, message: object) -> None:
            received.append(body)

        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            consumer = BrokerConsumer(conn, BACKEND_EVENTS_QUEUE, handler)
            with pytest.raises(Exception, match="ACCESS_REFUSED"):
                await consumer.start()
            assert consumer.running is False

    run(scenario())


def test_agent_service_cannot_actively_declare() -> None:
    """agent_svc configure yetkisi yok: passive doğrulama OK, active declare reddedilir (K3)."""

    async def scenario() -> None:
        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            channel = await conn.channel(publisher_confirms=False)
            await channel.declare_exchange("blog.agent.events", passive=True)
            with pytest.raises(Exception, match="ACCESS_REFUSED"):
                await channel.declare_exchange("zz.b2.agent-created", durable=True)
            await channel.close()

    run(scenario())
