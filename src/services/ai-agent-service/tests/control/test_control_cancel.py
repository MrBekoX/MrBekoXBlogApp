"""İptal akışı: kontrol tüketici + terminal-öncelik kuralları (plan satır 425-433).

Senaryolar:
- queued iş: cancel komutu → niyet + queued→cancelled + agent.run.cancelled
  olayı TEK transaction'da; iş hiç başlamadan biter (execute-öncesi engel).
- running iş: niyet kaydedilir (terminal DEĞİLDİR); B6 complete_job double'ı
  'rejected' döner; mark_cancelled_if_running terminali üretir.
- terminal iş: 'already_terminal' — geç cancel işi geri götürmez.
- tekrar teslim: ikinci cancel komutu idempotent karşılanır (yeni olay yok).
- resume/action-result: bilinmeyen run → kalıcı ihlal → DLQ (sessiz döngü yok).
- B6 store double ile terminal-öncelik yarışının iki yönü.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from messaging.control_store import CancelIntentOutcome
from messaging.retry import RetryAction, TransportRetryService
from messaging.topology import CONTROL_QUEUE

from .conftest import (
    CONTROL_QUEUE,
    TEST_TIERS,
    apply_decision,
    depth_is,
    fetch_message,
    make_envelope,
    publish_command,
    queue_depth,
    run,
    seed_job,
    status_is,
    wait_until,
)
from .doubles import B6WorkerStoreDouble

pytestmark = pytest.mark.usefixtures("clean_broker")


def _control_service(store: Any) -> Any:
    from messaging.control import ControlConsumerService

    return ControlConsumerService(store)


def _control_retry_service(store: Any, publisher: Any) -> TransportRetryService:
    return TransportRetryService(
        _control_service(store).handle_delivery,
        publisher,
        queue_name=CONTROL_QUEUE,
        tiers=TEST_TIERS,
    )


def _process_control(service: TransportRetryService) -> Any:
    async def _one() -> Any:
        conn, channel, message = await fetch_message(CONTROL_QUEUE)
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


def _cancel_command(run_id: str, *, reason: str = "kullanıcı isteği") -> Any:
    return make_envelope(
        message_type="agent.cancel.requested",
        payload={"reason": reason},
        run_id=run_id,
    )


async def _job_status(pool: Any, run_id: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))


async def _outbox_events(pool: Any, run_id: str, message_type: str) -> list[Any]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT message_id, envelope FROM agent.outbox_events "
            "WHERE envelope->>'run_id' = $1 AND message_type = $2 ORDER BY created_at",
            run_id,
            message_type,
        )


def test_cancel_queued_job_finalizes_before_execution(store: Any, db_pool: Any) -> None:
    """Execute-öncesi cancel engeli: queued iş cancel komutuyla başlamadan biter."""

    run_id = "c1000000-0000-0000-0000-000000000001"
    run(seed_job(db_pool, run_id=run_id, status="queued"))
    run(publish_command(_cancel_command(run_id)))

    service = _control_retry_service(store, _admin_commands_publisher(store))
    decision = _process_control(service)
    assert decision is not None and decision.action == RetryAction.ACK

    run(wait_until(status_is(db_pool, run_id, "cancelled"), timeout_seconds=5))
    cancelled_events = run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))
    assert len(cancelled_events) == 1  # durum + olay TEK transaction'da üretildi

    # İptal edilmiş işi worker double'ı ZATEN alamaz (status queued değil):
    worker = B6WorkerStoreDouble(db_pool)
    claimed = run(worker.claim_next_job())
    assert claimed is None  # execute hiç başlamadı


def test_cancel_running_job_records_intent_then_terminalizes(store: Any, db_pool: Any) -> None:
    """Running işte niyet kaydı terminal değildir; terminal mark_cancelled_if_running ile gelir."""

    run_id = "c1000000-0000-0000-0000-000000000002"
    run(seed_job(db_pool, run_id=run_id, status="running", execution_attempt=1))
    run(publish_command(_cancel_command(run_id)))

    service = _control_retry_service(store, _admin_commands_publisher(store))
    assert _process_control(service).action == RetryAction.ACK

    # Niyet kaydedildi ama iş RUNNING KALDI (cancel intent kaydı terminal değildir).
    assert run(_job_status(db_pool, run_id)) == "running"
    assert run(store.has_cancel_intent(run_id)) is True
    assert len(run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))) == 0

    # B6 worker: cancel intent'li işin complete'u 'rejected' döner (sözleşme guard'ı).
    worker = B6WorkerStoreDouble(db_pool)
    claimed = run(worker.claim_next_job())  # iş running; double claim etmez — running işi simüle etmek için doğrudan:
    assert claimed is None
    outcome = run(
        worker.complete_job(run_id, {"answer": "geç oldu"}, _fencing_of(run_id))
    )
    assert outcome == "rejected"  # aktif cancel intent var: completed yazılamaz

    # Terminali B7 üretir: mark_cancelled_if_running → cancelled + olay.
    result = run(
        store.mark_cancelled_if_running(
            run_id,
            conversation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"conv:{run_id}")),
            correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:seed")),
            reason="kullanıcı isteği",
        )
    )
    assert result == "cancelled"
    assert len(run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))) == 1


def test_cancel_terminal_job_is_rejected_and_leaves_state(store: Any, db_pool: Any) -> None:
    """Geç cancel: terminal işin durumunu geri götürmez (already_terminal)."""

    run_id = "c1000000-0000-0000-0000-000000000003"
    run(seed_job(db_pool, run_id=run_id, status="completed"))
    run(publish_command(_cancel_command(run_id)))

    service = _control_retry_service(store, _admin_commands_publisher(store))
    assert _process_control(service).action == RetryAction.ACK

    run(wait_until(status_is(db_pool, run_id, "completed"), timeout_seconds=2))
    assert len(run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))) == 0
    intent_result = run(
        store.record_cancel_intent(
            run_id,
            requested_by="backend-net",
            conversation_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
        )
    )
    assert intent_result.outcome == CancelIntentOutcome.ALREADY_TERMINAL


def test_duplicate_cancel_delivery_is_idempotent(store: Any, db_pool: Any) -> None:
    """Tekrar teslim edilen cancel komutu yeni terminal olay üretmez (inbox idempotency)."""

    run_id = "c1000000-0000-0000-0000-000000000004"
    run(seed_job(db_pool, run_id=run_id, status="queued"))
    command = _cancel_command(run_id)
    run(publish_command(command))

    service = _control_retry_service(store, _admin_commands_publisher(store))
    assert _process_control(service).action == RetryAction.ACK

    # AYNI message_id ile tekrar teslim (broker redelivery simülasyonu).
    run(publish_command(command, raw=_bytes_of(command)))
    assert _process_control(service).action == RetryAction.ACK

    cancelled_events = run(_outbox_events(db_pool, run_id, "agent.run.cancelled"))
    assert len(cancelled_events) == 1  # ikinci teslim yalnız ACK aldı


def _bytes_of(envelope: Any) -> bytes:
    return envelope.model_dump_json(exclude_none=True).encode("utf-8")


def test_resume_unknown_run_is_dead_lettered_without_loop(store: Any, db_pool: Any) -> None:
    """Bilinmeyen run'a resume komutu sessiz döngüye girmez; DLQ'da görünür olur."""

    resume = make_envelope(
        message_type="agent.resume.requested",
        payload={"checkpoint_reference": "agent-run/none/turn/1", "user_ref": "user-1"},
        run_id="c1000000-0000-0000-0000-000000000005",
    )
    run(publish_command(resume))

    service = _control_retry_service(store, _admin_commands_publisher(store))
    decision = _process_control(service)
    assert decision.action == RetryAction.NACK and decision.outcome == "contract_dead_letter"
    run(wait_until(depth_is(f"{CONTROL_QUEUE}.dlq", 1), timeout_seconds=10))
    assert queue_depth(CONTROL_QUEUE) == 0


def test_action_result_known_run_is_acked_for_b9(store: Any, db_pool: Any) -> None:
    """Bilinen run'da action result kayda alınır ve ACK edilir (B9 bağlantı noktası)."""

    run_id = "c1000000-0000-0000-0000-000000000006"
    run(seed_job(db_pool, run_id=run_id, status="running"))
    action_result = make_envelope(
        message_type="agent.action.result",
        payload={
            "proposal_id": str(uuid.uuid4()),
            "outcome": "accepted",
            "applied_article_revision": 1,
            "validated_at": "2026-10-12T00:00:00Z",
        },
        run_id=run_id,
    )
    run(publish_command(action_result))

    service = _control_retry_service(store, _admin_commands_publisher(store))
    assert _process_control(service).action == RetryAction.ACK
    assert queue_depth(f"{CONTROL_QUEUE}.dlq") == 0


def test_terminal_precedence_both_directions_with_worker_double(store: Any, db_pool: Any) -> None:
    """Terminal-öncelik kuralı (ortak sözleşme) store double ile iki yönde kanıtlanır."""

    # (a) cancel intent ÖNCE → complete_job 'rejected' → mark_cancelled_if_running cancelled üretir.
    run_id_a = "c1000000-0000-0000-0000-000000000007"
    conversation_a = run(seed_job(db_pool, run_id=run_id_a, status="running", execution_attempt=1))
    run(store.record_cancel_intent(
        run_id_a, requested_by="backend-net", conversation_id=conversation_a,
        correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:seed")),
    ))
    worker = B6WorkerStoreDouble(db_pool)
    assert run(worker.complete_job(run_id_a, {"answer": "x"}, _fencing_of(run_id_a))) == "rejected"
    assert run(store.mark_cancelled_if_running(
        run_id_a, conversation_id=conversation_a,
        correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:seed")),
    )) == "cancelled"
    assert run(_job_status(db_pool, run_id_a)) == "cancelled"

    # (b) completed commit'i cancel intent'ten ÖNCE → record_cancel_intent 'already_terminal'.
    run_id_b = "c1000000-0000-0000-0000-000000000008"
    conversation_b = run(seed_job(db_pool, run_id=run_id_b, status="running", execution_attempt=1))
    assert run(worker.complete_job(run_id_b, {"answer": "hazır"}, _fencing_of(run_id_b))) == "completed"
    intent = run(store.record_cancel_intent(
        run_id_b, requested_by="backend-net", conversation_id=conversation_b,
        correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:seed")),
    ))
    assert intent.outcome == CancelIntentOutcome.ALREADY_TERMINAL  # tamamlanma kazanır
    assert run(store.mark_cancelled_if_running(
        run_id_b, conversation_id=conversation_b,
        correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "corr:seed")),
    )) == "untouched"  # terminal işe dokunmaz
    assert run(_job_status(db_pool, run_id_b)) == "completed"


def _fencing_of(run_id: str) -> str:
    """seed_job'ın running durumda ürettiği fencing token'ı (aynı formül)."""

    return f"fnc-{uuid.UUID(run_id).hex[:12]}"


def _admin_commands_publisher(store: Any) -> Any:
    """Retry yayıncısı gerekmez; testlerde HOLD yolu kullanılmaz — NoOp publisher."""

    class NoOpPublisher:
        async def publish_raw(self, *args: Any, **kwargs: Any) -> Any:
            from messaging.publisher import PublishResult

            return PublishResult(confirmed=True)

    return NoOpPublisher()
