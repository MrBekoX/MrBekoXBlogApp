"""Tek seferlik uretici: v1 run mesaj sozlesmesinden v2'yi turetir (provenance).

v1 dondurulmus kalir. v2 yalniz run kapsamli 13 mesaj turunu tasir; content.*
turleri v1'de kalir (icerik senkronu run surumunden bagimsizdir).

v2 farklari (D015 genisletmesi, karar kaydi: src/contracts/agent/README.md "v2"):
- envelope.schema_version = 2; routing key'ler ``.v2`` sonekli.
- common: conversation_topic, run_intent, profile_snapshot_ref; source_reference
  kind=profile (profile_id/profile_revision/profile_content_hash/section_id/
  chunk_index/url=/about#section).
- agent.execute.requested: conversation_topic (zorunlu), profile_snapshot;
  who_am_i ise profile_snapshot zorunlu ve makale/selected_text alanlari yasak.
- agent.run.mode_selected: run_intent + source_scope (zorunlu), profile_snapshot;
  run_intent=profile ise profile kapsami, web yok, snapshot zorunlu.
- agent.run.completed / partially_completed: run_intent (zorunlu),
  profile_snapshot; run_intent=profile ise snapshot zorunlu, source_scope=profile,
  citation'lar yalniz profile turunde.
- agent.run.failed: run_intent ve profile_snapshot opsiyonel.

Kullanim: python src/contracts/agent/_generate_v2.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V1 = ROOT / "v1"
V2 = ROOT / "v2"

RUN_TYPES = [
    "agent.execute.requested",
    "agent.cancel.requested",
    "agent.resume.requested",
    "agent.action.result",
    "agent.run.accepted",
    "agent.run.mode_selected",
    "agent.run.progressed",
    "agent.run.needs_input",
    "agent.run.completed",
    "agent.run.partially_completed",
    "agent.run.failed",
    "agent.run.cancelled",
    "agent.action.proposed",
]

COMMON = "urn:blog-agent:v2:common#/$defs/"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _retarget(node):
    """v1 URN/baslik referanslarini v2'ye cevirir."""
    if isinstance(node, dict):
        return {k: _retarget(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_retarget(v) for v in node]
    if isinstance(node, str):
        return node.replace("urn:blog-agent:v1:", "urn:blog-agent:v2:")
    return node


def _title(schema: dict) -> None:
    if schema.get("title", "").endswith("V1"):
        schema["title"] = schema["title"][:-2] + "V2"


def build_contract() -> dict:
    contract = _load(V1 / "contract.json")
    contract["version"] = 2
    contract["description"] = (
        "v2 run mesaj sozlesmesi: v1'in run kapsamli 13 turu + konu (conversation_topic), "
        "etkin niyet (run_intent), profil snapshot referansi ve profile kaynak turu. "
        "content.* turleri v1'de kalir. Uretici: _generate_v2.py."
    )
    contract["message_types"] = {
        name: {**entry, "routing_key": entry["routing_key"].replace(".v1", ".v2")}
        for name, entry in contract["message_types"].items()
        if name in RUN_TYPES
    }
    return contract


def build_envelope() -> dict:
    env = _retarget(_load(V1 / "envelope.schema.json"))
    env["$id"] = "urn:blog-agent:v2:envelope"
    env["title"] = "AgentEnvelopeV2"
    env["properties"]["schema_version"] = {"const": 2}
    env["description"] = env["description"].replace("B1 zarf", "v2 zarf (B1 zarfinin surum 2'si)")
    return env


def build_common() -> dict:
    common = _retarget(_load(V1 / "common.schema.json"))
    common["title"] = "Blog agent messaging v2 ortak tanimlar"
    defs = common["$defs"]
    defs["conversation_topic"] = {"enum": ["auto", "who_am_i"]}
    defs["run_intent"] = {
        "enum": [
            "article_qa", "summarize", "explain", "compare", "research", "general",
            "profile", "projects", "content_suggestion", "collaboration",
        ]
    }
    defs["profile_id"] = {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,63}$"}
    defs["section_id"] = {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,127}$"}
    defs["profile_snapshot_ref"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["profile_id", "revision", "content_hash"],
        "properties": {
            "profile_id": {"$ref": "#/$defs/profile_id"},
            "revision": {"type": "integer", "minimum": 1},
            "content_hash": {"$ref": "#/$defs/hash_hex"},
        },
    }

    src = defs["source_reference"]
    src["properties"]["kind"] = {"enum": ["article", "web", "profile"]}
    src["properties"]["profile_id"] = {"$ref": "#/$defs/profile_id"}
    src["properties"]["profile_revision"] = {"type": "integer", "minimum": 1}
    src["properties"]["profile_content_hash"] = {"$ref": "#/$defs/hash_hex"}
    src["properties"]["section_id"] = {"$ref": "#/$defs/section_id"}
    profile_fields = ["profile_id", "profile_revision", "profile_content_hash", "section_id"]
    no_profile = [{"required": [f]} for f in profile_fields]
    for rule in src["allOf"]:
        then = rule["then"]
        then["not"]["anyOf"].extend(copy.deepcopy(no_profile))
    src["allOf"].append({
        "if": {"properties": {"kind": {"const": "profile"}}, "required": ["kind"]},
        "then": {
            "required": [
                "source_id", "title", "profile_id", "profile_revision",
                "profile_content_hash", "section_id", "chunk_index", "url",
            ],
            "properties": {"url": {"type": "string", "pattern": "^/about#[a-z0-9][a-z0-9-]{0,127}$"}},
            "not": {
                "anyOf": [
                    {"required": ["article_id"]},
                    {"required": ["article_revision"]},
                    {"required": ["accessed_at"]},
                ]
            },
        },
    })
    src["description"] = (
        "Kaynak referansi. profile turu: source_id = "
        "profile:{profile_id}:{profile_revision}:{profile_content_hash}:{section_id}:{chunk_index}, "
        "url = /about#{section_id} (dogrulayicilar capraz kural olarak denetler); "
        "URL modelden alinmaz, canonical metadata'dan uretilir."
    )
    return common


def _profile_intent_rule(extra_then: dict | None = None) -> dict:
    then: dict = {"required": ["profile_snapshot"], "properties": {"source_scope": {"const": "profile"}}}
    if extra_then:
        for key, value in extra_then.items():
            if key == "properties":
                then["properties"].update(value)
            else:
                then[key] = value
    return {"if": {"properties": {"run_intent": {"const": "profile"}}, "required": ["run_intent"]}, "then": then}


def build_payload(name: str) -> dict:
    schema = _retarget(_load(V1 / "payloads" / f"{name}.schema.json"))
    _title(schema)
    props = schema["properties"]
    if name == "agent.execute.requested":
        props["conversation_topic"] = {"$ref": COMMON + "conversation_topic"}
        props["profile_snapshot"] = {"$ref": COMMON + "profile_snapshot_ref"}
        schema["required"].append("conversation_topic")
        schema["allOf"].append({
            "if": {"properties": {"conversation_topic": {"const": "who_am_i"}}, "required": ["conversation_topic"]},
            "then": {
                "required": ["profile_snapshot"],
                "not": {
                    "anyOf": [
                        {"required": ["article_id"]},
                        {"required": ["article_revision"]},
                        {"required": ["article_content_hash"]},
                        {"required": ["selected_text"]},
                    ]
                },
            },
        })
    elif name == "agent.run.mode_selected":
        props["run_intent"] = {"$ref": COMMON + "run_intent"}
        props["source_scope"] = {"$ref": COMMON + "source_scope"}
        props["profile_snapshot"] = {"$ref": COMMON + "profile_snapshot_ref"}
        schema["required"].extend(["run_intent", "source_scope"])
        schema["allOf"].append(_profile_intent_rule({"properties": {"requires_web_search": {"const": False}}}))
    elif name in ("agent.run.completed", "agent.run.partially_completed"):
        props["run_intent"] = {"$ref": COMMON + "run_intent"}
        props["profile_snapshot"] = {"$ref": COMMON + "profile_snapshot_ref"}
        schema["required"].append("run_intent")
        schema["allOf"].append(_profile_intent_rule({
            "properties": {"citations": {"type": "array", "items": {"properties": {"kind": {"const": "profile"}}}}},
            "not": {"required": ["action_proposal"]},
        }))
    elif name == "agent.run.failed":
        props["run_intent"] = {"$ref": COMMON + "run_intent"}
        props["profile_snapshot"] = {"$ref": COMMON + "profile_snapshot_ref"}
    schema["$id"] = f"urn:blog-agent:v2:payload:{name}"
    return schema


def main() -> None:
    _dump(V2 / "contract.json", build_contract())
    _dump(V2 / "envelope.schema.json", build_envelope())
    _dump(V2 / "common.schema.json", build_common())
    contract = build_contract()
    for name, entry in contract["message_types"].items():
        _dump(V2 / entry["payload_schema"], build_payload(name))
    print(f"v2: {len(contract['message_types'])} mesaj turu yazildi")


if __name__ == "__main__":
    main()
