"""The public quality corpus is executable; paid acceptance is never automatic."""

import json
import os
from pathlib import Path
import subprocess
import sys
import asyncio
import importlib.util

import httpx
import pytest


SERVICE = Path(__file__).resolve().parents[2]


def acceptance_module():
    spec = importlib.util.spec_from_file_location("grounding_acceptance_test", SERVICE / "tools" / "grounding_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_evaluation_only_checks_public_corpus_without_provider_configuration():
    env = {key: value for key, value in os.environ.items() if not key.startswith("AGENT_LLM_")}
    env["AGENT_RUN_PAID_TESTS"] = "0"
    result = subprocess.run([sys.executable, str(SERVICE / "tools" / "evaluate_grounding.py"), "--check-corpus"],
        env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["corpus_valid"] and output["cases"] >= 9 and output["provider_calls"] == 0


def test_real_provider_evaluation_requires_both_opt_ins():
    env = dict(os.environ, AGENT_RUN_PAID_TESTS="0")
    result = subprocess.run([sys.executable, str(SERVICE / "tools" / "evaluate_grounding.py"), "--allow-paid-provider-calls"],
        env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "owner authorization" in result.stderr


@pytest.mark.parametrize("url", ["postgresql://user:secret@localhost/blogdb_dev",
    "postgresql://user:secret@production.example/blogdb_agent_quality_test",
    "postgresql://user:secret@localhost/blogdb_agent_quality_test?sslmode=disable"])
def test_acceptance_never_uses_shared_or_remote_database(url):
    module = acceptance_module()
    with pytest.raises(ValueError) as caught:
        module.validate_disposable_db({"AGENT_ACCEPTANCE_DISPOSABLE_DB": "1", "AGENT_TEST_DB_URL": url})
    assert "secret" not in str(caught.value)


def test_full_acceptance_requires_explicit_disposable_database_assertion():
    module = acceptance_module()
    url = "postgresql://user:secret@127.0.0.1:25432/blogdb_agent_quality_test_123"
    with pytest.raises(ValueError): module.validate_disposable_db({"AGENT_TEST_DB_URL": url})
    assert module.validate_disposable_db({"AGENT_ACCEPTANCE_DISPOSABLE_DB": "1", "AGENT_TEST_DB_URL": url}) == url


def test_real_request_hooks_enforce_aggregate_counts_and_embedding_bytes_before_network():
    module = acceptance_module()

    async def scenario():
        limits = module.RequestLimits("verifier")
        request = httpx.Request("POST", "https://provider.invalid/chat", json={})
        for _ in range(9): await limits.chat_request(request)
        with pytest.raises(Exception, match="request limit"): await limits.chat_request(request)
        assert limits.chat == 9
        embedding = httpx.Request("POST", "https://provider.invalid/embeddings", json={"input": ["source text"]})
        with pytest.raises(Exception, match="request/input"): await limits.embedding_request(embedding)
        assert limits.embedding == 0
        limits = module.RequestLimits("all")
        too_large = httpx.Request("POST", "https://provider.invalid/embeddings", json={"input": ["x" * 32769]})
        with pytest.raises(Exception, match="request/input"): await limits.embedding_request(too_large)
        assert limits.embedding == limits.embedding_bytes == 0
    asyncio.run(scenario())


def test_corpus_gate_requires_all_scenarios_including_two_unanswerable_pipeline_questions():
    module = acceptance_module()
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    module.validate_cases(cases)
    with pytest.raises(ValueError): module.validate_cases(cases[:-1])
    expected = module.load_pipeline_expectations(cases)
    assert sum(not rules.get("answerable", True) for rules in expected.values()) >= 2


@pytest.mark.parametrize("answer", ["Redis does not replace Postgres.", "Redis doesn't replace Postgres.",
    "Postgres is not replaced by Redis.", "It is false that Redis replaces Postgres."])
def test_role_gold_cannot_pass_opposite_polarity(answer):
    module = acceptance_module()
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    rules = module.load_pipeline_expectations(cases)["subject_object_reversal"]
    assert not module.gold_checks(answer, rules)
    assert module.gold_checks("Redis replaces Postgres in the caching layer.", rules)


@pytest.mark.parametrize("suppress_cancel", [False, True])
def test_acceptance_hard_deadline_cancels_work_and_still_closes_pool(monkeypatch, suppress_cancel):
    module = acceptance_module()
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("AGENT_RUN_PAID_TESTS", "1")
    monkeypatch.setenv("AGENT_ACCEPTANCE_DISPOSABLE_DB", "1")
    monkeypatch.setenv("AGENT_TEST_DB_URL", "postgresql://test:test@localhost/blogdb_agent_quality_test")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "test-only-never-sent")
    monkeypatch.setenv("AGENT_LLM_MODEL", "test-only-never-called")
    monkeypatch.setenv("AGENT_EMBEDDING_API_KEY", "test-only-never-sent")
    monkeypatch.setattr(module, "MAX_SECONDS", .02)
    class Pool:
        closed = False
        async def fetchrow(self, *args): return {"articles": "a", "chunks": "c", "cache": "e"}
        async def close(self): self.closed = True
    pool = Pool()
    async def connect(*args, **kwargs): return pool
    async def wait(*args, **kwargs):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            if not suppress_cancel: raise
            return {"passed": True}
    monkeypatch.setattr(module.asyncpg, "create_pool", connect)
    monkeypatch.setattr(module, "_pipeline_cases", wait)
    monkeypatch.setattr(module, "OpenAiModelProvider", lambda *args, **kwargs: object())
    monkeypatch.setattr(module, "OpenAiEmbeddingProvider", lambda *args, **kwargs: object())
    with pytest.raises(TimeoutError):
        asyncio.run(module.run_acceptance(cases, "full-pipeline"))
    assert pool.closed
