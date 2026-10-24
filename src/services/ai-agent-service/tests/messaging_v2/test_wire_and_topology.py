"""K4 offline: run wire sürümüyle zarf kurma, outbox yönlendirmesi, citation dönüşümü, topology.

Broker/DB gerektirmez. Sözleşme kanıtı: kurulan her zarf tüketiciyle aynı
doğrulayıcıdan (``parse_envelope``) geçer ve routing key zarfın kendi sürümündendir.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_core.models import ProfileSnapshotRef, SourceReference
from messaging.contracts import AgentContractError, UnknownMessageSpec, parse_envelope
from messaging.contracts.payloads import AgentSourceReference
from messaging.contracts.payloads_v2 import AgentSourceReferenceV2
from messaging.topology import (
    BACKEND_EVENTS_QUEUE,
    COMMANDS_EXCHANGE,
    CONTENT_QUEUE,
    CONTROL_QUEUE,
    CONTROL_V2_QUEUE,
    DEAD_EXCHANGE,
    EXECUTE_QUEUE,
    EXECUTE_V2_QUEUE,
    build_topology,
    command_routing_keys,
    control_queue_for,
    execute_queue_for,
)
from messaging.wire import (
    WORKER_WIRE_MAX,
    WORKER_WIRE_MAX_SETTING,
    WireVersionMismatch,
    compose_run_envelope,
    normalize_wire_version,
    outbox_route,
    to_transport_citation,
    to_transport_profile_snapshot,
    versioned_payload,
)

from .wire_constants import CONV_ID, CORR_ID, PROFILE_HASH, RUN_ID

SNAPSHOT = ProfileSnapshotRef(profile_id="sample-author", revision=1, content_hash=PROFILE_HASH)


def _profile_citation(section: str = "education", chunk: int = 0) -> SourceReference:
    return SourceReference(
        kind="profile",
        title="Eğitim",
        profile_id=SNAPSHOT.profile_id,
        profile_revision=SNAPSHOT.revision,
        profile_content_hash=SNAPSHOT.content_hash,
        section_id=section,
        chunk_index=chunk,
    )


def _compose(version: int, message_type: str, payload: dict) -> object:
    return compose_run_envelope(
        schema_version=version,
        message_type=message_type,
        run_id=RUN_ID,
        conversation_id=CONV_ID,
        correlation_id=CORR_ID,
        payload=payload,
    )


# --- sürüm sabitleri ---


def test_worker_wire_capability_constants() -> None:
    assert WORKER_WIRE_MAX == 2
    assert WORKER_WIRE_MAX_SETTING == "agent.worker_wire_max"
    assert normalize_wire_version(None) == 1  # eski satır/kayıt = v1
    assert normalize_wire_version(2) == 2
    with pytest.raises(WireVersionMismatch):
        normalize_wire_version(3)


# --- zarf kurma ---


@pytest.mark.parametrize("version", [1, 2])
def test_same_run_message_is_composed_with_run_version(version: int) -> None:
    envelope = _compose(
        version,
        "agent.run.progressed",
        {"event_sequence": 3, "kind": "retrieval_started", "message": "aranıyor", "detail": {}},
    )
    assert envelope.schema_version == version
    assert outbox_route(envelope) == ("blog.agent.events", f"agent.run.progressed.v{version}")
    parsed = parse_envelope(envelope.model_dump_json(exclude_none=True))
    assert parsed.schema_version == version
    assert type(parsed.payload).__name__ == f"AgentRunProgressedV{version}"


def test_versioned_payload_drops_v2_fields_for_v1_run() -> None:
    common = {"event_sequence": 0, "selected_mode": "fast", "requires_web_search": False, "reason": "r"}
    v2 = {"run_intent": "general", "source_scope": "general", "profile_snapshot": None}
    assert versioned_payload(1, common, v2) == common
    assert versioned_payload(2, common, v2) == {**common, "run_intent": "general", "source_scope": "general"}
    v1_envelope = _compose(1, "agent.run.mode_selected", versioned_payload(1, common, v2))
    assert "run_intent" not in v1_envelope.payload  # v1 consumer'ı için kırıcı alan eklenmez
    v2_envelope = _compose(2, "agent.run.mode_selected", versioned_payload(2, common, v2))
    assert v2_envelope.payload["run_intent"] == "general"


def test_v2_mode_selected_requires_intent_and_scope() -> None:
    with pytest.raises(ValueError):
        _compose(2, "agent.run.mode_selected", {"event_sequence": 0, "selected_mode": "fast",
                                                "requires_web_search": False, "reason": "r"})


def test_compose_rejects_type_not_in_version() -> None:
    with pytest.raises(UnknownMessageSpec):
        _compose(2, "content.profile.changed", {})


def test_compose_enforces_consumer_cross_rules_for_profile_completed() -> None:
    """Profile niyetinde snapshot eksikse üretici tarafında da missing_field (tüketiciyle aynı)."""

    citation = to_transport_citation(_profile_citation(), 2)
    payload = {
        "event_sequence": 0,
        "selected_mode": "fast",
        "answer": "Sample Author 2000-2004 yıllarında okudu.",
        "citations": [citation],
        "source_scope": "profile",
        "run_intent": "profile",
        "usage": {"run_id": RUN_ID, "recorded_at": "2026-10-22T10:00:00Z"},
    }
    with pytest.raises(AgentContractError) as excinfo:
        _compose(2, "agent.run.completed", payload)
    assert excinfo.value.category.value == "missing_field"

    payload["profile_snapshot"] = to_transport_profile_snapshot(SNAPSHOT)
    envelope = _compose(2, "agent.run.completed", payload)
    assert outbox_route(envelope)[1] == "agent.run.completed.v2"
    assert envelope.payload["citations"][0]["url"] == "/about#education"


# --- citation dönüşümü ---


def test_v1_citation_keeps_source_id() -> None:
    article = SourceReference(kind="article", article_id="post-1", article_revision=3, chunk_index=2, title="Başlık")
    transport = to_transport_citation(article, 1)
    assert isinstance(transport, AgentSourceReference)
    assert transport.source_id == "article:post-1:3:2"  # önceki dönüşüm düşürüyordu

    web = SourceReference(kind="web", url="https://example.com/a", accessed_at=datetime(2026, 10, 22, tzinfo=timezone.utc))
    web_transport = to_transport_citation(web, 1)
    assert web_transport.accessed_at == "2026-10-22T00:00:00Z"
    assert web_transport.source_id and web_transport.source_id.startswith("web:")


def test_v1_run_cannot_carry_profile_citation() -> None:
    with pytest.raises(WireVersionMismatch):
        to_transport_citation(_profile_citation(), 1)


def test_v2_profile_citation_carries_full_provenance() -> None:
    transport = to_transport_citation(_profile_citation("teaching", 1), 2)
    assert isinstance(transport, AgentSourceReferenceV2)
    assert transport.kind == "profile"
    assert transport.source_id == f"profile:sample-author:1:{PROFILE_HASH}:teaching:1"
    assert transport.url == "/about#teaching"
    assert transport.profile_snapshot.same_as(to_transport_profile_snapshot(SNAPSHOT))


def test_profile_snapshot_transport_accepts_domain_mapping_and_none() -> None:
    assert to_transport_profile_snapshot(None) is None
    from_domain = to_transport_profile_snapshot(SNAPSHOT)
    from_mapping = to_transport_profile_snapshot(
        {"profile_id": "sample-author", "revision": 1, "content_hash": PROFILE_HASH}
    )
    assert from_domain.same_as(from_mapping)


# --- topology (kayıttan türetme) ---


def test_queue_names_per_version() -> None:
    assert execute_queue_for(1) == EXECUTE_QUEUE == "agent.execute.q"
    assert control_queue_for(1) == CONTROL_QUEUE == "agent.control.q"
    assert execute_queue_for(2) == EXECUTE_V2_QUEUE == "agent.execute.v2.q"
    assert control_queue_for(2) == CONTROL_V2_QUEUE == "agent.control.v2.q"


def test_command_routing_keys_are_derived_from_registry() -> None:
    assert command_routing_keys(2, ("agent.execute.requested",)) == ("agent.execute.requested.v2",)
    assert command_routing_keys(2, ("agent.cancel.requested", "agent.resume.requested", "agent.action.result")) == (
        "agent.cancel.requested.v2",
        "agent.resume.requested.v2",
        "agent.action.result.v2",
    )


def test_v1_queues_and_bindings_are_unchanged() -> None:
    topology = build_topology()
    v1_main = {
        (EXECUTE_QUEUE, COMMANDS_EXCHANGE, "agent.execute.requested.v1"),
        (CONTROL_QUEUE, COMMANDS_EXCHANGE, "agent.cancel.requested.v1"),
        (CONTROL_QUEUE, COMMANDS_EXCHANGE, "agent.resume.requested.v1"),
        (CONTROL_QUEUE, COMMANDS_EXCHANGE, "agent.action.result.v1"),
        (CONTENT_QUEUE, "blog.content.events", "content.article.changed.v1"),
        (CONTENT_QUEUE, "blog.content.events", "content.sync.#"),
        (CONTENT_QUEUE, "blog.content.events", "content.profile.changed.v1"),
        (CONTENT_QUEUE, "blog.content.events", "content.project.changed.v1"),
        (BACKEND_EVENTS_QUEUE, "blog.agent.events", "agent.run.#"),
        (BACKEND_EVENTS_QUEUE, "blog.agent.events", "agent.action.#"),
    }
    assert v1_main <= set(topology.bindings)
    # v1 kuyruklarına v2 routing key bağlanmaz (eski worker v2 komutu görmez).
    for queue, _exchange, rk in topology.bindings:
        if queue in (EXECUTE_QUEUE, CONTROL_QUEUE) or queue.startswith((EXECUTE_QUEUE + ".", CONTROL_QUEUE + ".")):
            assert not rk.endswith(".v2"), (queue, rk)


def test_v2_queues_have_bindings_dlq_and_retry_tiers_like_v1() -> None:
    topology = build_topology(retry_tier_seconds=(10, 30))
    specs = {spec.name: spec for spec in topology.queues}
    for queue, rks in (
        (EXECUTE_V2_QUEUE, ("agent.execute.requested.v2",)),
        (CONTROL_V2_QUEUE, ("agent.cancel.requested.v2", "agent.resume.requested.v2", "agent.action.result.v2")),
    ):
        assert specs[queue].arguments == {"x-dead-letter-exchange": DEAD_EXCHANGE}
        assert f"{queue}.dlq" in specs
        for rk in rks:
            assert (queue, COMMANDS_EXCHANGE, rk) in topology.bindings
            assert (f"{queue}.dlq", DEAD_EXCHANGE, rk) in topology.bindings
        for tier in (10, 30):
            tier_queue = f"{queue}.retry.{tier}s.q"
            assert specs[tier_queue].arguments == {
                "x-message-ttl": tier * 1000,
                "x-dead-letter-exchange": COMMANDS_EXCHANGE,
            }
            for rk in rks:
                assert (tier_queue, f"blog.agent.retry.{tier}s", rk) in topology.bindings
    # Backend olay kuyruğu joker binding'leri v2 olaylarını da kapsar.
    assert (BACKEND_EVENTS_QUEUE, "blog.agent.events", "agent.run.#") in topology.bindings


def test_v1_main_queue_order_is_preserved() -> None:
    names = build_topology().queue_names
    assert names[:8] == (
        "agent.execute.q",
        "agent.execute.q.dlq",
        "agent.control.q",
        "agent.control.q.dlq",
        "agent.content.q",
        "agent.content.q.dlq",
        "backend.agent.events.q",
        "backend.agent.events.q.dlq",
    )
