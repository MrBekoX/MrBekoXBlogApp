"""Gerçek broker üstünde kademeli retry akışı (plan satır 414-416).

Senaryolar:
- Transport hatası 4 kez tekrarlanır: kademeler 1s → 2s → 3s gerçek TTL
  kuyruklarıyla dolar, her turda delivery_attempt artar, message_id SABİT
  kalır; son denemede mesaj DLQ'ya düşer (sürekli retry döngüsü YOK).
- Retry yeniden yayını confirm almazsa eski teslim ACK EDİLMEZ (HOLD):
  mesaj brokerca tekrar teslim edilir, kaybolmaz.
- GraphExecutionError broker retry'sızdır: teslim ACK'lanır, kalıcı job
  politikasına (B6) bırakılır.
"""

from __future__ import annotations

from typing import Any

import pytest

from messaging.contracts import parse_envelope
from messaging.retry import (
    GraphExecutionError,
    RetryAction,
    TransportError,
    TransportRetryService,
)

from .conftest import (
    EXECUTE_QUEUE,
    TEST_TIERS,
    depth_is,
    make_envelope,
    publish_command,
    queue_depth,
    run,
    wait_until,
)


def _retry_service(publisher: Any, handler: Any) -> TransportRetryService:
    return TransportRetryService(handler, publisher, queue_name=EXECUTE_QUEUE, tiers=TEST_TIERS)


async def _apply_decision(message: Any, decision: Any) -> None:
    """RetryAwareBrokerConsumer._on_message semantiğini testte birebir uygular."""

    if decision.action == RetryAction.NACK:
        await message.nack(requeue=False)
    elif decision.action == RetryAction.HOLD:
        return  # ACK/NACK yok: broker tekrar teslim eder
    else:
        await message.ack()


def _deliver_once(service: TransportRetryService) -> Any:
    """Tek teslimi çeker, retry servisine verir, kararı broker'a uygular."""

    async def _one() -> Any:
        from .conftest import fetch_message

        conn, channel, message = await fetch_message(EXECUTE_QUEUE)
        assert message is not None, "teslim kuyrukta olmalı"
        decision = await service.handle_delivery(message.body, message)
        await _apply_decision(message, decision)
        await channel.close()
        await conn.close()
        return decision

    return run(_one())


pytestmark = pytest.mark.usefixtures("clean_broker")


def test_transport_failures_walk_tier_ladder_then_dlq(agent_publisher: Any) -> None:
    envelope = make_envelope(run_id="a1000000-0000-0000-0000-000000000001")
    run(publish_command(envelope))

    seen_attempts: list[int] = []
    seen_message_ids: list[str] = []

    def failing_handler(raw: bytes, message: Any) -> None:
        parsed = parse_envelope(raw)
        seen_attempts.append(parsed.envelope.delivery_attempt)
        seen_message_ids.append(parsed.envelope.message_id)
        raise TransportError("model sağlayıcısı geçici erişilemez")

    service = _retry_service(agent_publisher, failing_handler)

    decision = _deliver_once(service)
    assert decision.action == RetryAction.ACK and decision.tier_seconds == TEST_TIERS[0]

    run(wait_until(depth_is(EXECUTE_QUEUE, 1), timeout_seconds=15))
    assert _deliver_once(service).tier_seconds == TEST_TIERS[1]

    run(wait_until(depth_is(EXECUTE_QUEUE, 1), timeout_seconds=15))
    assert _deliver_once(service).tier_seconds == TEST_TIERS[2]

    run(wait_until(depth_is(EXECUTE_QUEUE, 1), timeout_seconds=15))
    final = _deliver_once(service)
    assert final.action == RetryAction.NACK and final.outcome == "dead_lettered"

    # Toplam deneme = kademe sayısı + 1; sürekli retry döngüsü YOK.
    assert seen_attempts == [0, 1, 2, 3]
    # Aynı mantıksal message_id tüm teslimlerde korunur.
    assert len(set(seen_message_ids)) == 1 and seen_message_ids[0] == envelope.message_id

    run(wait_until(depth_is(f"{EXECUTE_QUEUE}.dlq", 1), timeout_seconds=10))
    assert queue_depth(EXECUTE_QUEUE) == 0


def test_unconfirmed_republish_holds_delivery(agent_publisher: Any) -> None:
    """Confirm gelmeyen retry yayınında eski teslim ACK edilmez (plan satır 416)."""

    envelope = make_envelope(run_id="a1000000-0000-0000-0000-000000000002")
    run(publish_command(envelope))

    class UnconfirmedPublisher:
        async def publish_raw(self, *args: Any, **kwargs: Any) -> Any:
            from messaging.publisher import PublishResult

            return PublishResult(confirmed=False, detail="test: confirm kaybı")

    def failing_handler(raw: bytes, message: Any) -> None:
        raise TransportError("geçici hata")

    service = _retry_service(UnconfirmedPublisher(), failing_handler)  # type: ignore[arg-type]

    decision = _deliver_once(service)
    assert decision.action == RetryAction.HOLD and decision.outcome == "publish_unconfirmed"
    # ACK/NACK verilmedi: mesaj teslimde kalır; kanal kapanınca brokerca geri konur.
    run(wait_until(depth_is(EXECUTE_QUEUE, 1), timeout_seconds=10))
    assert queue_depth(f"{EXECUTE_QUEUE}.dlq") == 0  # DLQ'ya düşmedi: kayıp yok, tekrar teslim bekler


def test_graph_execution_error_is_acked_not_retried(agent_publisher: Any) -> None:
    """Graph yürütme hatası broker retry'sızdır: ACK + kalıcı job politikası."""

    envelope = make_envelope(run_id="a1000000-0000-0000-0000-000000000003")
    run(publish_command(envelope))

    calls = 0

    def graph_handler(raw: bytes, message: Any) -> None:
        nonlocal calls
        calls += 1
        raise GraphExecutionError("graph node başarısız")

    service = _retry_service(agent_publisher, graph_handler)
    decision = _deliver_once(service)
    assert decision.action == RetryAction.ACK and decision.outcome == "graph_ack"

    run(wait_until(depth_is(EXECUTE_QUEUE, 0), timeout_seconds=10))
    assert calls == 1
    assert queue_depth(f"{EXECUTE_QUEUE}.dlq") == 0
    assert queue_depth(f"{EXECUTE_QUEUE}.retry.{TEST_TIERS[0]}s.q") == 0
