"""Dataset contracts and metric arithmetic are offline checks, not model quality."""

import importlib.util
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SERVICE = Path(__file__).resolve().parents[2]


def test_existing_corpus_check_also_validates_versioned_behavior_coverage():
    result = subprocess.run(
        [sys.executable, str(SERVICE / "tools" / "evaluate_grounding.py"), "--check-corpus", "--scope", "all"],
        env=dict(os.environ, AGENT_ENV_FILE=os.devnull, AGENT_RUN_PAID_TESTS="0"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["provider_calls"] == 0
    assert output["behavior_dataset"]["version"] == "agent-readiness-v1"
    assert output["behavior_dataset"]["cases"] == 24
    assert output["behavior_dataset"]["semantic_quality"] == "not_measured"


def evaluator():
    spec = importlib.util.spec_from_file_location("readiness_evaluation", SERVICE / "tools" / "readiness_evaluation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readiness_dataset_rejects_missing_coverage_and_duplicate_ids():
    module = evaluator()
    dataset = module.load_dataset()
    dataset["cases"] = [case for case in dataset["cases"] if case["subset"] != "injection"]
    with pytest.raises(ValueError, match="coverage"):
        module.validate_dataset(dataset)
    dataset = module.load_dataset()
    dataset["cases"][1]["id"] = dataset["cases"][0]["id"]
    with pytest.raises(ValueError, match="duplicate"):
        module.validate_dataset(dataset)


def test_paid_report_identity_binds_actual_corpus_and_prompt_bytes_without_a_provider_call():
    spec = importlib.util.spec_from_file_location("grounding_identity_test", SERVICE / "tools" / "grounding_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    identity = module.evaluation_identity(cases)
    assert identity["samples"] == 9
    assert len(identity["dataset_sha256"]) == len(identity["prompt_sources_sha256"]) == 64
    assert identity["layer"] == "real-provider"
    assert "no independent human calibration" in identity["judge"]


def observations(dataset):
    cases = {case["id"]: case for case in dataset["cases"]}
    supported = next(case for case in cases.values() if case["answerable"])
    unsupported = next(case for case in cases.values() if not case["answerable"])
    return {
        "kind": "agent-readiness-observations-v1", "commit": "a" * 40,
        "dataset_version": dataset["version"], "dataset_hash": evaluator().dataset_hash(dataset),
        "provider": "test-fixture", "model": "test-fixture", "prompt_version": "test-v1",
        "layer": "unit-fixture", "grader": "human", "grader_calibrated": False,
        "cases": [
            {"id": supported["id"], "intent": supported["intent"], "status": supported["expected_status"], "answered": False,
             "supported": None, "task_success": False, "retrieved_source_ids": [], "citation_source_ids": [],
             "latency_seconds": 2, "chat_tokens": 100, "embedding_tokens": 10, "usage_basis": "reported", "cost_usd": None},
            {"id": unsupported["id"], "intent": unsupported["intent"], "status": unsupported["expected_status"], "answered": True,
             "supported": False, "task_success": False, "retrieved_source_ids": [], "citation_source_ids": ["unknown-target"],
             "latency_seconds": None, "chat_tokens": 200, "embedding_tokens": 20, "usage_basis": "estimated", "cost_usd": None},
        ],
    }


def test_metrics_keep_false_acceptance_refusal_citations_and_missing_cost_separate():
    module = evaluator()
    dataset = module.load_dataset()
    report = module.assess_observations(dataset, observations(dataset))
    assert report["samples"] == 2 and report["dataset_cases"] == 24
    assert report["metrics"]["unsupported_answer_rate"] == 1
    assert report["metrics"]["unnecessary_refusal_rate"] == 1
    assert report["metrics"]["citation_precision"] == 0
    assert report["metrics"]["task_success_rate"] == 0
    assert report["metrics"]["latency_p95_seconds"] == 2
    assert report["measurement_counts"]["latency"] == 1
    assert report["metrics"]["cost_usd"] is None
    assert report["tokens"]["reported"] == {"chat": 100, "embedding": 10}
    assert report["tokens"]["estimated"] == {"chat": 200, "embedding": 20}
    assert report["semantic_quality"] == "not_measured_fixture"
    assert "passed" not in report  # No invented acceptance threshold.


@pytest.mark.parametrize("change", ["revision", "duplicate", "unknown", "nonfinite", "unbounded"])
def test_observation_gate_rejects_unbound_or_invalid_measurements(change):
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    if change == "revision":
        result["dataset_hash"] = "b" * 64
    elif change == "duplicate":
        result["cases"].append(result["cases"][0])
    elif change == "unknown":
        result["cases"][0]["id"] = "not-in-dataset"
    elif change == "nonfinite":
        result["cases"][0]["latency_seconds"] = float("nan")
    else:
        result["cases"][0]["raw_prompt"] = "must not become report content"
    with pytest.raises(ValueError):
        module.assess_observations(dataset, result)


@pytest.mark.parametrize("source,identity_field", [
    ("app/agent_core/qa/nodes.py", "prompt_sources_sha256"),
    ("tests/grounding/pipeline_expectations.json", "dataset_sha256"),
])
def test_live_identity_changes_with_actual_prompt_or_golden_rule_source(monkeypatch, source, identity_field):
    spec = importlib.util.spec_from_file_location("grounding_identity_dependencies", SERVICE / "tools" / "grounding_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    before = module.evaluation_identity(cases)
    original = Path.read_bytes
    target = SERVICE / source
    # Change only bytes observed by the identity calculation, never repo files.
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"\nchanged-public-evaluation-source" if path == target else original(path))
    after = module.evaluation_identity(cases)
    assert before[identity_field] != after[identity_field]


def test_completely_unmeasured_tokens_are_not_reported_as_zero_usage():
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    for row in result["cases"]:
        row.update(usage_basis="not_measured", chat_tokens=None, embedding_tokens=None)
    report = module.assess_observations(dataset, result)
    assert report["tokens"] == {"reported": None, "estimated": None, "mixed": None}
    assert report["measurement_counts"]["usage_measured"] == 0
    assert report["measurement_counts"]["usage_not_measured"] == 2


def test_measured_zero_usage_remains_distinct_from_missing_usage():
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    result["cases"] = result["cases"][:1]
    result["cases"][0].update(usage_basis="reported", chat_tokens=0, embedding_tokens=0)
    report = module.assess_observations(dataset, result)
    assert report["tokens"]["reported"] == {"chat": 0, "embedding": 0}
    assert report["measurement_counts"]["usage_measured"] == 1
    assert report["measurement_counts"]["usage_not_measured"] == 0


@pytest.mark.parametrize("change", ["large_integer", "large_finite_cost", "aggregate_cost", "aggregate_tokens"])
def test_numeric_protocol_rejects_unrepresentable_values_and_totals(change):
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    if change == "large_integer":
        result["cases"][0]["chat_tokens"] = 10**1000
    elif change == "large_finite_cost":
        for row in result["cases"]:
            row["cost_usd"] = 1e308
    elif change == "aggregate_cost":
        for row in result["cases"]:
            row["cost_usd"] = 2**52 + 10
    else:
        for row in result["cases"]:
            row.update(chat_tokens=2**52 + 10, usage_basis="reported")
    with pytest.raises(ValueError, match="measurement|aggregate"):
        module.assess_observations(dataset, result)


@pytest.mark.parametrize("invalid_number", [10**1000, 1e308], ids=["oversized-integer", "oversized-finite-float"])
def test_cli_numeric_rejection_returns_only_standard_sanitized_json(tmp_path, invalid_number):
    module = evaluator()
    result = observations(module.load_dataset())
    result["cases"][0]["cost_usd"] = invalid_number
    path = tmp_path / "public-observations.json"
    path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SERVICE / "tools" / "evaluate_grounding.py"), "--readiness-results", str(path)],
        env=dict(os.environ, AGENT_ENV_FILE=os.devnull, AGENT_RUN_PAID_TESTS="0"),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 1
    assert not completed.stderr
    assert json.loads(completed.stdout) == {"valid": False, "error": "Invalid bounded evaluation observations"}


@pytest.mark.parametrize("intent", ["compare", "explain", "summarize", "general", "projects", "content_suggestion", "collaboration"])
def test_observations_accept_all_current_runtime_intents_without_inventing_route_success(intent):
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    result["cases"] = result["cases"][:1]
    result["cases"][0]["intent"] = intent
    report = module.assess_observations(dataset, result)
    assert report["metrics"]["routing_accuracy"] == 0


def test_versioned_cases_match_the_public_deterministic_router_with_explicit_context():
    from agent_core.models import BudgetProfile, ConversationTurn, ExecutionContext, ProfileSnapshotRef
    from agent_core.routing import route_for_context

    module = evaluator()
    dataset = module.load_dataset()
    assert all("routing_context" in case for case in dataset["cases"])
    stamp = datetime(2026, 10, 25, tzinfo=timezone.utc)
    for case in dataset["cases"]:
        route = case["routing_context"]
        context = ExecutionContext(
            run_id="public-route-evaluation", conversation_id="public-route-evaluation", question=case["question"],
            language=case["language"], mode_preference=route["mode_preference"], selected_text=route["selected_text"],
            article_id="public-evaluation-article" if route["article_bound"] else None,
            conversation_topic=route["conversation_topic"],
            # Only routing is exercised: this public fixture reference does
            # not imply a canonical profile was loaded or semantically tested.
            profile_snapshot=ProfileSnapshotRef(profile_id="public-evaluation-profile", revision=1, content_hash="0" * 64)
                if route["conversation_topic"] == "who_am_i" else None,
            conversation_history=[ConversationTurn(**turn, created_at=stamp) for turn in case["history"]],
            budget_profile=BudgetProfile(name="routing-only", max_model_calls=1, max_total_tokens=128, max_duration_seconds=1),
        )
        actual = asyncio.run(route_for_context(context, router_model=None))
        assert actual.intent.value == case["intent"], case["id"]


@pytest.mark.parametrize("model", ["vendor/model:revision", "ft:base:org:sample:id", "Vendor/Model:Revision",
                                    pytest.param("x" * 256, id="maximum-length")])
def test_model_identity_supported_by_runtime_remains_exact_in_observation_report(model):
    from agent_core.adapters.config import LlmProviderSettings

    configured = LlmProviderSettings(api_key="test-only-never-sent", model=model)
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    result["model"] = configured.model
    assert module.assess_observations(dataset, result)["model"] == model


@pytest.mark.parametrize("model", ["", "vendor model", "vendor/model\nrevision", "x" * 257])
def test_observation_model_identifier_rejects_empty_controls_whitespace_and_excessive_length(model):
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    result["model"] = model
    with pytest.raises(ValueError, match="model"):
        module.assess_observations(dataset, result)


@pytest.mark.parametrize("label", ["provider", "prompt_version", "case", "source"])
def test_model_separator_support_does_not_relax_other_identifier_contracts(label):
    module = evaluator()
    dataset = module.load_dataset()
    result = observations(dataset)
    if label in {"provider", "prompt_version"}:
        result[label] = "public/label:revision"
        with pytest.raises(ValueError):
            module.assess_observations(dataset, result)
    else:
        if label == "case":
            dataset["cases"][0]["id"] = "public/case:revision"
        else:
            dataset["cases"][0]["evidence"][0]["source_id"] = "public/source:revision"
            dataset["cases"][0]["relevant_source_ids"] = ["public/source:revision"]
        with pytest.raises(ValueError):
            module.validate_dataset(dataset)


def test_evaluation_identity_never_refreshes_a_repository_index(tmp_path, monkeypatch):
    # Isolated test repository only. No workspace staging/configuration or
    # user hooks are used to reproduce a normal status cache refresh.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OPTIONAL_LOCKS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repository = tmp_path / "metadata-repository"
    repository.mkdir()
    service = repository / "src" / "services" / "ai-agent-service"
    sources = ("app/agent_core/grounding.py", "app/agent_core/qa/nodes.py", "app/agent_core/qa/runner.py",
               "tests/grounding/pipeline_expectations.json")
    for name in sources:
        source = service / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("Public identity fixture\n", encoding="utf-8")
    tracked = repository / "tracked.txt"
    tracked.write_text("Unchanged public content\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, capture_output=True, check=True, timeout=10)
    subprocess.run(["git", "add", "."], cwd=repository, capture_output=True, check=True, timeout=10)
    subprocess.run(["git", "-c", "user.name=Metadata fixture", "-c", "user.email=metadata@example.invalid",
                    "commit", "-qm", "Public identity fixture"],
                   cwd=repository, capture_output=True, check=True, timeout=10)
    index = repository / ".git" / "index"
    before = index.read_bytes(), index.stat().st_mtime_ns
    stamp = tracked.stat()
    os.utime(tracked, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 2_000_000_000))

    spec = importlib.util.spec_from_file_location("grounding_readonly_identity", SERVICE / "tools" / "grounding_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "__file__", str(service / "tools" / "grounding_acceptance.py"))
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    identity = module.evaluation_identity(cases)
    assert identity["commit"] is not None and identity["workspace_dirty"] is False
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert not (repository / ".git" / "index.lock").exists()
