"""Tek seferlik fixture uretici: B1 ortak fixture setini ve manifest'i yazar."""

import json
import pathlib

root = pathlib.Path(__file__).resolve().parent
valid = root / "valid"
invalid = root / "invalid"
valid.mkdir(parents=True, exist_ok=True)
invalid.mkdir(parents=True, exist_ok=True)

HASH1 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"  # sha256("test")
HASH2 = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"  # sha256("foo")
RUN = "aaaaaaa1-0000-4000-8000-000000000001"
CONV = "bbbbbbb1-0000-4000-8000-000000000002"
CORR = "ccccccc1-0000-4000-8000-000000000003"
CAUSE = "ddddddd1-0000-4000-8000-000000000004"
TRACE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def env(message_id, message_type, payload, *, producer="backend-net", run=RUN, conv=CONV,
        corr=CORR, cause=CAUSE, occurred="2026-10-11T09:00:00Z", deadline=None,
        trace=TRACE, delivery_attempt=None, schema_version=1):
    e = {
        "message_id": message_id,
        "message_type": message_type,
        "schema_version": schema_version,
        "occurred_at": occurred,
        "producer": producer,
        "payload": payload,
    }
    if corr is not None:
        e["correlation_id"] = corr
    if run is not None:
        e["run_id"] = run
    if conv is not None:
        e["conversation_id"] = conv
    if cause is not None:
        e["causation_id"] = cause
    if deadline is not None:
        e["deadline_at"] = deadline
    if trace is not None:
        e["trace_context"] = trace
    if delivery_attempt is not None:
        e["delivery_attempt"] = delivery_attempt
    return e


usage = {
    "run_id": RUN, "model_calls": 5, "prompt_tokens": 4200, "completion_tokens": 1100,
    "total_tokens": 5300, "tool_calls": 3, "web_search_calls": 2,
    "duration_seconds": 42.5, "recorded_at": "2026-10-11T09:04:30Z",
}
proposal = {
    "run_id": RUN, "proposal_id": "prop-1", "article_id": "my-blog-post", "article_revision": 7,
    "base_content_hash": HASH1, "summary": "Giris paragrafi sikilastirmasi",
    "proposed_content": "Yeni giris paragrafi ...", "created_at": "2026-10-11T09:04:20Z",
}

valid_cases = {}

# --- backend -> agent : commands ---
valid_cases["agent.execute.requested.json"] = env(
    "11111111-1111-4111-8111-111111111111", "agent.execute.requested",
    {"user_ref": "user-42", "question": "Bu makaledeki ana fikir nedir?", "language": "tr",
     "mode_preference": "auto", "budget_profile": "fast-default"},
    deadline="2026-10-11T09:05:00Z", delivery_attempt=0)

valid_cases["agent.execute.requested.with_article.json"] = env(
    "11111111-1111-4111-8111-111111111112", "agent.execute.requested",
    {"user_ref": "user-42", "question": "Secili paragrafi aciklar misin?", "language": "tr",
     "mode_preference": "analysis", "budget_profile": "analysis-default",
     "article_id": "my-blog-post", "article_revision": 7, "article_content_hash": HASH1,
     "context_snapshot_reference": "agent/article-snapshot/my-blog-post/7",
     "selected_text": "Onemli paragraf",
     "conversation_history": [
         {"role": "user", "content": "Merhaba", "created_at": "2026-10-11T08:58:00Z"},
         {"role": "assistant", "content": "Merhaba, nasil yardimci olabilirim?", "created_at": "2026-10-11T08:58:05Z"}]},
    deadline="2026-10-11T09:06:00Z")

valid_cases["agent.cancel.requested.json"] = env(
    "22222222-2222-4222-8222-222222222221", "agent.cancel.requested",
    {"reason": "Kullanici iptal etti"})

valid_cases["agent.resume.requested.json"] = env(
    "22222222-2222-4222-8222-222222222222", "agent.resume.requested",
    {"checkpoint_reference": "agent/checkpoint/" + RUN + "/attempt-1", "user_ref": "user-42"})

valid_cases["agent.action.result.accepted.json"] = env(
    "22222222-2222-4222-8222-222222222223", "agent.action.result",
    {"proposal_id": "prop-1", "outcome": "accepted", "applied_article_revision": 8,
     "validated_at": "2026-10-11T10:00:00Z"})

valid_cases["agent.action.result.rejected.json"] = env(
    "22222222-2222-4222-8222-222222222224", "agent.action.result",
    {"proposal_id": "prop-2", "outcome": "rejected",
     "reason": "Onaylanmayan surum", "validated_at": "2026-10-11T10:01:00Z"})

# --- agent -> backend : events (producer agent-py) ---
valid_cases["agent.run.accepted.json"] = env(
    "33333333-3333-4333-8333-333333333331", "agent.run.accepted",
    {"event_sequence": 1, "execution_attempt": 1, "fencing_token": "lease-0001",
     "accepted_at": "2026-10-11T09:00:02Z"},
    producer="agent-py", cause=None)

valid_cases["agent.run.mode_selected.json"] = env(
    "33333333-3333-4333-8333-333333333332", "agent.run.mode_selected",
    {"event_sequence": 2, "selected_mode": "deep_research", "requires_web_search": True,
     "reason": "Soru karsilastirmali arastirma istiyor"},
    producer="agent-py", cause=None)

valid_cases["agent.run.progressed.json"] = env(
    "33333333-3333-4333-8333-333333333333", "agent.run.progressed",
    {"event_sequence": 3, "execution_attempt": 1, "fencing_token": "lease-0003",
     "kind": "retrieval_started", "message": "Makale baglami hazirlaniyor",
     "detail": {"chunk_count": "12"}},
    producer="agent-py", cause=None, delivery_attempt=2)

valid_cases["agent.run.needs_input.json"] = env(
    "33333333-3333-4333-8333-333333333334", "agent.run.needs_input",
    {"event_sequence": 5, "unresolved_questions": ["Hangi donemi karsilastirmak istersiniz?"],
     "usage": usage},
    producer="agent-py", cause=None)

valid_cases["agent.run.completed.json"] = env(
    "33333333-3333-4333-8333-333333333335", "agent.run.completed",
    {"event_sequence": 7, "execution_attempt": 1, "fencing_token": "lease-0007",
     "selected_mode": "deep_research", "answer": "Raporun ozeti ...",
     "citations": [
         {"kind": "article", "article_id": "my-blog-post", "article_revision": 7, "chunk_index": 2},
         {"kind": "web", "url": "https://example.com/source", "accessed_at": "2026-10-11T09:04:11Z"}],
     "source_scope": "article_and_web",
     "unresolved_questions": ["Kaynak erisimi sinirliydi"],
     "usage": usage, "action_proposal": proposal},
    producer="agent-py", cause=None)

valid_cases["agent.run.partially_completed.json"] = env(
    "33333333-3333-4333-8333-333333333336", "agent.run.partially_completed",
    {"event_sequence": 8, "selected_mode": "analysis", "report": "Kismi analiz raporu",
     "source_scope": "article",
     "unresolved_questions": ["Ikinci tur arastirma gerekiyor"], "usage": usage},
    producer="agent-py", cause=None)

valid_cases["agent.run.failed.json"] = env(
    "33333333-3333-4333-8333-333333333337", "agent.run.failed",
    {"event_sequence": 4, "error_code": "provider_error",
     "error_message": "Model saglayicisi zaman asimi", "usage": usage},
    producer="agent-py", cause=None)

valid_cases["agent.run.cancelled.json"] = env(
    "33333333-3333-4333-8333-333333333338", "agent.run.cancelled",
    {"event_sequence": 6, "reason": "Kullanici iptal etti", "usage": usage},
    producer="agent-py", cause=None)

valid_cases["agent.action.proposed.json"] = env(
    "33333333-3333-4333-8333-333333333339", "agent.action.proposed",
    {"event_sequence": 6, "run_id": RUN, "proposal_id": "prop-1",
     "article_id": "my-blog-post", "article_revision": 7, "base_content_hash": HASH1,
     "summary": "Giris paragrafi sikilastirmasi", "proposed_content": "Yeni giris paragrafi ...",
     "created_at": "2026-10-11T09:04:20Z"},
    producer="agent-py", cause=None)

# --- backend -> agent : content ---
valid_cases["content.article.changed.json"] = env(
    "44444444-4444-4444-8444-444444444441", "content.article.changed",
    {"article_id": "my-blog-post", "article_revision": 8, "action": "updated",
     "content_hash": HASH2, "language": "tr", "title": "Guncellenmis baslik"},
    run=None, conv=None, cause=None)

valid_cases["content.article.changed.unpublished.json"] = env(
    "44444444-4444-4444-8444-444444444442", "content.article.changed",
    {"article_id": "my-blog-post", "article_revision": 8, "action": "unpublished"},
    run=None, conv=None, cause=None)

valid_cases["content.sync.batch.json"] = env(
    "44444444-4444-4444-8444-444444444443", "content.sync.batch",
    {"sync_id": "sync-2026-10-11-001", "batch_index": 0, "total_batches": 3,
     "items": [
         {"article_id": "post-a", "article_revision": 12, "content_hash": HASH1},
         {"article_id": "post-b", "article_revision": 4, "content_hash": HASH2}]},
    run=None, conv=None, cause=None)

valid_cases["content.sync.completed.json"] = env(
    "44444444-4444-4444-8444-444444444444", "content.sync.completed",
    {"sync_id": "sync-2026-10-11-001", "item_count": 2},
    run=None, conv=None, cause=None)

valid_cases["content.profile.changed.json"] = env(
    "44444444-4444-4444-8444-444444444445", "content.profile.changed",
    {"profile_revision": 3, "content_hash": HASH1,
     "context_snapshot_reference": "agent/profile-snapshot/3"},
    run=None, conv=None, cause=None)

valid_cases["content.project.changed.json"] = env(
    "44444444-4444-4444-8444-444444444446", "content.project.changed",
    {"project_id": "blogapp", "project_revision": 5, "content_hash": HASH2,
     "context_snapshot_reference": "agent/project-snapshot/blogapp/5"},
    run=None, conv=None, cause=None)

for name, doc in valid_cases.items():
    (valid / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# --- invalid fixtures ---
invalid_cases = {}

invalid_cases["missing_required_field.json"] = env(
    "55555555-5555-4555-8555-555555555551", "agent.execute.requested",
    {"user_ref": "user-42", "language": "tr", "mode_preference": "auto",
     "budget_profile": "fast-default"},
    deadline="2026-10-11T09:05:00Z")

invalid_cases["missing_envelope_field.json"] = env(
    "55555555-5555-4555-8555-555555555552", "agent.cancel.requested", {},
    corr=None)

invalid_cases["missing_run_identity.json"] = env(
    "55555555-5555-4555-8555-555555555553", "agent.run.completed",
    {"event_sequence": 7, "selected_mode": "fast", "answer": "Cevap",
     "source_scope": "article", "usage": usage},
    producer="agent-py", run=None, conv=None, cause=None)

invalid_cases["missing_deadline_for_execute.json"] = env(
    "55555555-5555-4555-8555-555555555554", "agent.execute.requested",
    {"user_ref": "user-42", "question": "Soru", "language": "tr",
     "mode_preference": "fast", "budget_profile": "fast-default"})

# v2 (Who am I) geçerli sürüm oldu; bilinmeyen sürüm örneği 99'a taşındı.
invalid_cases["unknown_schema_version.json"] = env(
    "55555555-5555-4555-8555-555555555555", "agent.cancel.requested", {},
    schema_version=99)

invalid_cases["unknown_message_type.json"] = env(
    "55555555-5555-4555-8555-555555555556", "agent.summarize.requested", {},
    deadline="2026-10-11T09:05:00Z")

big_question = "x" * 300000
invalid_cases["oversized_payload.json"] = env(
    "55555555-5555-4555-8555-555555555557", "agent.execute.requested",
    {"user_ref": "user-42", "question": big_question, "language": "tr",
     "mode_preference": "fast", "budget_profile": "fast-default"},
    deadline="2026-10-11T09:05:00Z")

invalid_cases["payload_not_object.json"] = env(
    "55555555-5555-4555-8555-555555555558", "agent.cancel.requested", "not-an-object")

invalid_cases["wrong_field_type.json"] = env(
    "55555555-5555-4555-8555-555555555559", "agent.execute.requested",
    {"user_ref": "user-42", "question": "Soru", "language": 42,
     "mode_preference": "fast", "budget_profile": "fast-default"},
    deadline="2026-10-11T09:05:00Z")

invalid_cases["bad_uuid.json"] = env(
    "not-a-uuid", "agent.cancel.requested", {})

invalid_cases["non_utc_timestamp.json"] = env(
    "55555555-5555-4555-8555-555555555560", "agent.cancel.requested", {},
    occurred="2026-10-11T12:00:00+03:00")

extra_env = env("55555555-5555-4555-8555-555555555561", "agent.cancel.requested", {})
extra_env["broker_hint"] = "internal-only"
invalid_cases["extra_envelope_field.json"] = extra_env

extra_payload = env(
    "55555555-5555-4555-8555-555555555562", "agent.execute.requested",
    {"user_ref": "user-42", "question": "Soru", "language": "tr",
     "mode_preference": "fast", "budget_profile": "fast-default",
     "client_owner_claim": "user-42"},
    deadline="2026-10-11T09:05:00Z")
invalid_cases["extra_payload_field.json"] = extra_payload

invalid_cases["producer_direction_mismatch.json"] = env(
    "55555555-5555-4555-8555-555555555563", "agent.run.completed",
    {"event_sequence": 7, "selected_mode": "fast", "answer": "Cevap",
     "source_scope": "article", "usage": usage},
    producer="backend-net", cause=None)

invalid_cases["malformed_json.json"] = "{ this is not json"

invalid_cases["bad_enum_value.json"] = env(
    "55555555-5555-4555-8555-555555555564", "agent.run.completed",
    {"event_sequence": 7, "selected_mode": "fast", "answer": "Cevap",
     "source_scope": "everywhere", "usage": usage},
    producer="agent-py", cause=None)

invalid_cases["answer_and_report.json"] = env(
    "55555555-5555-4555-8555-555555555565", "agent.run.completed",
    {"event_sequence": 7, "selected_mode": "fast", "answer": "Cevap",
     "report": "Rapor", "source_scope": "article", "usage": usage},
    producer="agent-py", cause=None)

for name, doc in invalid_cases.items():
    (invalid / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# Bozuk JSON fixture'i ham metin olarak yazilir (json.dumps ile tirnaklanmaz).
(invalid / "malformed_json.json").write_text(invalid_cases["malformed_json.json"] + "\n", encoding="utf-8")

manifest_cases = []
for name, doc in valid_cases.items():
    mt = doc["message_type"]
    manifest_cases.append({"file": "valid/" + name, "expect": "valid",
                           "message_type": mt, "schema_expect": "pass"})

schema_pass_reasons = {"producer_direction_mismatch.json", "missing_run_identity.json",
                       "missing_deadline_for_execute.json", "unknown_message_type.json"}
schema_skip_reasons = {"malformed_json.json"}
reasons = {
    "missing_required_field.json": "missing_field",
    "missing_envelope_field.json": "missing_field",
    "missing_run_identity.json": "missing_field",
    "missing_deadline_for_execute.json": "missing_field",
    "unknown_schema_version.json": "unknown_version",
    "unknown_message_type.json": "unknown_type",
    "oversized_payload.json": "oversized",
    "payload_not_object.json": "wrong_type",
    "wrong_field_type.json": "wrong_type",
    "bad_enum_value.json": "wrong_type",
    "answer_and_report.json": "wrong_type",
    "bad_uuid.json": "bad_format",
    "non_utc_timestamp.json": "bad_format",
    "malformed_json.json": "bad_format",
    "extra_envelope_field.json": "extra_field",
    "extra_payload_field.json": "extra_field",
    "producer_direction_mismatch.json": "producer_mismatch",
}
for name in invalid_cases:
    reason = reasons[name]
    if name in schema_skip_reasons:
        se = "skip"
    elif name in schema_pass_reasons:
        se = "pass"
    else:
        se = "fail"
    manifest_cases.append({"file": "invalid/" + name, "expect": "invalid",
                           "reason": reason, "schema_expect": se})

manifest = {
    "contract_version": 1,
    "description": "B1 ortak dogrulama fixture'lari. Iki dil (dotnet ve python) ayni dosyalari okur; expect/reason/schema_expect beklentileri her iki dogrulayici icin de gecerlidir. schema_expect=pass, JSON Schema'nin ifade edemedigi kurallarin (yon/uretici uyumu, run kimligi ve deadline zorunlulugu) dogrulayici tarafinda uygulanir.",
    "categories": ["missing_field", "unknown_version", "unknown_type", "oversized",
                   "wrong_type", "bad_format", "extra_field", "producer_mismatch"],
    "cases": manifest_cases,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("valid:", len(valid_cases), "invalid:", len(invalid_cases), "total cases:", len(manifest_cases))
