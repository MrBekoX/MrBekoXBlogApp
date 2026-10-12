"""DLQ replay doğrulaması (plan satır 420-421).

Replay öncesi yeniden doğrulama sırasının broker+DB üstünde kanıtı:
kimlik (payload_hash), mevcut terminal, iptal, deadline. Süresi geçmiş iş
DLQ'dan körlemesine başlatılmaz.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from messaging import BrokerPublisher, connect_broker
from messaging.job_store import compute_payload_hash
from messaging.retry import DlqReplayService
from messaging.topology import DEAD_EXCHANGE, EXECUTE_QUEUE

from .conftest import (
    AGENT_USER,
    ADMIN,
    envelope_bytes,
    make_envelope,
    make_settings,
    queue_depth,
    queue_depth_async,
    run,
    seed_job,
    status_is,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_broker")


def _dead_letter(envelope: Any) -> None:
    """Mesajı DLX üzerinden execute DLQ'ya düşürür (geç teslim simülasyonu)."""

    async def _publish() -> None:
        conn = await connect_broker(make_settings(*ADMIN))
        publisher = BrokerPublisher(conn, (DEAD_EXCHANGE,), make_settings(*ADMIN))
        await publisher.start()
        try:
            result = await publisher.publish_raw(
                DEAD_EXCHANGE,
                f"{envelope.message_type}.v1",
                envelope_bytes(envelope),
                message_id=envelope.message_id,
                correlation_id=envelope.correlation_id,
                type_name=envelope.message_type,
            )
            assert result.confirmed, result.detail
        finally:
            await publisher.close()
            await conn.close()

    run(_publish())
    run(wait_until(depth_is_dlq(1), timeout_seconds=10))


def depth_is_dlq(expected: int) -> Any:
    async def _condition() -> bool:
        return await queue_depth_async(f"{EXECUTE_QUEUE}.dlq") == expected

    return _condition


def dlq_depth() -> int:
    return run(queue_depth_async(f"{EXECUTE_QUEUE}.dlq"))


def _replay_service(store: Any, publisher: Any) -> DlqReplayService:
    service = DlqReplayService(
        None,  # bağlantı replay_batch'e çağrı başına verilir (kısa ömürlü araç deseni)
        store,
        publisher,
        queue_name=f"{EXECUTE_QUEUE}.dlq",
        origin_exchange="blog.agent.commands",
    )
    service.set_cancel_finalizer(lambda run_id: _finalize(store, run_id))
    return service


async def _finalize(store: Any, run_id: str) -> bool:
    result = await store.mark_cancelled_if_running(
        run_id,
        conversation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"conv:{run_id}")),
        correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:seed")),
        reason="dlq replay: cancel intent doğrulandı",
    )
    return result == "cancelled"


def _replay(service: DlqReplayService, *, limit: int = 10) -> list[Any]:
    async def _one() -> list[Any]:
        conn = await connect_broker(make_settings(*AGENT_USER))
        try:
            return await service.replay_batch(limit=limit, connection=conn)
        finally:
            await conn.close()

    return run(_one())


def _fetch_first_message_id() -> str | None:
    async def _one() -> str | None:
        from .conftest import fetch_message

        conn, channel, message = await fetch_message(EXECUTE_QUEUE)
        if message is None:
            await channel.close()
            await conn.close()
            return None
        value = message.message_id if isinstance(message.message_id, str) else None
        await channel.close()  # ACK yok: mesaj kuyrukta kalır
        await conn.close()
        return value

    return run(_one())


def test_valid_job_is_replayed_to_origin_with_same_id(store: Any, db_pool: Any, admin_publisher: Any) -> None:
    """Geçerli iş DLQ'dan orijinal kuyruğa AYNI message_id ile geri alınır."""

    run_id = "d1000000-0000-0000-0000-000000000001"
    envelope = make_envelope(run_id=run_id)
    run(seed_job(db_pool, run_id=run_id, status="queued", payload_hash=compute_payload_hash(envelope.payload)))
    _dead_letter(envelope)

    decisions = _replay(_replay_service(store, admin_publisher))

    assert len(decisions) == 1 and decisions[0].outcome == "replayed"
    run(wait_until(depth_is_dlq(0), timeout_seconds=10))
    assert _fetch_first_message_id() == envelope.message_id


def test_expired_job_is_not_blindly_replayed(store: Any, db_pool: Any, admin_publisher: Any) -> None:
    """Süresi geçmiş iş DLQ'dan körlemesine başlatılmaz; DLQ'da kalır."""

    run_id = "d1000000-0000-0000-0000-000000000002"
    envelope = make_envelope(run_id=run_id)
    run(seed_job(db_pool, run_id=run_id, status="queued", deadline_seconds=-60.0,
                 payload_hash=compute_payload_hash(envelope.payload)))
    _dead_letter(envelope)

    decisions = _replay(_replay_service(store, admin_publisher))

    assert len(decisions) == 1 and decisions[0].outcome == "deadline_exceeded"
    assert dlq_depth() == 1  # mesaj DLQ'da kaldı (düşürülmedi, başlatılmadı)
    assert queue_depth(EXECUTE_QUEUE) == 0  # orijinal kuyruğa GİTMEDİ


def test_cancel_intent_blocks_replay_and_finalizes_running(store: Any, db_pool: Any, admin_publisher: Any) -> None:
    """İptal niyeti replay'i engeller; running iş cancelled'a çekilir."""

    run_id = "d1000000-0000-0000-0000-000000000003"
    envelope = make_envelope(run_id=run_id)
    run(seed_job(db_pool, run_id=run_id, status="running", execution_attempt=1,
                 payload_hash=compute_payload_hash(envelope.payload)))
    from .conftest import insert_cancel_intent

    run(insert_cancel_intent(db_pool, run_id))
    _dead_letter(envelope)

    decisions = _replay(_replay_service(store, admin_publisher))

    assert len(decisions) == 1 and decisions[0].outcome == "cancel_requested"
    run(wait_until(status_is(db_pool, run_id, "cancelled"), timeout_seconds=5))
    assert dlq_depth() == 0
    assert queue_depth(EXECUTE_QUEUE) == 0


def test_terminal_job_replay_is_discarded(store: Any, db_pool: Any, admin_publisher: Any) -> None:
    """Mevut terminal yeniden doğrulanır: completed iş DLQ replay'iyle yeniden koşulmaz."""

    run_id = "d1000000-0000-0000-0000-000000000004"
    envelope = make_envelope(run_id=run_id)
    run(seed_job(db_pool, run_id=run_id, status="completed", payload_hash=compute_payload_hash(envelope.payload)))
    _dead_letter(envelope)

    decisions = _replay(_replay_service(store, admin_publisher))

    assert len(decisions) == 1 and decisions[0].outcome == "already_terminal"
    run(wait_until(depth_is_dlq(0), timeout_seconds=10))
    assert queue_depth(EXECUTE_QUEUE) == 0  # tekrar çalıştırma yok


def test_payload_mismatch_is_not_replayed(store: Any, db_pool: Any, admin_publisher: Any) -> None:
    """Kimlik doğrulaması: iş kaydıyla payload_hash uyuşmayan mesaj replay edilmez."""

    run_id = "d1000000-0000-0000-0000-000000000005"
    run(seed_job(db_pool, run_id=run_id, status="queued", payload_hash="gercek-hash"))
    envelope = make_envelope(run_id=run_id)  # payload'ı işin hash'iyle uyuşmaz
    _dead_letter(envelope)

    decisions = _replay(_replay_service(store, admin_publisher))

    assert len(decisions) == 1 and decisions[0].outcome == "identity_mismatch"
    assert dlq_depth() == 0  # çelişen mesaj düşürülür; kararla kalır
    assert queue_depth(EXECUTE_QUEUE) == 0


def test_unknown_run_is_replayed_to_intake(store: Any, db_pool: Any, admin_publisher: Any) -> None:
    """İş kaydı hiç yoksa replay serbesttir: intake idempotent kabulü yeniden yapar."""

    envelope = make_envelope(run_id="d1000000-0000-0000-0000-000000000006")
    _dead_letter(envelope)

    decisions = _replay(_replay_service(store, admin_publisher))

    assert len(decisions) == 1 and decisions[0].outcome == "replayed"
    run(wait_until(depth_is_dlq(0), timeout_seconds=10))
    assert queue_depth(EXECUTE_QUEUE) == 1
