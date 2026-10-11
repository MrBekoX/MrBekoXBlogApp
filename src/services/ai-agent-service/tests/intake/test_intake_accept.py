"""B4 kabul transaction testleri: idempotent kabul, çatışma, çökme pencereleri.

Senaryolar plan B4 kabul ölçütlerinden gelir:
- commit öncesi crash → yeniden teslimle kurtarılır;
- commit sonrası crash → çift iş yaratmaz;
- tekrar teslim idempotent;
- aynı run_id farklı payload → çatışma raporlanır;
- LLM/graph çağrısı yok (executor casusu tüm yollarda 0 çağrı).

Tüm testler GERÇEK broker (teslim/redelivery) ve GERÇEK Postgres
(migration'lı ``blogdb_agent_test``) kullanır; mock başarı başarı sayılmaz.
``failure_injection`` yalnız çökme pencerelerini simüle eder: DB ve broker
davranışı (rollback, redelivery, unique endeks) gerçektir.
"""

from __future__ import annotations

from typing import Any

import pytest

from messaging import IntakeService, JobPayloadConflict, JobStore, compute_payload_hash

from .conftest import (
    close_fetch,
    envelope_bytes,
    fetch_message,
    make_envelope,
    make_execution_payload,
    publish_command,
    run,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


def _intake_with_crash(store: JobStore, phase: str, executor_spy: Any) -> IntakeService:
    """Seçilen fazda ('pre_commit' | 'post_commit') çöken intake servisi."""

    def crash(event_phase: str) -> None:
        if event_phase == phase:
            raise RuntimeError(f"simulated crash at {event_phase}")

    return IntakeService(store, consumer_name="intake", graph_executor=executor_spy,
                         failure_injection=crash)


async def _deliver_once(intake: IntakeService, envelope: Any, *, ack: bool = True) -> Any:
    """Mesajı gerçek broker'dan çekip intake servisiyle işler; istenirse ACK eder."""

    conn, channel, message = await fetch_message()
    try:
        assert message is not None, "kuyrukta teslim bekleyen mesaj yok"
        outcome = await intake.handle_delivery(envelope_bytes(envelope), message)
        if ack:
            await message.ack()
        return outcome
    finally:
        await channel.close()
        await conn.close()


def test_first_accept_creates_job_and_outbox(intake: Any, store: Any, executor_spy: Any) -> None:
    envelope = make_envelope()
    run(publish_command(envelope))
    outcome = run(_deliver_once(intake, envelope))

    assert outcome.accepted is True
    assert outcome.outcome == "created"
    assert outcome.job_id is not None
    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox(pending_only=True)) == 1
    assert run(store.count_inbox()) == 1
    # B4: intake graph'ı çalıştırmaz — LLM/model çağrısı intake kapasitesini
    # tüketmez (plan kabul ölçütü).
    assert executor_spy.calls == []


def test_redelivery_same_message_id_is_inbox_idempotent(
    intake: Any, store: Any, executor_spy: Any
) -> None:
    envelope = make_envelope()
    run(publish_command(envelope))
    assert run(_deliver_once(intake, envelope)).outcome == "created"

    # Aynı mesaj AYNI message_id ile ikinci kez yayınlanır/teslim edilir
    # (B3 outbox publisher'ın confirm kaybı sonrası yeniden yayın yolu).
    run(publish_command(envelope))
    second = run(_deliver_once(intake, envelope))
    assert second.outcome == "duplicate_inbox"
    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox()) == 1
    assert executor_spy.calls == []


def test_same_run_same_payload_new_message_id_is_duplicate_job(
    intake: Any, store: Any, executor_spy: Any
) -> None:
    run_id = make_envelope().run_id
    payload = make_execution_payload()
    first_envelope = make_envelope(run_id=run_id, payload=payload)
    run(publish_command(first_envelope))
    first = run(_deliver_once(intake, first_envelope))
    assert first.outcome == "created"

    # Yeni message_id, aynı run_id + aynı payload: idempotent iş kabulü (B4 adım 4).
    second_envelope = make_envelope(run_id=run_id, payload=payload)
    run(publish_command(second_envelope))
    second = run(_deliver_once(intake, second_envelope))
    assert second.outcome == "duplicate_job"
    assert second.job_id == first.job_id
    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox()) == 1  # ikinci accepted olayı üretilmez
    assert executor_spy.calls == []


def test_same_run_different_payload_conflicts(intake: Any, store: Any, executor_spy: Any) -> None:
    run_id = make_envelope().run_id
    payload_a = make_execution_payload(question="İlk soru nedir?")
    payload_b = make_execution_payload(question="Bambaşka bir soru?")
    first_envelope = make_envelope(run_id=run_id, payload=payload_a)
    run(publish_command(first_envelope))
    assert run(_deliver_once(intake, first_envelope)).outcome == "created"

    conflict_envelope = make_envelope(run_id=run_id, payload=payload_b)
    run(publish_command(conflict_envelope))
    with pytest.raises(JobPayloadConflict) as excinfo:
        run(_deliver_once(intake, conflict_envelope, ack=False))

    assert excinfo.value.run_id == run_id
    assert excinfo.value.incoming_hash == compute_payload_hash(payload_b)
    # Mevcut iş korunur; çatışma inbox'a 'conflict' olarak raporlanır (plan B4).
    job = run(store.fetch_job(run_id))
    assert job is not None
    assert job["payload_hash"] == compute_payload_hash(payload_a)
    assert run(store.count_jobs()) == 1
    assert run(store.count_inbox(status="conflict")) == 1
    assert run(store.count_outbox()) == 1
    assert executor_spy.calls == []


def test_precommit_crash_is_recovered_by_redelivery(
    store: Any, executor_spy: Any
) -> None:
    crashing_intake = _intake_with_crash(store, "pre_commit", executor_spy)
    healthy_intake = IntakeService(store, consumer_name="intake", graph_executor=executor_spy)
    envelope = make_envelope()
    run(publish_command(envelope))

    # 1. teslim: commit ÖNCESİ çökme — transaction ROLLBACK eder, teslim ACK'sızdır.
    conn, channel, message = run(fetch_message())
    try:
        assert message is not None
        with pytest.raises(RuntimeError, match="simulated crash at pre_commit"):
            run(crashing_intake.handle_delivery(envelope_bytes(envelope), message))
        assert run(store.count_jobs()) == 0  # rollback: kalıcı iş YOK
        assert run(store.count_inbox()) == 0
        assert run(store.count_outbox()) == 0
    finally:
        run(close_fetch(conn, channel))  # ACK yok → broker mesajı kuyruğa geri koyar

    # 2. teslim (broker redelivery): tam kabul, tek iş.
    conn2, channel2, message2 = run(fetch_message())
    try:
        assert message2 is not None
        assert message2.redelivered is True, "mesaj brokerca yeniden teslim edilmeliydi"
        outcome = run(healthy_intake.handle_delivery(envelope_bytes(envelope), message2))
        assert outcome.outcome == "created"
        run(message2.ack())
    finally:
        run(close_fetch(conn2, channel2))

    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox(pending_only=True)) == 1
    assert run(store.count_inbox()) == 1
    assert executor_spy.calls == []


def test_postcommit_crash_does_not_duplicate_job(store: Any, executor_spy: Any) -> None:
    crashing_intake = _intake_with_crash(store, "post_commit", executor_spy)
    healthy_intake = IntakeService(store, consumer_name="intake", graph_executor=executor_spy)
    envelope = make_envelope()
    run(publish_command(envelope))

    # 1. teslim: commit tamamlandı, ACK verilmeden süreç çöktü.
    conn, channel, message = run(fetch_message())
    try:
        assert message is not None
        with pytest.raises(RuntimeError, match="simulated crash at post_commit"):
            run(crashing_intake.handle_delivery(envelope_bytes(envelope), message))
        assert run(store.count_jobs()) == 1  # commit kalıcı: iş kaybolmaz
        assert run(store.count_outbox(pending_only=True)) == 1
    finally:
        run(close_fetch(conn, channel))  # ACK verilmedi → yeniden teslim

    # 2. teslim: mevcut iş bulunur, yeni graph BAŞLATILMAZ, ACK alınır.
    conn2, channel2, message2 = run(fetch_message())
    try:
        assert message2 is not None
        assert message2.redelivered is True
        outcome = run(healthy_intake.handle_delivery(envelope_bytes(envelope), message2))
        assert outcome.outcome == "duplicate_inbox"
        run(message2.ack())
    finally:
        run(close_fetch(conn2, channel2))

    assert run(store.count_jobs()) == 1
    assert run(store.count_outbox()) == 1
    assert executor_spy.calls == []
