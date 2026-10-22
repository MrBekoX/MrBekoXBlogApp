"""v2 ortak fixture seti (src/contracts/agent/fixtures/v2) — doğrulayıcı + JSON Schema.

Aynı manifest .NET tarafındaki v2 fixture testleri tarafından da okunur: iki dil
aynı girdi için aynı beklentiyi (valid / kategori) üretmek zorundadır.
``schema_expect=skip`` vakaları JSON Schema'nın ifade edemediği çapraz kurallardır
(profile source_id/url eşliği, citation ↔ profile_snapshot bağı, v2'de olmayan
``content.*`` türleri) ve YALNIZ doğrulayıcıda uygulanır — bu yüzden doğrulayıcı
beklentisi her vaka için zorunludur.
"""

from __future__ import annotations

import json

import jsonschema
import pytest
from referencing import Registry, Resource

from contract_paths import (
    V2_CONTRACT,
    V2_DIR,
    V2_ENVELOPE_SCHEMA,
    V2_MANIFEST,
    read_v2_fixture,
    read_v2_payload_schema,
)
from messaging.contracts import (
    AgentContractError,
    AgentExecutionRequestedV2,
    AgentRunCompletedV2,
    AgentRunModeSelectedV2,
    MESSAGE_TYPE_REGISTRY_V2,
    WIRE_VERSION_V2,
    parse_envelope,
)


def json_schema_registry() -> Registry:
    resources = []
    for path in (V2_DIR / "payloads").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    for name in ("common.schema.json", "envelope.schema.json"):
        schema = json.loads((V2_DIR / name).read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def case_ids(case: dict) -> str:
    return case["file"]


@pytest.mark.parametrize("case", V2_MANIFEST["cases"], ids=case_ids)
def test_v2_fixture_matches_validator_expectation(case: dict) -> None:
    raw = read_v2_fixture(case["file"])

    if case["expect"] == "valid":
        parsed = parse_envelope(raw)
        assert parsed.envelope.message_type == case["message_type"]
        assert parsed.schema_version == WIRE_VERSION_V2
        assert parsed.spec.schema_version == WIRE_VERSION_V2
        assert parsed.spec.routing_key.endswith(".v2")
        return

    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == case["reason"], str(excinfo.value)


@pytest.mark.parametrize("case", V2_MANIFEST["cases"], ids=case_ids)
def test_v2_fixture_matches_json_schema_expectation(case: dict) -> None:
    schema_expect = case.get("schema_expect", "pass")
    if schema_expect == "skip":
        pytest.skip("çapraz kural yalnız doğrulayıcıda uygulanır (manifest schema_expect=skip)")

    instance = json.loads(read_v2_fixture(case["file"]))
    registry = json_schema_registry()

    envelope_ok = True
    try:
        jsonschema.Draft202012Validator(V2_ENVELOPE_SCHEMA, registry=registry).validate(instance)
    except jsonschema.ValidationError:
        envelope_ok = False

    payload_ok = True
    entry = V2_CONTRACT["message_types"].get(instance.get("message_type"))
    if entry is not None:
        payload_schema = read_v2_payload_schema(entry["payload_schema"])
        try:
            jsonschema.Draft202012Validator(payload_schema, registry=registry).validate(instance["payload"])
        except jsonschema.ValidationError:
            payload_ok = False

    schema_passes = envelope_ok and payload_ok
    if case["expect"] == "valid":
        assert schema_passes, "geçerli fixture v2 şemalarına uymalıdır"
    elif schema_expect == "pass":
        assert schema_passes, f"{case['file']} şemadan geçebilmeliydi"
    else:
        assert not schema_passes, f"{case['file']} v2 şemasında reddedilmeliydi"


def test_every_v2_message_type_has_valid_fixture() -> None:
    covered = {c["message_type"] for c in V2_MANIFEST["cases"] if c["expect"] == "valid"}
    assert set(MESSAGE_TYPE_REGISTRY_V2) <= covered


def test_v2_manifest_declares_contract_version() -> None:
    assert V2_MANIFEST["contract_version"] == WIRE_VERSION_V2


def test_skip_cases_are_cross_rules_enforced_by_validator() -> None:
    """schema_expect=skip vakaları şemada geçse bile doğrulayıcı tarafından reddedilir."""

    skipped = [c for c in V2_MANIFEST["cases"] if c.get("schema_expect") == "skip"]
    assert skipped, "v2 manifest çapraz kural vakaları içermeli"
    for case in skipped:
        assert case["expect"] == "invalid"
        with pytest.raises(AgentContractError) as excinfo:
            parse_envelope(read_v2_fixture(case["file"]))
        assert excinfo.value.category.value == case["reason"], case["file"]


def test_v2_parse_materializes_typed_payloads() -> None:
    who = parse_envelope(read_v2_fixture("valid/agent.execute.requested.who_am_i.json"))
    assert isinstance(who.payload, AgentExecutionRequestedV2)
    assert who.payload.conversation_topic.value == "who_am_i"
    assert who.payload.profile_snapshot is not None
    assert who.payload.article_id is None and who.payload.selected_text is None

    mode = parse_envelope(read_v2_fixture("valid/agent.run.mode_selected.profile.json"))
    assert isinstance(mode.payload, AgentRunModeSelectedV2)
    assert mode.payload.run_intent.value == "profile"
    assert mode.payload.requires_web_search is False

    completed = parse_envelope(read_v2_fixture("valid/agent.run.completed.profile.json"))
    assert isinstance(completed.payload, AgentRunCompletedV2)
    citation = completed.payload.citations[0]
    assert citation.kind == "profile"
    assert citation.url == f"/about#{citation.section_id}"
    assert completed.payload.profile_snapshot.same_as(citation.profile_snapshot)
