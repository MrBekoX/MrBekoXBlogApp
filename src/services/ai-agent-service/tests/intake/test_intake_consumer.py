"""B4 intake consumer testleri: gerçek BrokerConsumer döngüsü, ACK ve DLQ.

- Kabul edilen teslim ACK'lanır (kuyruk boşalır); ACK commit'ten sonra gelir.
- Sözleşme geçersiz / tür politikasına aykırı / çatışmalı mesajlar DLX'e düşer
  (requeue döngüsü yok — B2 consumer base davranışı); job oluşmaz veya mevcut
  iş korunur.
"""

from __future__ import annotations

from typing import Any

import pytest

from messaging import BrokerConsumer, IntakeService, connect_broker
from messaging.topology import EXECUTE_QUEUE

from .conftest import (
    envelope_bytes,
    job_count_is,
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


def _start_consumer(intake: IntakeService) -> Any:
    async def _start() -> Any:
        conn = await connect_broker(make_settings())
        consumer = BrokerConsumer(conn, EXECUTE_QUEUE, intake.handle_delivery)
        await consumer.start()
        return conn, consumer

    return run(_start())


def _stop_consumer(resources: Any) -> None:
    async def _stop() -> None:
        conn, consumer = resources
        await consumer.stop()
        await conn.close()

    run(_stop())


def test_consumer_acks_only_after_durable_accept(intake: Any, store: Any, executor_spy: Any) -> None:
    envelope = make_envelope()
    run(publish_command(envelope))
    # Broker başka agent testleriyle yüklüyken management sayacı gecikebilir;
    # görünürlüğü anlık doğrulama yerine yoklama ile kabul ederiz.
    run(wait_until(queue_depth_is(EXECUTE_QUEUE, 1)))

    resources = _start_consumer(intake)
    try:
        run(wait_until(job_count_is(store, 1)))
        # ACK commit'ten sonra: kuyruk boşalır (teslim onaylandı).
        run(wait_until(queue_depth_is(EXECUTE_QUEUE, 0)))
    finally:
        _stop_consumer(resources)

    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox(pending_only=True)) == 1
    assert executor_spy.calls == []


def test_invalid_contract_message_goes_to_dlq_without_job(intake: Any, store: Any) -> None:
    run(publish_command(make_envelope(), raw=b'{"bozuk json'))

    resources = _start_consumer(intake)
    try:
        run(wait_until(queue_depth_is(f"{EXECUTE_QUEUE}.dlq", 1)))
    finally:
        _stop_consumer(resources)

    assert run(store.count_jobs()) == 0
    assert run(store.count_inbox()) == 0  # doğrulanamayan mesaj işlenmiş sayılmaz
    assert queue_depth(EXECUTE_QUEUE) == 0  # requeue döngüsü yok


def test_wrong_type_message_is_policy_rejected_to_dlq(intake: Any, store: Any) -> None:
    # cancel komutu execute kuyruğunun routing key'iyle gönderilir: tür politikası
    # ihlali (B4 adım 2). Gerçek cancel işleri kontrol kuyruğundadır (B7 kapsamı).
    cancel = make_envelope(
        message_type="agent.cancel.requested", payload={"reason": "kullanıcı istedi"}
    )
    run(publish_command(
        cancel,
        raw=envelope_bytes(cancel),
        routing_key="agent.execute.requested.v1",
    ))

    resources = _start_consumer(intake)
    try:
        run(wait_until(queue_depth_is(f"{EXECUTE_QUEUE}.dlq", 1)))
    finally:
        _stop_consumer(resources)

    assert run(store.count_jobs()) == 0
    assert run(store.count_inbox()) == 0
    assert queue_depth(EXECUTE_QUEUE) == 0


def test_conflicting_message_goes_to_dlq_and_job_survives(
    intake: Any, store: Any, executor_spy: Any
) -> None:
    run_id = make_envelope().run_id
    first = make_envelope(run_id=run_id, payload=make_execution_payload(question="Birinci soru"))
    run(publish_command(first))
    resources = _start_consumer(intake)
    try:
        run(wait_until(job_count_is(store, 1)))

        conflict = make_envelope(
            run_id=run_id, payload=make_execution_payload(question="Farklı soru")
        )
        run(publish_command(conflict))
        # Çatışma kaydı nack'ten ÖNCE commit edilir; gerçek koşul inbox satırıdır
        # (DLQ sayacı yüklü brokerda gecikebilir/kalıntı gösterebilir).
        async def _conflict_recorded() -> bool:
            return await store.count_inbox(status="conflict") == 1

        run(wait_until(_conflict_recorded))
        run(wait_until(queue_depth_is(f"{EXECUTE_QUEUE}.dlq", 1)))
    finally:
        _stop_consumer(resources)

    # Çatışma raporlandı (DLQ) ama mevcut iş ve accepted olayı korunur.
    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox()) == 1
    assert run(store.count_inbox(status="conflict")) == 1
    assert executor_spy.calls == []
