"""B1 kural uygulaması: registry ↔ contract.json denkliği (sürüm başına), AMQP header
tutarlılığı, monoton event_sequence, null/ek-alan reddi, A1 iş modelleriyle
eşlenebilirlik (B0 kabul ölçütü 3) ve v1/v2 sürüm ayrımı (karar kaydı K3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_paths import CONTRACT, CONTRACTS_BY_VERSION, V2_DIR, read_fixture, read_v2_fixture
from messaging.contracts import (
    AgentActionProposedV1,
    AgentExecutionRequestedV1,
    AgentExecutionRequestedV2,
    ConversationTopic as TransportConversationTopic,
    MESSAGE_TYPE_REGISTRIES,
    MESSAGE_TYPE_REGISTRY_V1,
    MESSAGE_TYPE_REGISTRY_V2,
    RunIntent as TransportRunIntent,
    SUPPORTED_SCHEMA_VERSIONS,
    UnknownMessageSpec,
    lookup_spec,
    registry_for,
    spec_for,
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
    """v1 (donmuş) kayıt ↔ v1/contract.json; geriye dönük takma adlar v1'i gösterir."""

    assert CONTRACT["version"] == SCHEMA_VERSION == 1
    assert MESSAGE_TYPE_REGISTRY is MESSAGE_TYPE_REGISTRY_V1
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


@pytest.mark.parametrize("version", sorted(CONTRACTS_BY_VERSION))
def test_registry_matches_contract_json_per_version(version: int) -> None:
    """Her sürümün kaydı kendi contract.json'una birebir eşittir (K3: sürüm + tür anahtarı)."""

    contract = CONTRACTS_BY_VERSION[version]
    registry = registry_for(version)
    exchange_names = {value: key for key, value in contract["exchanges"].items()}
    assert contract["version"] == version
    assert contract["max_payload_bytes"] == MAX_PAYLOAD_BYTES
    assert contract["content_type"] == "application/json"
    assert tuple(contract["producers"]) == tuple(p.value for p in Producer)
    assert set(contract["message_types"]) == set(registry)

    for name, spec in registry.items():
        entry = contract["message_types"][name]
        assert spec.schema_version == version, name
        assert spec.message_type == name
        assert spec.exchange in exchange_names, name
        assert entry["direction"] == spec.direction.value, name
        assert entry["exchange"] == spec.exchange, name
        assert entry["routing_key"] == spec.routing_key, name
        assert entry["payload_schema"] == spec.payload_schema, name
        assert entry["requires_run_identity"] == spec.requires_run_identity, name
        assert entry["requires_deadline"] == spec.requires_deadline, name
        assert tuple(entry["allowed_producers"]) == tuple(p.value for p in spec.allowed_producers), name
        assert (CONTRACT_DIR_FOR[version] / spec.payload_schema).is_file(), name


CONTRACT_DIR_FOR = {1: V2_DIR.parent / "v1", 2: V2_DIR}


def test_supported_versions_cover_all_contract_directories() -> None:
    assert SUPPORTED_SCHEMA_VERSIONS == (1, 2)
    assert set(MESSAGE_TYPE_REGISTRIES) == set(SUPPORTED_SCHEMA_VERSIONS) == set(CONTRACTS_BY_VERSION)


@pytest.mark.parametrize("version", sorted(CONTRACTS_BY_VERSION))
def test_routing_key_is_message_type_with_version_suffix(version: int) -> None:
    for name, spec in registry_for(version).items():
        assert spec.routing_key == f"{name}.v{version}", name


def test_v2_registry_is_run_scoped_subset_with_v2_models() -> None:
    """v2 = v1'in run kapsamlı 13 türü; content.* yalnız v1; v1 modelleri donmuş kalır."""

    run_scoped = {name for name, spec in MESSAGE_TYPE_REGISTRY_V1.items() if spec.requires_run_identity}
    assert set(MESSAGE_TYPE_REGISTRY_V2) == run_scoped
    assert len(MESSAGE_TYPE_REGISTRY_V2) == 13
    assert not any(name.startswith("content.") for name in MESSAGE_TYPE_REGISTRY_V2)
    for name, spec in MESSAGE_TYPE_REGISTRY_V2.items():
        v1 = MESSAGE_TYPE_REGISTRY_V1[name]
        assert spec.payload_model.__name__.endswith("V2"), name
        assert v1.payload_model.__name__.endswith("V1"), name
        assert issubclass(spec.payload_model, v1.payload_model), name  # v2 ⊇ v1 alanları
        assert (spec.direction, spec.exchange, spec.allowed_producers) == (
            v1.direction,
            v1.exchange,
            v1.allowed_producers,
        ), name


def test_spec_lookup_is_version_keyed() -> None:
    assert spec_for(1, "agent.run.completed").routing_key == "agent.run.completed.v1"
    assert spec_for(2, "agent.run.completed").routing_key == "agent.run.completed.v2"
    assert lookup_spec(2, "content.profile.changed") is None
    assert lookup_spec(3, "agent.run.completed") is None
    with pytest.raises(UnknownMessageSpec):
        spec_for(2, "content.sync.batch")
    with pytest.raises(UnknownMessageSpec):
        registry_for(99)


def test_exchange_assignment_follows_plan() -> None:
    commands = {"blog.agent.commands"}
    events = {"blog.agent.events"}
    content = {"blog.content.events"}
    for registry in MESSAGE_TYPE_REGISTRIES.values():
        for name, spec in registry.items():
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
    """EC alanları ⊆ v2 execute payload ∪ run kimliği (v2 konu/snapshot alanları dahil).

    ``article_snapshot`` gövdedir (K7: taşınmaz); v1 payload'ı v2'nin alt kümesidir
    ve v1 run'larında ``conversation_topic``/``profile_snapshot`` None kalır.
    """

    from agent_core.models.context import ExecutionContext

    ec_fields = set(ExecutionContext.model_fields) - {"article_snapshot"}
    payload_fields = set(AgentExecutionRequestedV2.model_fields)
    envelope_identity = {"run_id", "conversation_id"}

    assert ec_fields <= payload_fields | envelope_identity, (
        f"eşleşmeyen ExecutionContext alanları: {sorted(ec_fields - payload_fields - envelope_identity)}"
    )
    v1_fields = set(AgentExecutionRequestedV1.model_fields)
    assert v1_fields < payload_fields
    assert payload_fields - v1_fields == {"conversation_topic", "profile_snapshot"}


def test_profile_snapshot_and_source_fields_match_a1_models() -> None:
    from agent_core.models.profile import ProfileSnapshotRef
    from agent_core.models.sources import SourceReference
    from messaging.contracts import AgentProfileSnapshotRef, AgentSourceReferenceV2

    assert set(ProfileSnapshotRef.model_fields) == set(AgentProfileSnapshotRef.model_fields)
    assert set(SourceReference.model_fields) == set(AgentSourceReferenceV2.model_fields)


def test_usage_and_proposal_field_sets_match_a1_models() -> None:
    from agent_core.models.action import ActionProposal
    from agent_core.models.usage import UsageRecord
    from messaging.contracts import payloads as transport

    assert set(UsageRecord.model_fields) == set(transport.AgentUsageRecord.model_fields)
    assert set(ActionProposal.model_fields) == set(transport.AgentActionProposalContent.model_fields)


def test_domain_progress_fields_map_to_progressed_payload_and_envelope() -> None:
    # W6 F1 güncellemesi: DomainProgress alanları İKİ olaya dağılır — genel
    # ilerleme alanları agent.run.progressed'e; ``proposal`` TAŞIYICISI ise
    # ACTION_PROPOSED'ta sözleşmenin agent.action.proposed payload'ının TAMAMINI
    # besler (payload alan kümesi ActionProposal alanlarını + zarf kimliğini
    # kapsar; altta AgentActionProposedV1 ile sabitlenir). Bütünlük kuralı:
    # ölü alan yok, uydurma alan yok.
    from agent_core.models.progress import DomainProgress

    envelope_carried = {"run_id", "occurred_at"}
    progressed_fields = set(AgentRunProgressedV1.model_fields)
    proposal_carrier = {"proposal"}
    proposed_payload_fields = set(AgentActionProposedV1.model_fields)

    # 1) proposal taşıyıcısı dışındaki her alan progressed payload'ında taşınır.
    assert set(DomainProgress.model_fields) - envelope_carried - proposal_carrier <= progressed_fields
    # 2) taşıyıcı öneri, agent.action.proposed payload alanlarını BÜTÜNÜYLE doldurur
    #    (run_id + proposal alanları + olay sırası alanları).
    assert proposed_payload_fields - {"run_id"} - set(AgentRunProgressedV1.model_fields) != set()


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


def test_v2_enum_values_match_domain_enums() -> None:
    from agent_core.models.enums import ConversationTopic as A1ConversationTopic, RunIntent as A1RunIntent

    assert [t.value for t in A1ConversationTopic] == [t.value for t in TransportConversationTopic]
    assert [i.value for i in A1RunIntent] == [i.value for i in TransportRunIntent]


def test_v2_enum_values_match_common_schema() -> None:
    common = json.loads((V2_DIR / "common.schema.json").read_text(encoding="utf-8"))["$defs"]
    assert common["conversation_topic"]["enum"] == [t.value for t in TransportConversationTopic]
    assert common["run_intent"]["enum"] == [i.value for i in TransportRunIntent]


# --- Sürüm ayrımı: negatif vakalar (K3) ---


def _with_version(raw: str, version: int) -> str:
    document = json.loads(raw)
    document["schema_version"] = version
    return json.dumps(document, ensure_ascii=False)


@pytest.mark.parametrize("version", [0, 3, 99])
def test_unknown_versions_are_rejected_as_unknown_version(version: int) -> None:
    raw = _with_version(read_v2_fixture("valid/agent.execute.requested.who_am_i.json"), version)
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == "unknown_version"


def test_v2_payload_under_v1_header_is_rejected() -> None:
    """v2 alanı taşıyan gövde v1 zarfıyla gelirse v1 DTO'su ek alanı reddeder (geri yorum yok)."""

    raw = _with_version(read_v2_fixture("valid/agent.execute.requested.who_am_i.json"), 1)
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == "extra_field"


def test_v2_profile_completed_under_v1_header_is_rejected() -> None:
    """Profile kaynağı v1'e daraltılamaz: v1 zarfında profile citation/run_intent reddedilir."""

    raw = _with_version(read_v2_fixture("valid/agent.run.completed.profile.json"), 1)
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value in {"extra_field", "wrong_type"}


def test_v1_payload_under_v2_header_missing_topic_is_rejected() -> None:
    raw = _with_version(read_fixture("valid/agent.execute.requested.json"), 2)
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == "missing_field"
    assert excinfo.value.field == "payload.conversation_topic"


@pytest.mark.parametrize(
    "fixture",
    [
        "valid/content.article.changed.json",
        "valid/content.sync.batch.json",
        "valid/content.profile.changed.json",
    ],
)
def test_content_types_under_v2_header_are_unknown_type(fixture: str) -> None:
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(_with_version(read_fixture(fixture), 2))
    assert excinfo.value.category.value == "unknown_type"


def test_v1_backlog_message_keeps_v1_dto() -> None:
    """v1 backlog/arşiv mesajı v1 DTO'suyla çözülür; v2 kuralları uygulanmaz."""

    parsed = parse_envelope(read_fixture("valid/agent.run.completed.json"))
    assert parsed.schema_version == 1
    assert type(parsed.payload).__name__ == "AgentRunCompletedV1"
    assert parsed.spec.routing_key == "agent.run.completed.v1"


def test_v2_auto_execute_may_carry_article_and_snapshot() -> None:
    """AUTO konusu makale bağlamını ve kabulde pinlenen snapshot'ı birlikte taşıyabilir."""

    base = json.loads(read_v2_fixture("valid/agent.execute.requested.auto_with_profile_snapshot.json"))
    article = json.loads(read_v2_fixture("valid/agent.execute.requested.with_article.json"))["payload"]
    for key in ("article_id", "article_revision", "article_content_hash"):
        base["payload"][key] = article[key]
    parsed = parse_envelope(json.dumps(base, ensure_ascii=False))
    assert parsed.payload.conversation_topic.value == "auto"
    assert parsed.payload.article_id == article["article_id"]


def test_profile_citation_without_payload_snapshot_is_bad_format() -> None:
    """Profil dışı niyette bile profile kaynağı pinlenmiş snapshot'sız taşınamaz."""

    document = json.loads(read_v2_fixture("valid/agent.run.completed.profile.json"))
    document["payload"]["run_intent"] = "general"
    document["payload"].pop("profile_snapshot")
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(json.dumps(document, ensure_ascii=False))
    assert excinfo.value.category.value == "bad_format"


def test_profile_mode_selected_without_snapshot_is_missing_field() -> None:
    document = json.loads(read_v2_fixture("valid/agent.run.mode_selected.profile.json"))
    document["payload"].pop("profile_snapshot")
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(json.dumps(document, ensure_ascii=False))
    assert excinfo.value.category.value == "missing_field"
    assert excinfo.value.field == "payload.profile_snapshot"
