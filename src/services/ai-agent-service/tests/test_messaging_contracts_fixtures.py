"""Ortak fixture setinin (src/contracts/agent/fixtures) Python transport katmanı üzerinden akışı.

Aynı manifest .NET ``AgentContractFixtureTests`` tarafından da okunur: her iki dil aynı
girdiler için aynı beklentiyi (valid / kategori) üretmek zorundadır. JSON Schema
dosyalarına karşı doğrulama, tek sözleşme kaynağının gerçekten bu dosyalar olduğunu kanıtlar.
"""

from __future__ import annotations

import json

import jsonschema
import pytest
from referencing import Registry, Resource

from contract_paths import CONTRACT, ENVELOPE_SCHEMA, MANIFEST, V1_DIR, read_fixture, read_payload_schema
from messaging.contracts import (
    AgentContractError,
    AgentExecutionRequestedV1,
    MESSAGE_TYPE_REGISTRY,
    parse_envelope,
)


def json_schema_registry() -> Registry:
    resources = []
    for path in (V1_DIR / "payloads").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    for name in ("common.schema.json", "envelope.schema.json"):
        schema = json.loads((V1_DIR / name).read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def case_ids(case: dict) -> str:
    return case["file"]


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=case_ids)
def test_fixture_matches_validator_expectation(case: dict) -> None:
    raw = read_fixture(case["file"])

    if case["expect"] == "valid":
        parsed = parse_envelope(raw)
        assert parsed.envelope.message_type == case["message_type"]
        return

    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.category.value == case["reason"], str(excinfo.value)


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=case_ids)
def test_fixture_matches_json_schema_expectation(case: dict) -> None:
    schema_expect = case.get("schema_expect", "pass")
    if schema_expect == "skip":
        pytest.skip("gövde JSON metni bozuk; şema kontrolü uygulanmaz")

    instance = json.loads(read_fixture(case["file"]))

    envelope_ok = True
    try:
        jsonschema.Draft202012Validator(ENVELOPE_SCHEMA, registry=json_schema_registry()).validate(instance)
    except jsonschema.ValidationError:
        envelope_ok = False

    payload_ok = True
    spec = MESSAGE_TYPE_REGISTRY.get(instance.get("message_type"))
    if spec is not None:
        payload_schema = read_payload_schema(spec.payload_schema)
        try:
            jsonschema.Draft202012Validator(payload_schema, registry=json_schema_registry()).validate(
                instance["payload"]
            )
        except jsonschema.ValidationError:
            payload_ok = False

    schema_passes = envelope_ok and payload_ok
    if case["expect"] == "valid":
        assert schema_passes, "geçerli fixture şemalara uymalıdır"
    elif schema_expect == "pass":
        # Yön/üretici uyumu, run kimliği ve deadline zorunluluğu şema değil doğrulayıcı kuralıdır.
        assert schema_passes, f"{case['file']} şemadan geçebilmeliydi"
    else:
        assert not schema_passes, f"{case['file']} şemada reddedilmeliydi"


def test_every_message_type_has_valid_fixture() -> None:
    covered = {c["message_type"] for c in MANIFEST["cases"] if c["expect"] == "valid"}
    assert set(MESSAGE_TYPE_REGISTRY) <= covered


def test_registry_covers_contract_message_types() -> None:
    contract_types = set(CONTRACT["message_types"])
    assert contract_types == set(MESSAGE_TYPE_REGISTRY)


def test_size_gate_uses_configured_limit_before_parsing() -> None:
    raw = read_fixture("valid/agent.execute.requested.json")
    with pytest.raises(AgentContractError) as excinfo:
        parse_envelope(raw, max_payload_bytes=32)
    assert excinfo.value.category.value == "oversized"


def test_oversized_fixture_exceeds_contract_limit() -> None:
    raw = read_fixture("invalid/oversized_payload.json")
    assert len(raw.encode("utf-8")) > 262_144


def test_parse_materializes_typed_payload() -> None:
    raw = read_fixture("valid/agent.execute.requested.with_article.json")
    parsed = parse_envelope(raw)
    assert isinstance(parsed.payload, AgentExecutionRequestedV1)
    assert parsed.payload.article_id == "my-blog-post"
    assert parsed.payload.article_revision == 7
    assert parsed.payload.mode_preference.value == "analysis"
    assert parsed.envelope.deadline_at == "2026-10-11T09:06:00Z"


def test_parse_accepts_bytes_input() -> None:
    raw = read_fixture("valid/agent.cancel.requested.json")
    parsed_str = parse_envelope(raw)
    parsed_bytes = parse_envelope(raw.encode("utf-8"))
    assert parsed_bytes.envelope.message_id == parsed_str.envelope.message_id


def test_parse_rejects_non_text_input() -> None:
    with pytest.raises(TypeError):
        parse_envelope({"payload": {}})  # type: ignore[arg-type]
