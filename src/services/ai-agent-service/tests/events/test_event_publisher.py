"""B5 AgentEventPublisher: outbox'a aynı-transaction yazım ve atomik sequence.

Kabul ölçütü bağlantıları (plan B5):
- atomik event_sequence: run başına eşzamanlı yayıncılar duplicate/ters sıra ÜRETEMEZ.
- kritik durum + terminal sonuç outbox kaydıyla AYNI transaction'da.
- kaynak/kapsam kontrolü tamamlanmış sonuç yayınlanır.
- sık ilerleme sinyalleri seyrekleştirilir; token başına broker mesajı yok.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from messaging import AgentOutcome, AlreadyTerminal, EventPublishError, ThrottledProgress
from messaging.contracts import parse_envelope

from .conftest import (
    article_citation,
    make_run_ids,
    run,
    seed_accepted_job,
    usage_record,
    web_citation,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


# ------------------------------------------------------------------ progress


async def _publish_progress(publisher, run_id, conversation_id, correlation_id, kind, message):
    return await publisher.publish_progress(
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        kind=kind,
        message=message,
    )


def test_progress_events_get_atomic_contract_valid_sequences(db_pool, publisher):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    first = run(
        _publish_progress(publisher, run_id, conversation_id, correlation_id, "retrieval_started", "arama başladı")
    )
    second = run(
        _publish_progress(publisher, run_id, conversation_id, correlation_id, "retrieval_completed", "arama bitti")
    )
    third = run(
        _publish_progress(publisher, run_id, conversation_id, correlation_id, "generation_started", "üretim başladı")
    )

    assert not isinstance(first, ThrottledProgress)
    assert [first.payload["event_sequence"], second.payload["event_sequence"], third.payload["event_sequence"]] == [1, 2, 3]

    # Zarf sözleşmeye birebir uymak zorundadır (B1 parse_envelope geri doğrulaması).
    for envelope in (first, second, third):
        parsed = parse_envelope(envelope.model_dump_json(exclude_none=True).encode("utf-8"))
        assert parsed.spec.message_type == "agent.run.progressed"
        assert parsed.envelope.producer == "agent-py"
        assert parsed.envelope.run_id == run_id


def test_progress_throttles_same_kind_but_keeps_transitions(db_pool, slow_publisher):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    first = run(
        _publish_progress(slow_publisher, run_id, conversation_id, correlation_id, "research_round_completed", "tur 1")
    )
    throttled = run(
        _publish_progress(slow_publisher, run_id, conversation_id, correlation_id, "research_round_completed", "tur 2")
    )
    other_kind = run(
        _publish_progress(slow_publisher, run_id, conversation_id, correlation_id, "generation_started", "üretim")
    )

    assert isinstance(first, object) and not isinstance(first, ThrottledProgress)
    assert isinstance(throttled, ThrottledProgress)
    assert not isinstance(other_kind, ThrottledProgress)

    async def _count() -> int:
        return await db_pool.fetchval("SELECT count(*) FROM agent.outbox_events")

    assert run(_count()) == 2  # throttle edilmiş sinyal kayıt yazmaz, sıra tüketmez


def test_concurrent_publishers_cannot_duplicate_or_regress_sequence(db_pool, publisher):
    """Atomiklik: 12 eşzamanlı yayıncı → benzersiz, artan, aralıksız 1..12."""

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    kinds = [
        "run_started", "mode_selected", "article_context_ready", "run_resumed",
        "retrieval_started", "retrieval_completed", "research_started",
        "research_round_completed", "generation_started", "generation_completed",
        "validation_completed", "action_proposed",
    ]

    async def _publish_all() -> list[int]:
        async def _one(kind: str) -> int:
            envelope = await publisher.publish_progress(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                kind=kind,
                message=f"{kind} sinyali",
            )
            assert not isinstance(envelope, ThrottledProgress)
            return int(envelope.payload["event_sequence"])

        return list(await asyncio.gather(*(_one(kind) for kind in kinds)))

    sequences = sorted(run(_publish_all()))
    assert sequences == list(range(1, 13))  # duplicate yok, ters sıra yok, boşluk yok


# ------------------------------------------------------------------ terminal


def test_terminal_outcome_writes_job_status_and_outbox_atomically(db_pool, publisher):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    envelope = run(
        publisher.publish_outcome(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            outcome=AgentOutcome(
                kind="completed",
                selected_mode="fast",
                answer="Makale X konusunu işliyor.",
                citations=(article_citation(run_id),),
                source_scope="article",
                usage=usage_record(run_id),
            ),
        )
    )

    async def _check() -> tuple[str, int, str]:
        status = await db_pool.fetchval("SELECT status FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id))
        count = await db_pool.fetchval("SELECT count(*) FROM agent.outbox_events")
        first_type = await db_pool.fetchval("SELECT message_type FROM agent.outbox_events LIMIT 1")
        return status, count, first_type

    status, count, message_type = run(_check())
    assert status == "completed"  # kritik durum outbox ile aynı transaction'da
    assert count == 1
    assert message_type == "agent.run.completed"
    assert envelope.message_type == "agent.run.completed"
    parsed = parse_envelope(envelope.model_dump_json(exclude_none=True).encode("utf-8"))
    assert parsed.envelope.payload["event_sequence"] == 1
    assert parsed.envelope.payload["source_scope"] == "article"
    assert parsed.envelope.payload["answer"]


def test_second_terminal_event_is_never_produced(db_pool, publisher):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    run(
        publisher.publish_outcome(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            outcome=AgentOutcome(kind="failed", error_code="provider_error", error_message="sağlayıcı hatası"),
        )
    )
    with pytest.raises(AlreadyTerminal):
        run(
            publisher.publish_outcome(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                outcome=AgentOutcome(
                    kind="completed",
                    selected_mode="fast",
                    answer="geç gelen başarı",
                    citations=(article_citation(run_id),),
                    source_scope="article",
                    usage=usage_record(run_id),
                ),
            )
        )

    async def _rows() -> tuple[int, str]:
        count = await db_pool.fetchval("SELECT count(*) FROM agent.outbox_events")
        status = await db_pool.fetchval("SELECT status FROM agent.jobs")
        return count, status

    count, status = run(_rows())
    assert count == 1  # ikinci terminal olay üretilmedi
    assert status == "failed"


def test_terminal_for_unknown_run_is_rejected(db_pool, publisher):
    run_id, conversation_id, correlation_id = make_run_ids()  # iş kaydı YOK

    with pytest.raises(EventPublishError):
        run(
            publisher.publish_outcome(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                outcome=AgentOutcome(kind="cancelled", cancel_reason="bilinmeyen run"),
            )
        )


def test_inconsistent_source_scope_result_is_not_published(db_pool, publisher):
    """Kaynak/kapsam kontrolü tamamlanmış sonuç yayınlanır: article scope + web
    citation çelişkisi yayın öncesi reddedilir; hiçbir kayıt yazılmaz."""

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    with pytest.raises(EventPublishError):
        run(
            publisher.publish_outcome(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                outcome=AgentOutcome(
                    kind="completed",
                    selected_mode="fast",
                    answer="web kaynağı article scope ile uyuşmuyor",
                    citations=(web_citation(),),
                    source_scope="article",
                    usage=usage_record(run_id),
                ),
            )
        )

    async def _check() -> tuple[int, str]:
        count = await db_pool.fetchval("SELECT count(*) FROM agent.outbox_events")
        status = await db_pool.fetchval("SELECT status FROM agent.jobs")
        return count, status

    count, status = run(_check())
    assert count == 0
    assert status == "accepted"  # tamamlanma yazılmadı: sonuç yayınlanmadı


def test_needs_input_keeps_job_accepted(db_pool, publisher):
    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    envelope = run(
        publisher.publish_needs_input(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            unresolved_questions=("Hangi bölümü açıklamamı istersiniz?",),
        )
    )

    parsed = parse_envelope(envelope.model_dump_json(exclude_none=True).encode("utf-8"))
    assert parsed.spec.message_type == "agent.run.needs_input"
    assert parsed.envelope.payload["unresolved_questions"]

    async def _status() -> str:
        return await db_pool.fetchval("SELECT status FROM agent.jobs")

    assert run(_status()) == "accepted"  # needs_input terminal değildir


def test_mode_selected_web_flag_only_for_deep_research(db_pool, publisher):
    run_id, conversation_id, correlation_id = make_run_ids()

    envelope = run(
        publisher.publish_mode_selected(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            selected_mode="fast",
            requires_web_search=False,
            reason="kısa soru; web gerekmez",
        )
    )
    parsed = parse_envelope(envelope.model_dump_json(exclude_none=True).encode("utf-8"))
    assert parsed.spec.message_type == "agent.run.mode_selected"

    with pytest.raises(Exception):  # B1 çapraz kuralı: web yalnız deep_research'te
        run(
            publisher.publish_mode_selected(
                run_id=run_id,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
                selected_mode="analysis",
                requires_web_search=True,
                reason="aykırı kombinasyon",
            )
        )


# --------------------------------------------------- W6 F1: action proposed


def test_action_proposed_publishes_contract_valid_envelope_and_is_not_throttled(db_pool, publisher):
    """W6 F1: A9 öneri olayı agent.action.proposed olarak outbox'a yazılır.

    Bu olay B9 backend proposal kaydının TEK kaynağıdır; seyrekleştirme
    kaydı düşürebileceği için mode_selected gibi önemli geçiş sayılır.
    """
    from messaging.contracts.payloads import AgentActionProposalContent

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    proposal = AgentActionProposalContent(
        run_id=run_id,
        proposal_id="7b9c0000-0000-0000-0000-00000000c0de",
        article_id="1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1",
        article_revision=3,
        base_content_hash="a" * 64,
        summary="İş birliği önerisi — konuk yazı.",
        proposed_content="İş birliği talebi\n\nAmaç: konuk yazı",
        created_at="2026-10-12T09:00:00Z",
    )

    first = run(
        publisher.publish_action_proposed(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            proposal=proposal,
        )
    )
    # Seyrekleştirme YOK: aynı saniyedeki ikinci olay da üretilir (kayıt olayı).
    second = run(
        publisher.publish_action_proposed(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            proposal=proposal,
        )
    )
    assert not isinstance(first, ThrottledProgress)
    assert not isinstance(second, ThrottledProgress)
    assert second.payload["event_sequence"] == first.payload["event_sequence"] + 1

    parsed = parse_envelope(first.model_dump_json(exclude_none=True).encode("utf-8"))
    assert parsed.spec.message_type == "agent.action.proposed"
    assert parsed.envelope.run_id == run_id
    assert parsed.envelope.payload["proposal_id"] == proposal.proposal_id
    assert parsed.envelope.payload["run_id"] == run_id  # zarf run_id ile uyuşar
    assert parsed.envelope.payload["article_revision"] == 3
    assert parsed.envelope.payload["base_content_hash"] == "a" * 64
    assert parsed.envelope.payload["summary"].startswith("İş birliği")


# ------------------------------------------------------------ generation_delta


def test_generation_delta_is_never_throttled_and_contract_valid(db_pool, slow_publisher):
    """Streaming sözleşmesi: parçalı üretim metni SEYREKLEŞTİRİLMEZ.

    ``slow_publisher`` 60s seyrekleştirme penceresiyle kuruludur; art arda
    hızlı ``generation_delta`` yayınlarında hiçbir olay ``ThrottledProgress``
    olmaz (token akışı kalıcı olarak yutulamaz) ve sıra monoton kalır.
    """
    from messaging.events import MAX_GENERATION_DELTA_CHARS
    from agent_core.models import MAX_GENERATION_DELTA_CHARS as DOMAIN_LIMIT

    assert MAX_GENERATION_DELTA_CHARS == DOMAIN_LIMIT  # kopyalar kilit adımında

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    first = run(
        slow_publisher.publish_generation_delta(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            text="Merhaba ",
        )
    )
    second = run(
        slow_publisher.publish_generation_delta(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            text="dünya",
        )
    )

    assert not isinstance(first, ThrottledProgress)
    assert not isinstance(second, ThrottledProgress)
    assert len(first) == 1 and len(second) == 1
    assert second[0].payload["event_sequence"] == first[0].payload["event_sequence"] + 1

    parsed = parse_envelope(first[0].model_dump_json(exclude_none=True).encode("utf-8"))
    assert parsed.spec.message_type == "agent.run.progressed"
    assert parsed.envelope.payload["kind"] == "generation_delta"
    assert parsed.envelope.payload["message"] == "Merhaba "
    assert parsed.envelope.payload["detail"] == {}  # detail bilgi TAŞIMAZ (mevcut progressed davranışı)
    assert len(parsed.envelope.payload["message"]) <= MAX_GENERATION_DELTA_CHARS


def test_generation_delta_splits_chunks_over_carrier_limit(db_pool, slow_publisher):
    """1500 karakteri aşan chunk bölünür: her parça sınırı aşmaz, birleşim eşittir."""

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    text = "x" * 4000  # → 1500 + 1500 + 1000
    envelopes = run(
        slow_publisher.publish_generation_delta(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            text=text,
        )
    )

    assert [len(e.payload["message"]) for e in envelopes] == [1500, 1500, 1000]
    assert "".join(e.payload["message"] for e in envelopes) == text
    assert [e.payload["kind"] for e in envelopes] == ["generation_delta"] * 3
    sequences = [e.payload["event_sequence"] for e in envelopes]
    assert sequences == [1, 2, 3]  # her parça kendi sıra tahsisini alır
    for envelope in envelopes:
        parsed = parse_envelope(envelope.model_dump_json(exclude_none=True).encode("utf-8"))
        assert parsed.spec.message_type == "agent.run.progressed"


def test_generation_delta_empty_text_writes_no_event(db_pool, slow_publisher):
    """Boş metin olay üretmez (``message`` min_length=1 sözleşmesi)."""

    run_id, conversation_id, correlation_id = make_run_ids()
    run(seed_accepted_job(db_pool, run_id, conversation_id, correlation_id))

    envelopes = run(
        slow_publisher.publish_generation_delta(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            text="",
        )
    )
    assert envelopes == []

    async def _count() -> int:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_sequence FROM agent.run_event_sequences WHERE run_id = $1",
                uuid.UUID(run_id),
            )
            return int(row["last_sequence"]) if row is not None else 0

    assert run(_count()) == 0  # sıra tüketilmedi
