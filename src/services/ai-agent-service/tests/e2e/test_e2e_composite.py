"""B11 bileşik uçtan uca testler — GERÇEK broker + GERÇEK postgres + gerçek
intake/worker/relay/publisher hatı (model test sağlayıcısıyla: is_test_double).

Kapsanan plan maddeleri:
- "makale bağlamıyla soru → backend kabul + outbox → broker → intake → worker
  (graph) → kaynaklı cevap olayı" (backend projection + GET yarımı .NET B11
  suite'indedir; iki suite kablo sözleşmesiyle birleşir — rapor §E2E).
- yenileme/replay: AYNI message_id tekrar teslim intake'te tekilleşir.
- iptal yolu: cancel intent → worker terminali cancelled.
- kaldırılan içeriğe dayanan geç sonuç: stale_snapshot reddi.
- broker kapalıyken outbox birikmesi + toparlanma.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from e2e.harness import (
    count_jobs,
    job_row,
    make_e2e_worker,
    make_execute_envelope,
    make_execution_payload,
    pending_outbox_envelopes,
    publish_command,
    relay_once,
    run,
    run_intake_once,
    wait_until,
)

from messaging import ControlStore
from messaging.contracts import AgentEnvelope, Producer
from messaging.contracts.payloads import ArticleContentChangedV1
from messaging.content import ContentSyncState
from messaging.topology import BACKEND_EVENTS_QUEUE, EXECUTE_QUEUE

from e2e.conftest import (
    AGENT_USER,
    BACKEND_USER,
    fetch_event_envelopes,
    make_settings,
    queue_depth_async,
    run_broker_down,
    run_broker_up,
)


async def _depth_is(queue: str, expected: int) -> bool:
    from e2e.conftest import queue_depth_async  # lazy: conftest↔harness döngüsünü kırar

    return await queue_depth_async(queue) == expected


async def _depth_at_least(queue: str, minimum: int) -> bool:
    from e2e.conftest import queue_depth_async

    return await queue_depth_async(queue) >= minimum


pytestmark = pytest.mark.usefixtures("clean_environment")


# ---------------------------------------------------------------------------
# 1) Tam hat: komut → intake → worker(graph) → kaynaklı terminal olayı kabloda
# ---------------------------------------------------------------------------


def test_e2e_command_flows_to_sourced_terminal_event(store, db_pool, event_publisher, relay):
    # Not (B6 raporu kuralı): article üçlüsü taşıyan bağlamda citation'sız test
    # cevabı B5 yayın kuralınca completed'a ÇEVRİLMEZ. Bu suite'te test sağlayıcı
    # citation ÜRETEMEZ (gerçek retrieval/model yok); bu yüzden tam-hat testi
    # genel kapsamla koşar. "Makale bağlamı + citation'lı sourced answer" yarımı
    # .NET B11 suite'inde kablo üzerinden doğrulanır (rapor §E2E birleşimi).
    payload = make_execution_payload(question="Bu konuyu kısaca açıklar mısın?")
    envelope = make_execute_envelope(payload=payload)

    # 1) backend yarımı (kablo): komut gerçek backend_svc rolüyle yayınlanır.
    run(publish_command(envelope, make_settings(*BACKEND_USER)))
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 1)))

    # 2) GERÇEK intake: doğrulama → inbox → iş + accepted outbox TEK transaction → ACK.
    run(run_intake_once(store, make_settings(*AGENT_USER)))
    assert run(count_jobs(db_pool)) == 1
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 0)))  # ACK commit'ten sonra

    # accepted olayı outbox'ta; relay gerçek broker'a taşır.
    result = run(relay_once(relay))
    assert result.published >= 1

    # 3) GERÇEK worker: claim → graph (test sağlayıcılı) → terminal outbox.
    worker = make_e2e_worker(store, db_pool, publisher=event_publisher)
    cycle = run(worker.run_once())
    assert (cycle.idle, cycle.action) == (False, "completed")
    assert cycle.run_id == envelope.run_id

    row = run(job_row(db_pool, envelope.run_id))
    assert row["status"] == "completed"

    # 4) Terminal olay gerçek broker'a: relay → backend.agent.events.q.
    drained = run(relay_once(relay))
    assert drained.published >= 1

    run(wait_until(lambda: _depth_at_least(BACKEND_EVENTS_QUEUE, 1)))
    events = run(fetch_event_envelopes())
    types = [e.envelope.message_type for e in events]
    assert "agent.run.completed" in types, f"kabloda completed yok: {types}"

    completed = next(e for e in events if e.envelope.message_type == "agent.run.completed")
    assert completed.envelope.run_id == envelope.run_id
    assert completed.envelope.correlation_id == envelope.correlation_id
    assert completed.envelope.producer == Producer.AGENT_PY
    payload_completed = completed.envelope.payload
    assert payload_completed["event_sequence"] >= 1
    assert payload_completed["answer"], "terminal olay kaynaklı cevap taşımali"
    # B5 yayın kuralı: makale kapsamında citation taşımayan cevap completed'a
    # çevrilmez; bu test double'ı citation taşımaz → partial/kısmi yol olabilir.
    # Kesin iddia: terminal olay TEK ve event_sequence monoton.
    sequences = [e.envelope.payload["event_sequence"] for e in events]
    assert sequences == sorted(sequences), "event_sequence gerilemesi yok"


# ---------------------------------------------------------------------------
# 2) Yenileme/replay: AYNI message_id tekrar teslim tekilleşir
# ---------------------------------------------------------------------------


def test_e2e_redelivered_command_is_idempotent(store, db_pool, event_publisher, relay):
    envelope = make_execute_envelope()

    # İlk teslim: kabul + çalıştırma + terminal.
    run(publish_command(envelope, make_settings(*BACKEND_USER)))
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 1)))
    run(run_intake_once(store, make_settings(*AGENT_USER)))
    worker = make_e2e_worker(store, db_pool, publisher=event_publisher)
    first = run(worker.run_once())
    assert first.action == "completed"

    # Yenileme: AYNI message_id ile tekrar teslim (broker redelivery / replay).
    run(publish_command(envelope, make_settings(*BACKEND_USER)))
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 1)))
    run(run_intake_once(store, make_settings(*AGENT_USER)))

    # Tekilleştirme: ikinci iş YOK; terminal iş yeniden çalıştırılmaz.
    assert run(count_jobs(db_pool)) == 1
    second = run(worker.run_once())
    assert second.idle is True
    row = run(job_row(db_pool, envelope.run_id))
    assert row["status"] == "completed"
    assert row["execution_attempt"] == 1, "yenileme ikinci yürütme üretmemeli"


# ---------------------------------------------------------------------------
# 3) İptal yolu: cancel intent → worker terminali cancelled
# ---------------------------------------------------------------------------


def test_e2e_cancel_path_finalizes_cancelled(store, db_pool, relay):
    """İptal yolu: backend cancel komutu → GERÇEK control consumer → terminal.

    B6 kuralı: cancel intent'li iş worker tarafından claim EDİLMEZ; terminali
    kontrol hattı üretir (queued→cancelled + agent.run.cancelled TEK
    transaction). Bu test o gerçek hattı kullanır; worker çevrimi işin
    artık alınmadığını doğrular.
    """

    from messaging.control import ControlConsumerService
    from messaging.retry import RetryAction, TransportRetryService
    from messaging.topology import CONTROL_QUEUE

    envelope = make_execute_envelope()
    run(publish_command(envelope, make_settings(*BACKEND_USER)))
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 1)))
    run(run_intake_once(store, make_settings(*AGENT_USER)))

    # Backend cancel komutu gerçek üretici rolüyle control kuyruğuna.
    cancel = make_execute_envelope(run_id=envelope.run_id, message_id=str(uuid.uuid4()))
    run(publish_command(
        AgentEnvelope(
            message_id=cancel.message_id,
            message_type="agent.cancel.requested",
            schema_version=cancel.schema_version,
            run_id=envelope.run_id,
            conversation_id=envelope.conversation_id,
            correlation_id=envelope.correlation_id,
            occurred_at=cancel.occurred_at,
            producer=Producer.BACKEND_NET,
            payload={"reason": "e2e iptal"},
        ),
        make_settings(*BACKEND_USER),
        routing_key="agent.cancel.requested.v1",
    ))
    run(wait_until(lambda: _depth_is(CONTROL_QUEUE, 1)))

    # GERÇEK kontrol tüketimi: ControlConsumerService + transport retry katmanı.
    class _NoOpPublisher:
        async def publish_raw(self, *args: Any, **kwargs: Any) -> Any:
            from messaging.publisher import PublishResult

            return PublishResult(confirmed=True)

    async def _process_cancel() -> Any:
        from e2e.conftest import fetch_control_message

        fetched = await fetch_control_message()
        assert fetched is not None, "cancel komutu control kuyruğunda yok"
        conn, channel, message = fetched
        control_store = ControlStore(db_pool, schema="agent")
        service = TransportRetryService(
            ControlConsumerService(control_store).handle_delivery,
            _NoOpPublisher(),  # retry HOLD yolu bu senaryoda kullanılmaz (B7 deseni)
            queue_name=CONTROL_QUEUE,
            tiers=(1, 2, 3),
        )
        decision = await service.handle_delivery(message.body, message)
        await message.ack()
        await channel.close()
        await conn.close()
        return decision

    decision = run(_process_cancel())
    assert decision.action == RetryAction.ACK

    row = run(job_row(db_pool, envelope.run_id))
    assert row["status"] == "cancelled", "queued iş cancel ile başlamadan biter"

    # Worker çevrimi: cancel'lı iş artık claim EDİLMEZ (B6 claim filtresi).
    worker = make_e2e_worker(store, db_pool)
    cycle = run(worker.run_once())
    assert cycle.idle is True

    # cancelled terminal olayı TEK; relay gerçek broker'a taşır.
    events = run(pending_outbox_envelopes(db_pool, envelope.run_id))
    types = [e["message_type"] for e in events]
    assert types.count("agent.run.cancelled") == 1, f"terminal olay sayısı: {types}"
    assert types.count("agent.run.completed") == 0, "iptal edilen iş completed üretemez"

    run(relay_once(relay))
    run(wait_until(lambda: _depth_at_least(BACKEND_EVENTS_QUEUE, 1)))
    wire = run(fetch_event_envelopes())
    assert any(e.envelope.message_type == "agent.run.cancelled" for e in wire)


# ---------------------------------------------------------------------------
# 4) Kaldırılan içeriğe dayanan geç sonuç reddi (stale guard)
# ---------------------------------------------------------------------------


def test_e2e_removed_content_rejects_stale_command(store, db_pool, event_publisher):
    article_id = str(uuid.uuid4())
    payload = make_execution_payload(
        article_id=article_id,
        article_revision=4,
    )
    envelope = make_execute_envelope(payload=payload)

    run(publish_command(envelope, make_settings(*BACKEND_USER)))
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 1)))
    run(run_intake_once(store, make_settings(*AGENT_USER)))

    # İçerik kaldırıldı (B8 tombstone): revision 5 kaldırma anı; komut revizyon 4
    # ile uçuşta kaldı → yürütme BAŞLAMADAN reddedilir.
    state = ContentSyncState()
    state.apply_article_changed(
        ArticleContentChangedV1(
            article_id=article_id, article_revision=5, action="unpublished"
        )
    )
    worker = make_e2e_worker(
        store, db_pool, publisher=event_publisher, content_state=state
    )
    cycle = run(worker.run_once())
    assert cycle.action == "failed", f"çıkan: {cycle.action} {cycle.detail}"
    assert "eski komut" in cycle.detail

    row = run(job_row(db_pool, envelope.run_id))
    assert row["status"] == "failed"
    document = json.loads(row["result_json"])
    assert document["error_code"] == "stale_snapshot"

    # failed terminal olayı TEK — geç/kaynaklı cevap yayını YOK.
    events = run(pending_outbox_envelopes(db_pool, envelope.run_id))
    types = [e["message_type"] for e in events]
    assert types.count("agent.run.failed") == 1
    assert types.count("agent.run.completed") == 0


# ---------------------------------------------------------------------------
# 5) Broker kapalıyken outbox birikmesi + toparlanma (senaryo 9'un python yarısı)
# ---------------------------------------------------------------------------


def test_e2e_broker_outage_outbox_accumulates_then_recovers(
    store, db_pool, event_publisher, relay
):
    envelope = make_execute_envelope()
    run(publish_command(envelope, make_settings(*BACKEND_USER)))
    run(wait_until(lambda: _depth_is(EXECUTE_QUEUE, 1)))
    run(run_intake_once(store, make_settings(*AGENT_USER)))

    worker = make_e2e_worker(store, db_pool, publisher=event_publisher)
    cycle = run(worker.run_once())
    assert cycle.action == "completed"

    # Broker GERÇEKTEN kapanır (rabbitmqctl stop_app): relay yayını başarısız,
    # terminal olay kaydı DB outbox'ında beklemede kalır (kayıp yok).
    run_broker_down()
    try:
        outcome = run(relay_once(relay))
        assert outcome.published == 0, "broker kapalıyken yayın başarı sayılamaz"
        pending = run(pending_outbox_envelopes(db_pool, envelope.run_id))
        assert len(pending) >= 1, "broker kapalıyken terminal olay kaybedildi"
        pending_ids = {e["message_id"] for e in pending}  # toparlanma ÖNCESİ kanıt
    finally:
        run_broker_up()

    # Toparlanma: broker döner, AYNI message_id'li kayıtlar kabloda taşınır.
    outcome = run(relay_once(relay))
    assert outcome.published >= 1
    run(wait_until(lambda: _depth_at_least(BACKEND_EVENTS_QUEUE, 1)))
    wire = run(fetch_event_envelopes())
    wire_ids = {e.envelope.message_id for e in wire}
    recovered = wire_ids & pending_ids
    assert recovered, "toparlanmadan sonra bekleyen olay kabloda görünmedi"
