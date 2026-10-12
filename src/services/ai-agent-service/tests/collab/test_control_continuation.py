"""B9 kontrol tüketici graph devamı: gerçek broker + gerçek Postgres üstünde.

Plan B9: "Action result komutu kontrol consumer'ında doğrulanmış sonuçla graph'ı
sürdürsün. Aynı onay için ikinci bir resume mesajı üretip graph'ı iki kez devam
ettirme."

Senaryolar:
- action_result (accepted) teslimi → driver bir kez; payload B1 sözleşme
  modeline çözümlenmiş; inbox kaydı yazılır; tekrar teslim (aynı message_id)
  duplicate ile karşılanır, driver TEKRAR çağrılmaz.
- resume_requested teslimi → driver'a sözleşme payload'ı ile iletilir.
- Eşzamanlı ikiz teslim → graph etkisi TEK (A9 çalışma makinesi ikinci
  müdahaleyi reddeder); kayıp/yinelenen graph devamı yok.
- Bilinmeyen run → kalıcı ihlal → DLQ (sessiz döngü yok; B7 davranışı).
- Driver hatası → teslim ACK'sız + inbox YOK (en az bir kez devam); sonraki
  teslimde driver yeniden çağrılır.
- Driver bağlıyken cancel akışı B7'deki gibi çalışır (driver cancel'a dokunmaz).
- Gerçek graph kanıtı: driver, backend'in doğrulanmış sonucunu A9 çalışma
  makinesine taşıyıp needs_input'taki çalışmayı RESOLVED/COMPLETED'a geçirir.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_core.models import compute_content_hash
from messaging.control import ControlConsumerService, ControlPolicyError
from messaging.retry import RetryAction, TransportRetryService

from .conftest import (
    CONTROL_QUEUE,
    TEST_TIERS,
    apply_decision,
    depth_is,
    envelope_bytes,
    fetch_message,
    inbox_count,
    make_action_result_payload,
    make_envelope,
    make_resume_payload,
    publish_command,
    queue_depth,
    run,
    seed_job,
    wait_until,
)
from .doubles import RecordingResumeDriver

pytestmark = pytest.mark.usefixtures("clean_broker")

PROPOSAL_ID = "7b9c0000-0000-0000-0000-00000000c0de"


def _control_service(store: Any, driver: Any) -> ControlConsumerService:
    from messaging.control import ControlConsumerService

    return ControlConsumerService(store, resume_driver=driver)


def _control_retry_service(store: Any, driver: Any, publisher: Any) -> TransportRetryService:
    return TransportRetryService(
        _control_service(store, driver).handle_delivery,
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


def _accepted_result(run_id: str, *, message_id: str | None = None) -> Any:
    return make_envelope(
        message_type="agent.action.result",
        payload=make_action_result_payload(proposal_id=PROPOSAL_ID, outcome="accepted"),
        run_id=run_id,
        message_id=message_id,
    )


def test_action_result_continues_graph_and_redelivery_is_duplicate(
    store: Any, db_pool: Any, agent_publisher: Any
) -> None:
    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id))
    driver = RecordingResumeDriver()
    envelope = _accepted_result(run_id)
    run(publish_command(envelope))

    service = _control_retry_service(store, driver, agent_publisher)
    decision = _process_control(service)

    assert decision.action == RetryAction.ACK, f"ilk teslim ACK olmalı: {decision}"
    assert driver.call_count == 1
    kind, driver_run_id, payload = driver.calls[0]
    assert kind == "action_result"
    assert driver_run_id == run_id
    assert payload.proposal_id == PROPOSAL_ID
    assert payload.outcome == "accepted"
    assert payload.applied_article_revision == 3  # kabul mesajı revizyonu taşır
    assert run(inbox_count(db_pool, envelope.message_id)) == 1

    # Ağ sonrası tekrar: AYNI message_id ile tekrar teslim → duplicate; driver
    # ikinci kez çağrılmaz (graph iki kez devam ettirilmez).
    run(publish_command(envelope, raw=envelope_bytes(envelope)))
    second = _process_control(service)
    assert second.action == RetryAction.ACK
    assert second.outcome == "completed"
    assert driver.call_count == 1
    assert run(inbox_count(db_pool, envelope.message_id)) == 1


def test_resume_requested_invokes_driver_with_contract_payload(
    store: Any, db_pool: Any, agent_publisher: Any
) -> None:
    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id))
    driver = RecordingResumeDriver()
    checkpoint_reference = f"agent-collab/{run_id}"
    envelope = make_envelope(
        message_type="agent.resume.requested",
        payload=make_resume_payload(checkpoint_reference=checkpoint_reference, user_ref="u:b9-owner"),
        run_id=run_id,
    )
    run(publish_command(envelope))

    decision = _process_control(_control_retry_service(store, driver, agent_publisher))

    assert decision.action == RetryAction.ACK
    assert driver.call_count == 1
    kind, driver_run_id, payload = driver.calls[0]
    assert kind == "resume_requested"
    assert driver_run_id == run_id
    assert payload.checkpoint_reference == checkpoint_reference
    assert payload.user_ref == "u:b9-owner"


def test_unknown_run_is_dead_lettered_without_inbox(
    store: Any, db_pool: Any, agent_publisher: Any
) -> None:
    run_id = str(uuid.uuid4())  # iş kaydı YOK
    driver = RecordingResumeDriver()
    run(publish_command(_accepted_result(run_id)))

    service = _control_retry_service(store, driver, agent_publisher)
    decision = _process_control(service)

    assert decision.action == RetryAction.NACK, f"bilinmeyen run DLQ'ya düşmeli: {decision}"
    assert driver.call_count == 0
    run(wait_until(depth_is(f"{CONTROL_QUEUE}.dlq", 1), timeout_seconds=10))
    assert queue_depth(CONTROL_QUEUE) == 0


def test_driver_failure_blocks_ack_and_retry_reaches_driver(
    store: Any, db_pool: Any, agent_publisher: Any
) -> None:
    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id))
    driver = RecordingResumeDriver(fail_on_call=1)  # ilk çağrı düşer
    envelope = _accepted_result(run_id)
    run(publish_command(envelope))

    service = _control_service(store, driver)

    async def _direct(raw: bytes) -> None:
        await service.handle_delivery(raw, _stub_message(envelope))

    with pytest.raises(RuntimeError, match="driver bilinçli başarısız"):
        run(_direct(envelope_bytes(envelope)))
    assert driver.call_count == 1
    assert run(inbox_count(db_pool, envelope.message_id)) == 0  # kayıt YOK → iş kaybolmaz

    # Tekrar teslim (transport retry simülasyonu): driver yeniden çağrılır ve
    # bu kez başarılı; inbox yazılır.
    result = run(service.handle_delivery(envelope_bytes(envelope), _stub_message(envelope)))
    assert result["outcome"] == "continued"
    assert driver.call_count == 2
    assert run(inbox_count(db_pool, envelope.message_id)) == 1


def test_concurrent_twin_deliveries_produce_single_graph_effect(
    store: Any, db_pool: Any
) -> None:
    """Dağıtık yarış: iki consumer aynı mesajı aynı anda alırsa graph etkisi TEK."""

    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id))
    graph_state = _proposal_review_state(run_id)
    driver = RecordingResumeDriver(graph=_fake_collab_graph(graph_state, run_id))
    service = _control_service(store, driver)
    envelope = _accepted_result(run_id)

    async def _race() -> list[dict[str, Any]]:
        results = await asyncio.gather(
            service.handle_delivery(envelope_bytes(envelope), _stub_message(envelope)),
            service.handle_delivery(envelope_bytes(envelope), _stub_message(envelope)),
            return_exceptions=True,
        )
        return results  # type: ignore[return-value]

    results = run(_race())

    continued = [r for r in results if isinstance(r, dict) and r["outcome"] == "continued"]
    duplicates = [r for r in results if isinstance(r, dict) and r["outcome"] == "duplicate"]
    guarded = [r for r in results if isinstance(r, BaseException)]
    assert len(continued) == 1, f"tam bir teslim devam ettirmeli: {results}"
    # Diğer ikiz ya inbox ön-okumasında duplicate görür ya da driver çağrısı
    # A9 makinesinin "sonuçlandı" guard'ına takılır; iki yolda da etkisi YOKTUR.
    assert len(duplicates) + len(guarded) == 1, f"ikinci ikiz etkisiz kalmalı: {results}"
    if guarded:
        from agent_core.errors import AgentErrorCode, PortError

        assert isinstance(guarded[0], PortError)
        assert guarded[0].code is AgentErrorCode.VALIDATION_ERROR
    # Graph etkisi TEK: çözülme tam bir kez üretildi.
    assert len(driver.outcomes) == 1
    assert driver.outcomes[0]["resolved"] is True
    assert run(inbox_count(db_pool, envelope.message_id)) == 1


def test_cancel_flow_unchanged_when_driver_attached(
    store: Any, db_pool: Any, agent_publisher: Any
) -> None:
    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id, status="queued"))
    driver = RecordingResumeDriver()
    cancel = make_envelope(
        message_type="agent.cancel.requested",
        payload={"reason": "kullanıcı isteği"},
        run_id=run_id,
    )
    run(publish_command(cancel))

    decision = _process_control(_control_retry_service(store, driver, agent_publisher))

    assert decision.action == RetryAction.ACK
    assert driver.call_count == 0  # driver cancel yoluna dokunmaz (B7 davranışı)
    run(wait_until(lambda: _status_is(db_pool, run_id, "cancelled"), timeout_seconds=5))
    assert run(_has_cancel_intent(db_pool, run_id)) is True


def test_real_collab_graph_resolves_from_validated_result(
    store: Any, db_pool: Any
) -> None:
    """Uç kanıt: doğrulanmış backend sonucu A9 çalışma makinesini RESOLVED'a taşır."""

    run_id = str(uuid.uuid4())
    run(seed_job(db_pool, run_id=run_id))
    driver = RecordingResumeDriver(graph=_real_collab_graph(run_id))
    service = _control_service(store, driver)
    envelope = _accepted_result(run_id)

    result = run(service.handle_delivery(envelope_bytes(envelope), _stub_message(envelope)))

    assert result["outcome"] == "continued"
    assert result["driver_outcome"]["stage"] == "completed"
    assert len(driver.outcomes) == 1
    assert driver.outcomes[0]["resolved"] is True  # başarı yalnız kabul sonucundan sonra


# ------------------------------------------------------------------ yardımcılar


class _StubMessage:
    """aio_pika mesajı yerine geçen en küçük double (test double işaretli)."""

    is_test_double = True

    def __init__(self, envelope: Any) -> None:
        self.message_id = envelope.message_id


def _stub_message(envelope: Any) -> _StubMessage:
    return _StubMessage(envelope)


async def _status_is(pool: Any, run_id: str, expected: str) -> bool:
    async with pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id)
        )
    return status == expected


async def _has_cancel_intent(pool: Any, run_id: str) -> bool:
    async with pool.acquire() as conn:
        return (
            await conn.fetchval(
                "SELECT 1 FROM agent.cancel_intents WHERE run_id = $1", uuid.UUID(run_id)
            )
            is not None
        )


def _proposal_review_state(run_id: str) -> Any:
    """A9 checkpoint state'i: PROPOSAL_REVIEW'da bekleyen iş birliği çalışması."""

    from agent_core.collab.models import CollabStage, CollaborationState
    from agent_core.models.action import ActionProposal

    summary = "İş birliği önerisi — konuk yazı. Kapsam: B9 testi. Takvim: ekim."
    proposed_content = "İş birliği talebi (B9 test)\n\nAmaç: konuk yazı\nKapsam: B9 testi"
    proposal = ActionProposal(
        proposal_id=PROPOSAL_ID,
        run_id=run_id,
        article_id="1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1",
        article_revision=3,
        base_content_hash=compute_content_hash("makale-içeriği"),
        summary=summary,
        proposed_content=proposed_content,
        created_at=datetime.now(timezone.utc),
    )
    return CollaborationState(
        stage=CollabStage.PROPOSAL_REVIEW,
        proposal=proposal,
        proposal_content_hash=compute_content_hash(proposed_content),
    )


def _real_collab_graph(run_id: str) -> Any:
    """Driver'ın graph yarısı: validated_result ile ``run_collaboration`` çağırır."""

    from datetime import timedelta

    from agent_core.collab.runner import run_collaboration
    from agent_core.models import BudgetProfile, ExecutionContext, ModePreference, RunIntent
    from agent_core.models.action import ValidatedActionResult
    from agent_core.models.routing import RouteDecision

    context = ExecutionContext(
        run_id=run_id,
        conversation_id=run_id,
        question="konuk yazı iş birliği",
        language="tr",
        mode_preference=ModePreference.FAST,
        article_id="1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1",
        article_revision=3,
        article_content_hash=compute_content_hash("makale-içeriği"),
        budget_profile=BudgetProfile(
            name="default",
            max_model_calls=16,
            max_total_tokens=32000,
            max_duration_seconds=600.0,
        ),
    )
    route = RouteDecision(
        run_id=run_id,
        selected_mode=_fast_mode(),
        intent=RunIntent.COLLABORATION,
        brief_reason="B9 test rotası",
        decided_at=datetime.now(timezone.utc),
    )

    async def _graph(kind: str, graph_run_id: str, payload: Any) -> dict[str, Any]:
        assert kind == "action_result"
        validated = ValidatedActionResult(
            proposal_id=payload.proposal_id,
            run_id=graph_run_id,
            outcome=payload.outcome,
            reason=payload.reason,
            applied_article_revision=payload.applied_article_revision,
            validated_at=datetime.fromisoformat(payload.validated_at.replace("Z", "+00:00")),
        )
        _state, outcome = await run_collaboration(
            context,
            route,
            state=_proposal_review_state(run_id),
            validated_result=validated,
        )
        return {
            "resolved": outcome.status.value == "completed",
            "stage": outcome.status.value,
        }

    return _graph


def _fake_collab_graph(state: Any, run_id: str) -> Any:
    """Tek etki kanıtı için sahte graph: ilk çağrı çözülür, ikincisi reddedilir."""

    resolved = {"done": False}

    async def _graph(kind: str, graph_run_id: str, payload: Any) -> dict[str, Any]:
        if resolved["done"]:
            from agent_core.errors import AgentErrorCode, PortError

            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "bu iş birliği çalışması sonuçlandı; sonuç üzerine devam edilmez",
                port="test-double",
            )
        resolved["done"] = True
        return {"resolved": True, "stage": "completed"}

    return _graph


def _fast_mode() -> Any:
    from agent_core.models import AgentMode

    return AgentMode.FAST
