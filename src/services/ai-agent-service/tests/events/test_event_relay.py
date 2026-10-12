"""B5 outbox relay: progress/terminal olayları confirm'lu broker'a taşınır.

Plan B5: "Outbox publisher confirm sonrası yayın kaydını güncellesin" — relay
türden bağımsızdır; kabul ölçütü senaryoları burada gerçek broker üzerinden
kanıtlanır:
- tüm olay türleri backend.agent.events.q'ya tam zarf sözleşmesiyle düşer;
- confirm sonrası published_at yazılır, tekrar relay aynı kaydı almaz;
- yayın sırası oluşturulma sırasını izler (sequence ile aynı yönde).
"""

from __future__ import annotations

import uuid

import pytest

from messaging import AgentOutcome, OutboxRelay
from messaging.contracts import parse_envelope
from messaging.topology import BACKEND_EVENTS_QUEUE

from .conftest import (
    BACKEND_USER,
    article_citation,
    close_fetch,
    fetch_event_messages,
    make_run_ids,
    queue_depth,
    queue_depth_is,
    run,
    seed_accepted_job,
    usage_record,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


def _relay(store, agent_publisher) -> OutboxRelay:
    return OutboxRelay(store, agent_publisher, batch_size=16, lease_seconds=30.0)


def test_relay_publishes_progress_and_terminal_events_to_backend_queue(
    db_pool, store, publisher, agent_publisher
):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    run(
        _publish_trio(publisher, run_id, conversation_id, correlation_id)
    )

    result = run(_relay(store, agent_publisher).run_once())

    assert result.claimed == 3
    assert result.published == 3
    assert result.failed == 0

    # Kuyruk gerçekten üç olayı aldı (confirm'lu yayın; unroutable başarı sayılmaz).
    run(wait_until(queue_depth_is(BACKEND_EVENTS_QUEUE, 3)))

    fetched = run(fetch_event_messages(limit=8))
    assert len(fetched) == 3
    types = []
    for _conn, _channel, message in fetched:
        parsed = parse_envelope(bytes(message.body))
        types.append(parsed.spec.message_type)
        assert parsed.envelope.run_id == run_id
        assert parsed.envelope.producer == "agent-py"
    assert types == [
        "agent.run.mode_selected",
        "agent.run.progressed",
        "agent.run.completed",
    ]

    conn, channel = fetched[0][0], fetched[0][1]
    close_fetch(conn, channel)


def test_relay_marks_rows_published_and_second_run_claims_nothing(
    db_pool, store, publisher, agent_publisher
):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))
    run(_publish_trio(publisher, run_id, conversation_id, correlation_id))

    first = run(_relay(store, agent_publisher).run_once())
    assert first.published == 3

    async def _published_rows() -> int:
        return await db_pool.fetchval(
            "SELECT count(*) FROM agent.outbox_events WHERE published_at IS NOT NULL"
        )

    assert run(_published_rows()) == 3  # confirm sonrası yayın kaydı güncellendi

    second = run(_relay(store, agent_publisher).run_once())
    assert second.claimed == 0  # tekrar relay aynı kaydı yeniden yayınlamaz
    assert queue_depth(BACKEND_EVENTS_QUEUE) == 3


def test_relay_preserves_outbox_creation_order(db_pool, store, publisher, agent_publisher):
    """Yayın sırası outbox oluşturma sırasıdır; sequence ile aynı yönde ilerler."""

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    first = run(
        publisher.publish_progress(
            run_id=run_id, conversation_id=conversation_id, correlation_id=correlation_id,
            kind="retrieval_started", message="sıra 1",
        )
    )
    second = run(
        publisher.publish_progress(
            run_id=run_id, conversation_id=conversation_id, correlation_id=correlation_id,
            kind="retrieval_completed", message="sıra 2",
        )
    )
    assert first.payload["event_sequence"] < second.payload["event_sequence"]

    result = run(_relay(store, agent_publisher).run_once())
    assert result.published == 2

    fetched = run(fetch_event_messages(limit=8))
    sequences = [
        parse_envelope(bytes(message.body)).envelope.payload["event_sequence"]
        for _conn, _channel, message in fetched
    ]
    assert sequences == sorted(sequences)

    conn, channel = fetched[0][0], fetched[0][1]
    close_fetch(conn, channel)


def test_relay_publishes_terminal_snapshot_with_full_result(db_pool, store, publisher, agent_publisher):
    """Terminal olay tam sonuç snapshot'ı taşır: answer, citations, usage, scope."""

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))
    run(
        publisher.publish_outcome(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            outcome=AgentOutcome(
                kind="completed",
                selected_mode="analysis",
                report="# Rapor\n\nKaynaklı özet.",
                citations=(article_citation(run_id),),
                source_scope="article",
                usage=usage_record(run_id),
            ),
        )
    )

    result = run(_relay(store, agent_publisher).run_once())
    assert result.published == 1

    fetched = run(fetch_event_messages(limit=4))
    assert len(fetched) == 1
    parsed = parse_envelope(bytes(fetched[0][2].body))
    payload = parsed.envelope.payload
    assert parsed.spec.message_type == "agent.run.completed"
    assert payload["report"].startswith("# Rapor")
    assert payload["source_scope"] == "article"
    assert payload["usage"]["run_id"] == run_id
    assert payload["citations"][0]["kind"] == "article"
    assert "answer" not in payload  # answer/report ayrıklığı snapshot'ta korunur

    close_fetch(fetched[0][0], fetched[0][1])


async def _publish_trio(publisher, run_id: str, conversation_id: str, correlation_id: str) -> None:
    await publisher.publish_mode_selected(
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        selected_mode="deep_research",
        requires_web_search=True,
        reason="derin araştırma istendi",
    )
    await publisher.publish_progress(
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        kind="retrieval_started",
        message="makale bağlamı hazırlanıyor",
    )
    await publisher.publish_outcome(
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        outcome=AgentOutcome(
            kind="completed",
            selected_mode="analysis",
            answer="Kaynaklı yanıt.",
            citations=(article_citation(run_id),),
            source_scope="article",
            usage=usage_record(run_id),
        ),
    )
