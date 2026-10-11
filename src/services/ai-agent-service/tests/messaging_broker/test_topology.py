"""Topology kabul ölçütleri: tekrarlı kurulum bozmaz, pasif doğrulama fail-fast eder."""

from __future__ import annotations

import asyncio
from typing import Any

import aio_pika
import pytest

from messaging import (
    EXECUTE_QUEUE,
    TopologyError,
    build_topology,
    declare_topology,
    verify_topology,
)
from messaging.connection import broker_connection

from .conftest import ADMIN, AGENT_USER, make_settings, run


def test_topology_declare_is_idempotent() -> None:
    async def scenario() -> None:
        async with broker_connection(make_settings(*ADMIN)) as conn:
            channel = await conn.channel(publisher_confirms=False)
            await declare_topology(channel)
            await declare_topology(channel)  # ikinci kurulum: PRECONDITION_FAILED olmamalı
            await channel.close()
            await verify_topology(conn)  # taze kanallarla pasif denetim

    run(scenario())


def test_verify_topology_fail_fast_on_empty_vhost() -> None:
    """Topology hiç kurulmamış vhost'ta pasif doğrulama TopologyError verir."""

    async def scenario() -> None:
        # "/" vhost'ı boştur (topology yalnız blogapp_dev'te kuruldu)
        async with broker_connection(make_settings(*ADMIN, virtualhost="/")) as empty_conn:
            with pytest.raises(TopologyError) as excinfo:
                await verify_topology(empty_conn)
            assert any("exchange:blog.agent.commands" in m for m in excinfo.value.missing)
            assert any(f"queue:{EXECUTE_QUEUE}" in m for m in excinfo.value.missing)

    run(scenario())


def test_mismatched_queue_arguments_are_rejected() -> None:
    """Aynı adla farklı argümanla declare PRECONDITION_FAILED üretir (topoloji bozulmaz)."""

    async def scenario() -> None:
        name = "zz.b2.mismatch.q"
        async with broker_connection(make_settings(*ADMIN)) as conn:
            channel = await conn.channel(publisher_confirms=False)
            await channel.declare_queue(name, durable=True)
            with pytest.raises(aio_pika.exceptions.ChannelPreconditionFailed):
                await channel.declare_queue(
                    name, durable=True, arguments={"x-message-ttl": 1000}
                )
            # PRECONDITION_FAILED kanalı kapattı; temizlik taze kanalla
            cleanup = await conn.channel(publisher_confirms=False)
            await cleanup.queue_delete(name)
            await cleanup.close()
            await channel.close()

    run(scenario())


def test_verify_topology_with_agent_scope() -> None:
    """Agent rolü kapsamlı pasif doğrulama: kendi kuyrukları + events exchange'i.

    RabbitMQ 4.x pasif declare'da en az bir izin ister; agent commands/content
    exchange'lerini denetleyemez (test_auth'ta ACCESS_REFUSED kanıtı), bu
    yüzden doğrulama rol kapsamıyla çağrılır (K3 pasif doğrulama yolu).
    """

    async def scenario() -> None:
        from messaging import BACKEND_EVENTS_QUEUE

        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            await verify_topology(
                conn,
                exchanges=("blog.agent.events",),
                queues=(EXECUTE_QUEUE, "agent.control.q", "agent.content.q"),
            )
        assert BACKEND_EVENTS_QUEUE == "backend.agent.events.q"  # sabit koruması

    run(scenario())


def test_retry_topology_routes_back_to_origin_exchange() -> None:
    """Retry kuyruğu TTL sonrası mesajı orijinal exchange'e, aynı routing key ile döndürür."""

    tier = 1
    topology = build_topology(retry_tier_seconds=(tier,))
    retry_exchange = f"blog.agent.retry.{tier}s"
    tier_queue_name = "agent.execute.q.retry.1s.q"

    async def scenario() -> None:
        async with broker_connection(make_settings(*ADMIN)) as conn:
            channel = await conn.channel(publisher_confirms=True)
            await declare_topology(channel, topology)
            retry_ex = await channel.get_exchange(retry_exchange, ensure=False)
            result = await retry_ex.publish(
                aio_pika.Message(
                    b'{"probe":"retry"}',
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                "agent.execute.requested.v1",
                mandatory=True,
            )
            assert result is not None

            execute_q = await channel.declare_queue(EXECUTE_QUEUE, passive=True)
            deadline = asyncio.get_running_loop().time() + 15.0
            message: Any = None
            while asyncio.get_running_loop().time() < deadline:
                message = await execute_q.get(fail=False, timeout=2.0)
                if message is not None:
                    break
            assert message is not None, "retry kuyruğu mesajı orijinal kuyruğa dönmedi"
            assert message.routing_key == "agent.execute.requested.v1"
            assert message.body == b'{"probe":"retry"}'
            await message.ack()

            # test-artifaktları temizliği (paylaşılan topology'yi bozmadan)
            for queue in topology.queue_names:
                if queue.endswith(f".retry.{tier}s.q"):
                    await channel.queue_delete(queue)
            await channel.exchange_delete(retry_exchange)
            await channel.close()

    run(scenario())
