"""B4 outbox relay testleri: accepted olayının confirm'lu yayını ve beklemede bırakma.

- Confirm gelince kayıt published olur ve backend olay kuyruğu olayı tam zarf
  sözleşmesiyle alır ([RMQ-CONFIRMS#C1]: confirm broker kabulüdür).
- Yayın hatasında kayıt beklemede kalır, hata görünür yazılır, attempts artar
  (plan B3 publisher kuralı;ENG-OUTBOX#C2 relay tekrarına consumer idempotency).
- Lease (claimed_until + SKIP LOCKED) aynı kaydın iki relay'e düşmesini engeller.
"""

from __future__ import annotations

from typing import Any

import pytest

from messaging import (
    BrokerPublisher,
    IntakeService,
    JobStore,
    OutboxRelay,
    connect_broker,
)
from messaging.contracts import parse_envelope
from messaging.topology import BACKEND_EVENTS_QUEUE

from .conftest import (
    BACKEND_USER,
    envelope_bytes,
    fetch_message,
    make_envelope,
    make_execution_payload,
    make_settings,
    publish_command,
    queue_depth,
    queue_depth_is,
    run,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


async def _accept_one_job(intake: Any, store: Any) -> Any:
    envelope = make_envelope(payload=make_execution_payload())
    await publish_command(envelope)
    conn, channel, message = await fetch_message()
    try:
        assert message is not None
        outcome = await intake.handle_delivery(envelope_bytes(envelope), message)
        await message.ack()
        return envelope, outcome
    finally:
        await channel.close()
        await conn.close()


def _accept_one_job_sync(intake: Any, store: Any) -> Any:
    return run(_accept_one_job(intake, store))


def _make_relay(store: JobStore, publisher: BrokerPublisher) -> OutboxRelay:
    return OutboxRelay(store, publisher, batch_size=8, lease_seconds=30.0)


def test_relay_publishes_accepted_event_and_marks_published(
    intake: Any, store: Any, agent_publisher: Any
) -> None:
    command, _outcome = _accept_one_job_sync(intake, store)
    assert run(store.count_outbox(pending_only=True)) == 1

    relay = _make_relay(store, agent_publisher)
    result = run(relay.run_once())
    assert (result.claimed, result.published, result.failed) == (1, 1, 0)
    assert run(store.count_outbox(pending_only=True)) == 0

    # Backend olay kuyruğu accepted olayını alır (gerçek broker routing).
    run(wait_until(queue_depth_is(BACKEND_EVENTS_QUEUE, 1)))

    conn, channel, message = run(fetch_message(BACKEND_EVENTS_QUEUE, *BACKEND_USER))
    try:
        assert message is not None
        parsed = parse_envelope(message.body)
        assert parsed.envelope.message_type == "agent.run.accepted"
        assert parsed.envelope.run_id == command.run_id
        assert parsed.envelope.causation_id == command.message_id
        assert str(parsed.envelope.producer) == "agent-py"
        assert parsed.payload.event_sequence == 0
        assert parsed.payload.accepted_at  # UtcIsoString dolu
        run(message.ack())
    finally:
        run(_close(channel, conn))

    # İkinci relay çevrimi yayınlanmış kaydı tekrar yayınlamaz (ENG-OUTBOX#C2).
    # Not: management sayacı yüklü brokerda gecikebilir; sıfırlanmayı yoklarız.
    second = run(relay.run_once())
    assert second.claimed == 0
    run(wait_until(queue_depth_is(BACKEND_EVENTS_QUEUE, 0)))


def test_relay_failure_keeps_record_pending_with_error(intake: Any, store: Any, truncated_db: Any) -> None:
    _accept_one_job_sync(intake, store)

    # Başlatılmamış publisher: yayın RuntimeError ile düşer (yapılandırma hatası).
    async def _unstarted() -> Any:
        conn = await connect_broker(make_settings())
        publisher = BrokerPublisher(conn, ("blog.agent.events",), make_settings())
        return conn, publisher

    conn, unstarted_publisher = run(_unstarted())
    try:
        relay = _make_relay(store, unstarted_publisher)
        result = run(relay.run_once())
        assert (result.claimed, result.published, result.failed) == (1, 0, 1)

        async def _read_row() -> Any:
            async with truncated_db.acquire() as db:
                return await db.fetchrow(
                    "SELECT publish_attempts, last_error, published_at "
                    "FROM agent.outbox_events"
                )

        row = run(_read_row())
        assert row["published_at"] is None  # beklemede kalır (confirm yok)
        assert row["publish_attempts"] == 1
        assert row["last_error"] is not None and "start()" in row["last_error"]
    finally:
        async def _close_conn() -> None:
            await conn.close()

        run(_close_conn())


def test_claim_lease_prevents_double_claim(store: Any, intake: Any) -> None:
    _accept_one_job_sync(intake, store)

    async def _claims() -> Any:
        first = await store.claim_outbox_batch(limit=10, lease_seconds=30.0)
        second = await store.claim_outbox_batch(limit=10, lease_seconds=30.0)
        return first, second

    first_batch, second_batch = run(_claims())
    assert len(first_batch) == 1
    assert second_batch == []  # lease tutuluyor: aynı kayıt ikinci relay'e düşmez

    run(store.record_outbox_failure(first_batch[0]["outbox_id"], "test hatası"))

    # Lease bırakıldı (failure kaydı claim'i temizler): tekrar alınabilir.
    async def _reclaim() -> Any:
        return await store.claim_outbox_batch(limit=10, lease_seconds=30.0)

    reclaimed = run(_reclaim())
    assert len(reclaimed) == 1
    assert reclaimed[0]["outbox_id"] == first_batch[0]["outbox_id"]


async def _close(channel: Any, conn: Any) -> None:
    await channel.close()
    await conn.close()
