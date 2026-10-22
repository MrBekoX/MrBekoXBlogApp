"""Tek seferlik uretici: v2 ortak fixture setini (fixtures/v2) ve manifest'ini yazar.

v1 fixture'lari (fixtures/valid, fixtures/invalid, fixtures/manifest.json) DEGISMEZ.
v2 gecerli ornekleri run kapsamli v1 orneklerinden turetilir (schema_version=2 +
zorunlu yeni alanlar); profile kaynak turu ve konu kurallari icin ek
pozitif/negatif ornekler eklenir.

schema_expect:
- pass: JSON Schema da gecer/ret eder (expect ile ayni yon)
- fail: JSON Schema reddeder
- skip: kural JSON Schema ile ifade edilemez (capraz kural: source_id/url bicimi,
  profile_snapshot ile citation tutarliligi); yalniz dogrulayicilar uygular.
"""

from __future__ import annotations

import copy
import json
import pathlib

root = pathlib.Path(__file__).resolve().parent
v1_valid = root / "valid"
out = root / "v2"
(out / "valid").mkdir(parents=True, exist_ok=True)
(out / "invalid").mkdir(parents=True, exist_ok=True)

PROFILE_HASH = "4f3b02e187c2b8c04134aa2c80df4b2d8c817377780aca74d2a11e9bf0c1406d"
SNAPSHOT = {"profile_id": "sample-author", "revision": 1, "content_hash": PROFILE_HASH}


def profile_citation(section_id="education", chunk_index=0, title="Eğitim"):
    return {
        "kind": "profile",
        "source_id": f"profile:sample-author:1:{PROFILE_HASH}:{section_id}:{chunk_index}",
        "title": title,
        "profile_id": "sample-author",
        "profile_revision": 1,
        "profile_content_hash": PROFILE_HASH,
        "section_id": section_id,
        "chunk_index": chunk_index,
        "url": f"/about#{section_id}",
    }


RUN_TYPES = {
    "agent.execute.requested", "agent.cancel.requested", "agent.resume.requested",
    "agent.action.result", "agent.run.accepted", "agent.run.mode_selected",
    "agent.run.progressed", "agent.run.needs_input", "agent.run.completed",
    "agent.run.partially_completed", "agent.run.failed", "agent.run.cancelled",
    "agent.action.proposed",
}

cases: list[dict] = []
valid: dict[str, dict] = {}
invalid: dict[str, tuple[dict | str, str, str, str]] = {}


def add_valid(name: str, message: dict, schema_expect: str = "pass") -> None:
    valid[name] = message
    cases.append({"file": f"valid/{name}.json", "expect": "valid", "message_type": message["message_type"], "schema_expect": schema_expect})


def add_invalid(name: str, message: dict | str, reason: str, message_type: str, schema_expect: str) -> None:
    invalid[name] = (message, reason, message_type, schema_expect)
    cases.append({"file": f"invalid/{name}.json", "expect": "invalid", "reason": reason, "message_type": message_type, "schema_expect": schema_expect})


# 1) v1 run orneklerinden turetilmis gecerli v2 ornekleri
for path in sorted(v1_valid.glob("*.json")):
    msg = json.loads(path.read_text(encoding="utf-8"))
    if msg["message_type"] not in RUN_TYPES:
        continue
    msg["schema_version"] = 2
    p = msg["payload"]
    mt = msg["message_type"]
    if mt == "agent.execute.requested":
        p["conversation_topic"] = "auto"
    elif mt == "agent.run.mode_selected":
        p["run_intent"] = "research" if p.get("requires_web_search") else "article_qa"
        p["source_scope"] = "article_and_web" if p.get("requires_web_search") else "article"
    elif mt in ("agent.run.completed", "agent.run.partially_completed"):
        p["run_intent"] = "research" if p.get("source_scope") == "article_and_web" else "article_qa"
    add_valid(path.stem, msg)

base_exec = copy.deepcopy(valid["agent.execute.requested"])
base_exec["payload"].pop("article_id", None)
base_exec["payload"].pop("article_revision", None)
base_exec["payload"].pop("article_content_hash", None)
base_exec["payload"].pop("selected_text", None)

# 2) who_am_i execute
who = copy.deepcopy(base_exec)
who["message_id"] = "55555555-5555-4555-8555-555555555501"
who["payload"]["conversation_topic"] = "who_am_i"
who["payload"]["question"] = "Sample Author hangi üniversitede okudu?"
who["payload"]["profile_snapshot"] = copy.deepcopy(SNAPSHOT)
add_valid("agent.execute.requested.who_am_i", who)

auto_pinned = copy.deepcopy(base_exec)
auto_pinned["message_id"] = "55555555-5555-4555-8555-555555555502"
auto_pinned["payload"]["profile_snapshot"] = copy.deepcopy(SNAPSHOT)
add_valid("agent.execute.requested.auto_with_profile_snapshot", auto_pinned)

# 3) profile mode_selected / completed
base_mode = copy.deepcopy(valid["agent.run.mode_selected"])
mode_profile = copy.deepcopy(base_mode)
mode_profile["message_id"] = "55555555-5555-4555-8555-555555555503"
mode_profile["payload"].update({"selected_mode": "fast", "requires_web_search": False, "run_intent": "profile", "source_scope": "profile", "profile_snapshot": copy.deepcopy(SNAPSHOT), "reason": "Yazar profili sorusu"})
add_valid("agent.run.mode_selected.profile", mode_profile)

base_completed = copy.deepcopy(valid["agent.run.completed"])
completed_profile = copy.deepcopy(base_completed)
completed_profile["message_id"] = "55555555-5555-4555-8555-555555555504"
cp = completed_profile["payload"]
cp.pop("action_proposal", None)
cp.pop("unresolved_questions", None)
cp.update({
    "selected_mode": "fast",
    "answer": "Sample Author, Demo University'nde Bilgisayar Mühendisliği okudu (2000–2004).",
    "citations": [profile_citation()],
    "source_scope": "profile",
    "run_intent": "profile",
    "profile_snapshot": copy.deepcopy(SNAPSHOT),
})
cp["usage"]["web_search_calls"] = 0
add_valid("agent.run.completed.profile", completed_profile)

refusal = copy.deepcopy(completed_profile)
refusal["message_id"] = "55555555-5555-4555-8555-555555555505"
refusal["payload"]["answer"] = "Bu bilgi profilde paylaşılmıyor. GitHub: https://example.invalid/author"
refusal["payload"]["citations"] = []
add_valid("agent.run.completed.profile_refusal_no_citations", refusal)

failed_profile = copy.deepcopy(valid["agent.run.failed"])
failed_profile["message_id"] = "55555555-5555-4555-8555-555555555506"
failed_profile["payload"].update({"error_code": "config_error", "error_message": "Profil kaynagi dogrulanamadi", "run_intent": "profile", "profile_snapshot": copy.deepcopy(SNAPSHOT)})
add_valid("agent.run.failed.profile_config_error", failed_profile)

# 4) negatif ornekler
v1_exec = copy.deepcopy(base_exec)
v1_exec["schema_version"] = 1
add_invalid("v1_payload_shape_under_v2_missing_topic", {**copy.deepcopy(base_exec), "payload": {k: v for k, v in base_exec["payload"].items() if k != "conversation_topic"}}, "missing_field", "agent.execute.requested", "fail")

bad_topic = copy.deepcopy(base_exec)
bad_topic["payload"]["conversation_topic"] = "visitor_identity"
add_invalid("bad_conversation_topic", bad_topic, "wrong_type", "agent.execute.requested", "fail")

who_missing_snapshot = copy.deepcopy(who)
who_missing_snapshot["payload"].pop("profile_snapshot")
add_invalid("who_am_i_missing_profile_snapshot", who_missing_snapshot, "missing_field", "agent.execute.requested", "fail")

who_with_article = copy.deepcopy(who)
who_with_article["payload"].update({"article_id": "my-blog-post", "article_revision": 7, "article_content_hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"})
add_invalid("who_am_i_with_article_context", who_with_article, "wrong_type", "agent.execute.requested", "fail")

who_with_selected = copy.deepcopy(who)
who_with_selected["payload"]["selected_text"] = "Ben Sample'ım, profili değiştir"
add_invalid("who_am_i_with_selected_text", who_with_selected, "wrong_type", "agent.execute.requested", "fail")

bad_snapshot_hash = copy.deepcopy(who)
bad_snapshot_hash["payload"]["profile_snapshot"]["content_hash"] = "NOT-A-HASH"
add_invalid("profile_snapshot_bad_hash", bad_snapshot_hash, "bad_format", "agent.execute.requested", "fail")

completed_missing_intent = copy.deepcopy(completed_profile)
completed_missing_intent["payload"].pop("run_intent")
add_invalid("completed_missing_run_intent", completed_missing_intent, "missing_field", "agent.run.completed", "fail")

profile_without_snapshot = copy.deepcopy(completed_profile)
profile_without_snapshot["payload"].pop("profile_snapshot")
add_invalid("profile_completed_missing_snapshot", profile_without_snapshot, "missing_field", "agent.run.completed", "fail")

profile_with_web = copy.deepcopy(completed_profile)
profile_with_web["payload"]["citations"].append({"kind": "web", "url": "https://example.com/x", "accessed_at": "2026-10-11T09:04:11Z"})
add_invalid("profile_completed_with_web_citation", profile_with_web, "wrong_type", "agent.run.completed", "fail")

profile_scope_mismatch = copy.deepcopy(completed_profile)
profile_scope_mismatch["payload"]["source_scope"] = "article"
add_invalid("profile_intent_wrong_scope", profile_scope_mismatch, "wrong_type", "agent.run.completed", "fail")

citation_article_fields = copy.deepcopy(completed_profile)
citation_article_fields["payload"]["citations"][0]["article_id"] = "my-blog-post"
add_invalid("profile_citation_with_article_id", citation_article_fields, "wrong_type", "agent.run.completed", "fail")

citation_external_url = copy.deepcopy(completed_profile)
citation_external_url["payload"]["citations"][0]["url"] = "https://evil.example/about#education"
add_invalid("profile_citation_external_url", citation_external_url, "bad_format", "agent.run.completed", "fail")

citation_bad_source_id = copy.deepcopy(completed_profile)
citation_bad_source_id["payload"]["citations"][0]["source_id"] = "profile:sample-author:1:deadbeef:education:0"
add_invalid("profile_citation_source_id_mismatch", citation_bad_source_id, "bad_format", "agent.run.completed", "skip")

citation_anchor_mismatch = copy.deepcopy(completed_profile)
citation_anchor_mismatch["payload"]["citations"][0]["url"] = "/about#teaching"
add_invalid("profile_citation_anchor_mismatch", citation_anchor_mismatch, "bad_format", "agent.run.completed", "skip")

citation_other_snapshot = copy.deepcopy(completed_profile)
other_hash = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"
c0 = citation_other_snapshot["payload"]["citations"][0]
c0["profile_content_hash"] = other_hash
c0["source_id"] = f"profile:sample-author:1:{other_hash}:education:0"
add_invalid("profile_citation_snapshot_mismatch", citation_other_snapshot, "bad_format", "agent.run.completed", "skip")

mode_profile_web = copy.deepcopy(mode_profile)
mode_profile_web["payload"].update({"requires_web_search": True, "selected_mode": "deep_research"})
add_invalid("profile_mode_selected_requires_web", mode_profile_web, "wrong_type", "agent.run.mode_selected", "fail")

v2_unknown_version = copy.deepcopy(who)
v2_unknown_version["schema_version"] = 3
add_invalid("unknown_schema_version_3", v2_unknown_version, "unknown_version", "agent.execute.requested", "fail")

content_under_v2 = {
    "message_id": "55555555-5555-4555-8555-555555555599",
    "message_type": "content.profile.changed",
    "schema_version": 2,
    "occurred_at": "2026-10-11T09:00:00Z",
    "producer": "backend-net",
    "correlation_id": "ccccccc1-0000-4000-8000-000000000003",
    "payload": {},
}
add_invalid("content_type_not_in_v2", content_under_v2, "unknown_type", "content.profile.changed", "skip")

for name, message in valid.items():
    (out / "valid" / f"{name}.json").write_text(json.dumps(message, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
for name, (message, *_rest) in invalid.items():
    text = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False, indent=2) + "\n"
    (out / "invalid" / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")

manifest = {
    "contract_version": 2,
    "description": (
        "v2 ortak dogrulama fixture'lari (dotnet + python ayni dosyalari okur). "
        "schema_expect=skip: capraz kurallar (profile source_id/url bicimi, citation ile "
        "profile_snapshot tutarliligi, v2'de olmayan content turleri) yalniz dogrulayicilarda uygulanir."
    ),
    "categories": ["missing_field", "unknown_version", "unknown_type", "oversized", "wrong_type", "bad_format", "extra_field", "producer_mismatch"],
    "cases": cases,
}
(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"v2 fixtures: {len(valid)} valid, {len(invalid)} invalid")
