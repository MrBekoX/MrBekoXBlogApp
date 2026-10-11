"""B1 kural uygulaması: registry ↔ contract.json denkliği, AMQP header tutarlılığı,
monoton event_sequence, null/ek-alan reddi ve A1 iş modelleriyle eşlenebilirlik
(B0 kabul ölçütü 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_paths import CONTRACT, read_fixture
from messaging.contracts import (
    AgentExecutionRequestedV1,
    AgentRunProgressedV1,
    AgentContractError,
    AgentErrorCode as TransportErrorCode,
    AgentMode as TransportAgentMode,
    EventSequenceTracker,
    MAX_PAYLOAD_BYTES,
    MESSAGE_TYPE_REGISTRY,
    ModePreference as TransportModePreference,
    Producer,
    ProgressKind as TransportProgressKind,
    SCHEMA_VERSION,
    SequenceRegression,
    SourceScope as TransportSourceScope,
    parse_envelope,
    to_amqp_properties,
)

RUN_ID = "aaaaaaa1-0000-4000-8000-000000000001"
CONV_ID = "bbbbbbb1-0000-4000-8000-000000000002"
CORR_ID = "ccccccc1-0000-4000-8000-000000000003"


def test_registry_matches_contract_json() -> None:
    assert CONTRACT["version"] == SCHEMA_VERSION
    assert CONTRACT["max_payload_bytes"] == MAX_PAYLOAD_BYTES
    assert CONTRACT["content_type"] == "application/json"
    assert set(CONTRACT["message_types"]) == set(MESSAGE_TYPE_REGISTRY)

    for name, spec in MESSAGE_TYPE_REGISTRY.items():
        entry = CONTRACT["message_types"][name]
        assert entry["direction"] == spec.direction.value, name
        assert entry["exchange"] == spec.exchange, name
        assert entry["routing_key"] == spec.routing_key, name
        assert entry["payload_schema"] == spec.payload_schema, name
        assert entry["requires_run_identity"] == spec.requires_run_identity, name
        assert entry["requires_deadline"] == spec.requires_deadline, name
        assert tuple(entry["allowed_producers"]) == tuple(p.value for p in spec.allowed_producers), name

    contract_producers = tuple(CONTRACT["producers"])
    assert contract_producers == tuple(p.value for p in Producer)


def test_routing_key_is_message_type_with_version_suffix() -> None:
    for name, spec in MESSAGE_TYPE_REGISTRY.items():
        assert spec.routing_key == f"{name}.v1", name


def test_exchange_assignment_follows_plan() -> None:
    commands = {"blog.agent.commands"}
    events = {"blog.agent.events"}
    content = {"blog.content.events"}
    for name, spec in MESSAGE_TYPE_REGISTRY.items():
        if name.startswith("agent.run.") or name == "agent.action.proposed":
            assert spec.exchange in events, name
        elif name.startswith("content."):
            assert spec.exchange in content, name
        else:
            assert spec.exchange in commands, name


def test_amqp_properties_are_consistent_with_envelope() -> None:
    envelope = parse_envelope(read_fixture("valid/agent.run.progressed.json")).envelope

    properties = to_amqp_properties(envelope)

    assert properties == {
        "message_id": envelope.message_id,
        "correlation_id": envelope.correlation_id,
        "content_type": "application/json",
        "type": "agent.run.progressed",
    }


def test_event_sequence_tracker_rejects_equal_and_lower_sequence() -> None:
    tracker = EventSequenceTracker()

    tracker.accept(RUN_ID, 1)
    tracker.accept(RUN_ID, 5)
    with pytest.raises(SequenceRegression):
        tracker.accept(RUN_ID, 5)
    with pytest.raises(SequenceRegression):
        tracker.accept(RUN_ID, 4)
    tracker.accept(RUN_ID, 6)


def test_event_sequence_tracker_tracks_runs_independently() -> None:
    tracker = EventSequenceTracker()

    tracker.accept(RUN_ID, 3)
    tracker.accept(CONV_ID, 1)
    assert tracker._last_by_run == {RUN_ID: 3, CONV_ID: 1}


def test_explicit_null_field_is_rejected() -> None:
    raw = json.dumps(
        {
            "message_id": "77777777-7777-4777-8777-777777777777",
            "message_type": "agent.cancel.requested",
            "schema_version": 1,
            "correlation_id": CORR_ID,
            "occurred_at": "2026-10-11T09:00:00Z",
            "producer": "backend-net",
            "deadline_at": None,
            "payload": {},
        }
    )

    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == "wrong_type"


def test_unknown_payload_field_is_rejected() -> None:
    raw = json.dumps(
        {
            "message_id": "77777777-7777-4777-8777-777777777777",
            "message_type": "agent.cancel.requested",
            "schema_version": 1,
            "run_id": RUN_ID,
            "conversation_id": CONV_ID,
            "correlation_id": CORR_ID,
            "occurred_at": "2026-10-11T09:00:00Z",
            "producer": "backend-net",
            "payload": {"secret_claim": "x"},
        }
    )

    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == "extra_field"


def test_user_ref_is_carried_opaquely() -> None:
    """user_ref yetki kanıtı değildir: değeri değiştirmek sözleşme geçerliliğini etkilemez;
    yetkilendirme backend run sahipliğinde ayrı kararştır (plan satır 198)."""

    base = json.loads(read_fixture("valid/agent.execute.requested.json"))
    base["payload"]["user_ref"] = "baskin-bir-kimlik"
    parsed = parse_envelope(json.dumps(base))

    assert isinstance(parsed.payload, AgentExecutionRequestedV1)
    assert parsed.payload.user_ref == "baskin-bir-kimlik"


def test_contracts_package_does_not_use_pickle() -> None:
    """Gövde yalnız JSON olarak çözümlenir; pickle/keyfi nesne deserialization yoktur (plan satır 239)."""

    import re

    import messaging.contracts as contracts_package

    usage_pattern = re.compile(r"import\s+pickle|pickle\.loads?\s*\(|cPickle|cloudpickle")
    package_dir = Path(contracts_package.__path__[0])
    for path in sorted(package_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert usage_pattern.search(source) is None, f"{path.name} pickle kullanmamalıdır"


# --- A1 iş modelleriyle eşlenebilirlik (B0 kabul ölçütü 3) ---


def test_execution_context_fields_map_to_payload_and_envelope() -> None:
    from agent_core.models.context import ExecutionContext

    ec_fields = set(ExecutionContext.model_fields) - {"article_snapshot"}
    payload_fields = set(AgentExecutionRequestedV1.model_fields)
    envelope_identity = {"run_id", "conversation_id"}

    assert ec_fields <= payload_fields | envelope_identity, (
        f"eşleşmeyen ExecutionContext alanları: {sorted(ec_fields - payload_fields - envelope_identity)}"
    )


def test_usage_and_proposal_field_sets_match_a1_models() -> None:
    from agent_core.models.action import ActionProposal
    from agent_core.models.usage import UsageRecord
    from messaging.contracts import payloads as transport

    assert set(UsageRecord.model_fields) == set(transport.AgentUsageRecord.model_fields)
    assert set(ActionProposal.model_fields) == set(transport.AgentActionProposalContent.model_fields)


def test_domain_progress_fields_map_to_progressed_payload_and_envelope() -> None:
    from agent_core.models.progress import DomainProgress

    envelope_carried = {"run_id", "occurred_at"}
    payload_fields = set(AgentRunProgressedV1.model_fields)

    assert set(DomainProgress.model_fields) - envelope_carried <= payload_fields


def test_run_status_maps_onto_five_terminal_events() -> None:
    from agent_core.models.enums import RunStatus

    status_to_event = {
        RunStatus.COMPLETED: "agent.run.completed",
        RunStatus.PARTIAL: "agent.run.partially_completed",
        RunStatus.NEEDS_INPUT: "agent.run.needs_input",
        RunStatus.CANCELLED: "agent.run.cancelled",
        RunStatus.FAILED: "agent.run.failed",
    }

    assert set(status_to_event.values()) <= set(MESSAGE_TYPE_REGISTRY)
    assert len(status_to_event) == len(RunStatus)


def test_a1_enum_values_match_transport_enums() -> None:
    from agent_core.errors import AgentErrorCode as A1ErrorCode
    from agent_core.models.enums import (
        AgentMode as A1AgentMode,
        ModePreference as A1ModePreference,
        ProgressKind as A1ProgressKind,
        SourceScope as A1SourceScope,
    )

    assert {m.value for m in A1AgentMode} == {m.value for m in TransportAgentMode}
    assert {m.value for m in A1ModePreference} == {m.value for m in TransportModePreference}
    assert {s.value for s in A1SourceScope} == {s.value for s in TransportSourceScope}
    assert {k.value for k in A1ProgressKind} == {k.value for k in TransportProgressKind}
    assert {e.value for e in A1ErrorCode} == {e.value for e in TransportErrorCode}
