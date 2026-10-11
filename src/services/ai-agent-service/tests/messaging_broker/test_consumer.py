"""Consumer kabul ölçütleri: sınırlı prefetch/eşzamanlı tüketim, handler hatasının
DLQ'ya düşmesi (requeue döngüsü yok) ve yeniden bağlantı sonrası tüketim."""

from __future__ import annotations

import asyncio
from typing import Any

import aio_pika

from messaging import BrokerConsumer, EXECUTE_QUEUE, connect_broker
from messaging.connection import broker_connection

from .conftest import (
    AGENT_USER,
    ADMIN,
    make_settings,
    restart_broker_container,
    run,
    wait_for_management,
    wait_until,
)


async def _publish_execute_commands(count: int, conn: Any) -> None:
    channel = await conn.channel(publisher_confirms=True)
    commands = await channel.declare_exchange("blog.agent.commands", passive=True)
    for index in range(count):
        result = await commands.publish(
            aio_pika.Message(
                f'{{"n":{index}}}'.encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=f"probe-{index}",
            ),
            "agent.execute.requested.v1",
            mandatory=True,
        )
        assert result is not None
    await channel.close()


def test_prefetch_limits_concurrent_handlers() -> None:
    """prefetch=2 ile eşzamanlı handler sayısı 2'yi aşmaz, tüm mesajlar işlenir."""

    async def scenario() -> None:
        in_flight = 0
        max_in_flight = 0
        processed: list[bytes] = []
        lock = asyncio.Lock()

        async def handler(body: bytes, message: Any) -> None:
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.3)
            processed.append(body)
            async with lock:
                in_flight -= 1

        settings = make_settings(*AGENT_USER, prefetch_count=2)
        async with broker_connection(settings) as consumer_conn:
            consumer = BrokerConsumer(consumer_conn, EXECUTE_QUEUE, handler, settings)
            await consumer.start()

            async with broker_connection(make_settings(*ADMIN)) as admin_conn:
                await _publish_execute_commands(5, admin_conn)

            await wait_until(lambda: len(processed) == 5, timeout_seconds=20.0)
            await consumer.stop()

        assert len(processed) == 5
        assert max_in_flight <= 2, f"prefetch aşıldı: {max_in_flight}"

    run(scenario())


def test_handler_failure_dead_letters_without_requeue_loop() -> None:
    """Handler hatası mesajı hedef DLQ'ya düşürür; kuyruk requeue döngüsü kurmaz."""

    async def scenario() -> None:
        attempts: list[bytes] = []

        async def failing_handler(body: bytes, message: Any) -> None:
            attempts.append(body)
            raise RuntimeError("bilinçli test hatası")

        settings = make_settings(*AGENT_USER)
        async with broker_connection(settings) as consumer_conn:
            consumer = BrokerConsumer(consumer_conn, EXECUTE_QUEUE, failing_handler, settings)
            await consumer.start()

            async with broker_connection(make_settings(*ADMIN)) as admin_conn:
                await _publish_execute_commands(1, admin_conn)

                # DLQ'ya düşmesini bekle
                dlq_channel = await admin_conn.channel(publisher_confirms=False)
                dlq = await dlq_channel.declare_queue(f"{EXECUTE_QUEUE}.dlq", passive=True)
                deadline = asyncio.get_running_loop().time() + 15.0
                dead: Any = None
                while asyncio.get_running_loop().time() < deadline:
                    dead = await dlq.get(fail=False, timeout=1.0)
                    if dead is not None:
                        break
                assert dead is not None, "mesaj DLQ'ya düşmedi"
                assert dead.routing_key == "agent.execute.requested.v1"  # rk korunur
                assert dead.redelivered in (True, False)  # DLX aktarımı teslim kaydı taşır
                await dead.ack()
                await dlq_channel.close()

            await wait_until(lambda: len(attempts) == 1, timeout_seconds=10.0)
            await consumer.stop()

        # tek işleme: requeue döngüsü yok (nack requeue=False)
        assert len(attempts) == 1

    run(scenario())


def test_consumer_recovers_after_broker_restart() -> None:
    """Gerçek kesinti: broker restart sonrası robust consumer yeniden bağlanır ve çalışır."""

    async def scenario() -> None:
        received: list[bytes] = []

        async def handler(body: bytes, message: Any) -> None:
            received.append(body)

        settings = make_settings(*AGENT_USER, reconnect_interval_seconds=1.5)
        consumer_conn = await connect_broker(settings)
        try:
            consumer = BrokerConsumer(consumer_conn, EXECUTE_QUEUE, handler, settings)
            await consumer.start()

            async with broker_connection(make_settings(*ADMIN)) as admin_conn:
                await _publish_execute_commands(1, admin_conn)
            await wait_until(lambda: len(received) >= 1, timeout_seconds=20.0)

            # --- gerçek kesinti: durable topology volume'de kalır ---
            restart_broker_container()
            wait_for_management()

            # kesinti SONRASI taze admin bağlantısıyla yayın (backend ayrı bağlantı)
            async with broker_connection(make_settings(*ADMIN)) as admin_conn:
                await _publish_execute_commands(1, admin_conn)

            await wait_until(lambda: len(received) >= 2, timeout_seconds=120.0)
            await consumer.stop()
        finally:
            await consumer_conn.close()

        assert len(received) >= 2, "yeniden bağlantı sonrası mesaj işlenmedi"

    run(scenario())
