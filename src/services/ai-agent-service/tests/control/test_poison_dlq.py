"""Poison mesaj: şema hatalı teslim DLQ'ya düşer, tekrar çalıştırılmaz (plan satır 419).

"Sürekli nack/requeue döngüsü oluşturma" ve "Şema hatalı mesajı tekrar tekrar
çalıştırma" yasaklarının broker üstünde kanıtı.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from messaging.retry import RetryAction, TransportRetryService

from .conftest import (
    CONTROL_QUEUE,
    EXECUTE_QUEUE,
    TEST_TIERS,
    apply_decision,
    depth_is,
    fetch_message,
    make_envelope,
    publish_command,
    queue_depth,
    run,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_broker")


def _rejecting_service(publisher: Any) -> TransportRetryService:
    """Handler'ı zarfı çözümleyen servis: şema ihlali kalıcı sınıfa düşer."""

    async def handler(raw: bytes, message: Any) -> None:
        from messaging.contracts import parse_envelope

        parse_envelope(raw)  # ihlalde AgentContractError yükselir

    return TransportRetryService(handler, publisher, queue_name=EXECUTE_QUEUE, tiers=TEST_TIERS)


def _poison_body() -> bytes:
    """Zorunlu alanı eksik (deadline_at yok) geçerli-JSON gövde."""
    return (
        '{"message_id":"' + str(uuid.uuid4()) + '","message_type":"agent.execute.requested",'
        '"schema_version":1,"run_id":"' + str(uuid.uuid4()) + '",'
        '"conversation_id":"' + str(uuid.uuid4()) + '",'
        '"correlation_id":"' + str(uuid.uuid4()) + '",'
        '"occurred_at":"2026-10-12T00:00:00Z","producer":"backend-net",'
        '"payload":{"user_ref":"u1","question":"soru","language":"tr",'
        '"mode_preference":"auto","budget_profile":"default"}}'
    ).encode("utf-8")


def _process_single(service: TransportRetryService, queue_name: str) -> Any:
    """Tek teslimi işler ve kararı broker'a uygular; mesaj yoksa None."""

    async def _one() -> Any:
        conn, channel, message = await fetch_message(queue_name)
        if message is None:
            await channel.close()
            await conn.close()
            return None
        decision = await service.handle_delivery(message.body, message)
        await apply_decision(message, decision)
        await channel.close()
        await conn.close()
        return decision

    return run(_one())


def test_schema_invalid_message_goes_to_dlq_once(agent_publisher: Any) -> None:
    run(publish_command(make_envelope(run_id="b1000000-0000-0000-0000-000000000001"), raw=_poison_body()))

    service = _rejecting_service(agent_publisher)
    deliveries = 0
    while True:
        decision = _process_single(service, EXECUTE_QUEUE)
        if decision is None:
            break
        deliveries += 1
        assert decision.action == RetryAction.NACK, f"poison teslim DLQ'ya gitmeli: {decision}"
        if deliveries > 3:
            pytest.fail("şema hatalı mesaj tekrar tekrar çalıştırılıyor (retry döngüsü)")

    assert deliveries == 1  # TEK kez çalıştırıldı; tekrar çalıştırma yok
    run(wait_until(depth_is(f"{EXECUTE_QUEUE}.dlq", 1), timeout_seconds=10))
    assert queue_depth(EXECUTE_QUEUE) == 0
    assert queue_depth(f"{EXECUTE_QUEUE}.retry.{TEST_TIERS[0]}s.q") == 0  # retry kademesi DOLMADI


def test_unparseable_body_is_not_republished(agent_publisher: Any) -> None:
    """JSON olmayan gövde retry yayınına gönderilmez; karar kalıcı reddir."""

    run(publish_command(make_envelope(run_id="b1000000-0000-0000-0000-000000000002"), raw=b"not-json-at-all"))

    service = _rejecting_service(agent_publisher)
    decision = _process_single(service, EXECUTE_QUEUE)
    assert decision is not None
    assert decision.action == RetryAction.NACK and decision.outcome == "contract_dead_letter"

    run(wait_until(depth_is(f"{EXECUTE_QUEUE}.dlq", 1), timeout_seconds=10))
    assert queue_depth(EXECUTE_QUEUE) == 0


def test_wrong_type_for_queue_is_permanent_rejection(store: Any, agent_publisher: Any) -> None:
    """Kuyruk tür politikası ihlali (kalıcı) → DLQ; iş kaydı YAZILMAZ."""

    # cancel komutu yanlışlıkla execute kuyruğunun routing key'iyle gönderilmiş olsun.
    cancel = make_envelope(message_type="agent.cancel.requested", run_id="b1000000-0000-0000-0000-000000000003")
    run(publish_command(cancel, routing_key="agent.execute.requested.v1"))

    from messaging.intake import IntakeService
    from messaging.job_store import JobStore

    job_store = JobStore(store._pool)  # B4 kabul deposu (tür politikası intake'te)
    intake = IntakeService(job_store, consumer_name="intake")
    service = TransportRetryService(intake.handle_delivery, agent_publisher, queue_name=EXECUTE_QUEUE, tiers=TEST_TIERS)

    decision = _process_single(service, EXECUTE_QUEUE)
    assert decision is not None
    assert decision.action == RetryAction.NACK and decision.outcome == "contract_dead_letter"

    run(wait_until(depth_is(f"{EXECUTE_QUEUE}.dlq", 1), timeout_seconds=10))
    assert run(job_store.count_jobs()) == 0  # yanlış türden iş ÜRETİLMEDİ
    assert queue_depth(CONTROL_QUEUE) == 0
