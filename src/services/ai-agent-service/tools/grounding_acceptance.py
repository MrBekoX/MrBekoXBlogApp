"""Real-provider acceptance with explicit request, token, data and database limits.

Only the public corpus is sent. No dotenv discovery, service startup, schema
creation/drop or production data cleanup is performed. A passing small corpus
does not certify general answer correctness.
"""

from __future__ import annotations

import json
import asyncio
import hashlib
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx

from agent_core.adapters import EmbeddingProviderSettings, LlmProviderSettings, OpenAiEmbeddingProvider, OpenAiModelProvider
from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy, Deadline
from agent_core.budget.store import PolicyBudgetStore
from agent_core.content.anchors import fold_text
from agent_core.content.postgres import PostgresContentIndex, PostgresEmbeddingCache
from agent_core.errors import AgentErrorCode, PortError
from agent_core.grounding import GroundingEvidence, verify_answer
from agent_core.models import ArticleSnapshot, BudgetProfile, ExecutionContext, compute_content_hash
from agent_core.qa.retrieval import SnapshotRetriever
from agent_core.qa.runner import run_article_qa

MAX_CASES = 9
MAX_CHAT_TOKENS = 60000
MAX_EMBEDDING_BYTES = 32768
MAX_SECONDS = 300
PIPELINE_EXPECTATIONS = Path(__file__).resolve().parents[1] / "tests" / "grounding" / "pipeline_expectations.json"


def _source_digest(sources):
    """Bind names and byte boundaries as well as source contents."""
    digest = hashlib.sha256()
    for name, content in sorted(sources):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def evaluation_identity(cases):
    """Bind finite live evidence to source revisions without recording secrets."""
    service = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.run(["git", "--no-optional-locks", "rev-parse", "HEAD"], cwd=service,
                                capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            commit = None
        dirty = bool(subprocess.run(["git", "--no-optional-locks", "status", "--porcelain"], cwd=service,
                                   capture_output=True, text=True, timeout=5, check=True).stdout)
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    prompt_sources = ["app/agent_core/grounding.py", "app/agent_core/qa/nodes.py", "app/agent_core/qa/runner.py"]
    prompt_digest = _source_digest([(name, (service / name).read_bytes()) for name in prompt_sources])
    corpus = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    dataset_sources = ["tests/grounding/corpus.json", "tests/grounding/pipeline_expectations.json"]
    dataset_digest = _source_digest([(dataset_sources[0], corpus),
                                      (dataset_sources[1], (service / dataset_sources[1]).read_bytes())])
    return {"commit": commit, "workspace_dirty": dirty, "dataset_version": "grounding-corpus-v1",
            "dataset_sha256": dataset_digest, "dataset_source_files": dataset_sources,
            "prompt_version": "grounding-verifier-and-qa-v1", "prompt_sources_sha256": prompt_digest,
            "prompt_source_files": prompt_sources,
            "samples": len(cases), "provider": "configured-openai-compatible", "layer": "real-provider",
            "judge": "configured model verifier with finite rule checks; no independent human calibration has been measured"}


def validate_cases(cases):
    if (len(cases) != MAX_CASES or sum(case["supported"] is True for case in cases) != 3
            or any(len(case["source"].encode("utf-8")) > 512 or len(case["question"].encode("utf-8")) > 512 for case in cases)):
        raise ValueError("Acceptance requires all 9 approved cases, including 3 supported and 6 unsupported candidates")


def load_pipeline_expectations(cases):
    expected = json.loads(PIPELINE_EXPECTATIONS.read_text(encoding="utf-8"))
    if not isinstance(expected, dict) or set(expected) != {case["id"] for case in cases}:
        raise ValueError("The full-pipeline golden expectations must cover every public case")
    for rules in expected.values():
        if (rules.get("language") not in {"tr", "en"} or not isinstance(rules.get("required"), list)
                or not 1 <= len(rules["required"]) <= 4 or not isinstance(rules.get("forbidden"), list)
                or type(rules.get("answerable", True)) is not bool
                or len(rules.get("question", "").encode("utf-8")) > 512):
            raise ValueError("Full-pipeline golden checks are invalid or unbounded")
        for pattern in rules["required"]:
            if not isinstance(pattern, str) or len(pattern) > 300:
                raise ValueError("A golden check is invalid")
            re.compile(pattern)
        if len(rules["forbidden"]) > 10 or any(not isinstance(value, str) for value in rules["forbidden"]):
            raise ValueError("A forbidden-output check is invalid")
        for pattern in rules.get("forbidden_regex", []):
            if not isinstance(pattern, str) or len(pattern) > 300:
                raise ValueError("A forbidden-output pattern is invalid")
            re.compile(pattern)
    if sum(rules.get("answerable", True) is False for rules in expected.values()) < 2:
        raise ValueError("Full-pipeline acceptance requires at least two unanswerable questions")
    return expected


def gold_checks(answer, rules):
    normalized = " ".join(fold_text(answer).split())
    return (all(re.search(pattern, normalized, re.S) for pattern in rules["required"])
            and not any(value in normalized for value in rules["forbidden"])
            and not any(re.search(pattern, normalized, re.S) for pattern in rules.get("forbidden_regex", [])))


def validate_disposable_db(environ) -> str:
    if environ.get("AGENT_ACCEPTANCE_DISPOSABLE_DB") != "1":
        raise ValueError("Full-pipeline acceptance requires an explicitly disposable database")
    value = environ.get("AGENT_TEST_DB_URL", "")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"postgres", "postgresql"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                 and re.fullmatch(r"blogdb_agent_quality_test(?:_[a-zA-Z0-9_]+)?", unquote(parsed.path.removeprefix("/")))
                 and parsed.username and not parsed.fragment and not parsed.query)
        parsed.port  # reject malformed ports before any connection
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Acceptance requires an isolated loopback blogdb_agent_quality_test database URL")
    return value


class RequestLimits:
    def __init__(self, scope: str):
        self.max_chat = {"verifier": 9, "full-pipeline": 18, "all": 27}[scope]
        self.max_embedding = 0 if scope == "verifier" else 18
        self.chat = self.embedding = self.embedding_bytes = 0
        self.deadline = Deadline(MAX_SECONDS)

    async def chat_request(self, request):
        self.deadline.raise_if_exceeded()
        if self.chat >= self.max_chat:
            raise PortError(AgentErrorCode.BUDGET_EXHAUSTED, "Acceptance chat request limit reached", port="acceptance")
        self.chat += 1

    async def embedding_request(self, request):
        self.deadline.raise_if_exceeded()
        body = json.loads(request.content)
        values = body.get("input")
        values = [values] if isinstance(values, str) else values
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError("Acceptance embedding input was not a bounded text batch")
        amount = sum(len(item.encode("utf-8")) for item in values)
        if self.embedding >= self.max_embedding or self.embedding_bytes + amount > MAX_EMBEDDING_BYTES:
            raise PortError(AgentErrorCode.BUDGET_EXHAUSTED, "Acceptance embedding request/input limit reached", port="acceptance")
        self.embedding += 1
        self.embedding_bytes += amount

    def report(self):
        return {"chat_requests": self.chat, "chat_request_limit": self.max_chat,
                "embedding_requests": self.embedding, "embedding_request_limit": self.max_embedding,
                "embedding_input_bytes": self.embedding_bytes, "embedding_input_byte_limit": MAX_EMBEDDING_BYTES,
                "chat_token_limit": MAX_CHAT_TOKENS, "duration_limit_seconds": MAX_SECONDS}


async def _verify_cases(cases, model, policy, store, deadline):
    guard = BudgetGuard(store, policy, "grounding-acceptance")
    rows = []
    for case in cases:
        deadline.raise_if_exceeded()
        try:
            result = await verify_answer(answer=case["answer"], question=case["question"],
                evidence=[GroundingEvidence("S1", case["source"])], model=model, guard=guard,
                action_id="acceptance:" + case["id"], deadline=deadline)
            deadline.raise_if_exceeded()
            accepted = bool(result.answer) and not result.rejected
            rows.append({"id": case["id"], "expected": case["supported"], "accepted": accepted})
        except Exception as error:
            rows.append({"id": case["id"], "expected": case["supported"], "accepted": False,
                         "error": type(error).__name__})
    positives = [row for row in rows if row["expected"]]
    false_acceptances = sum(not row["expected"] and row["accepted"] for row in rows)
    recall = sum(row["accepted"] for row in positives) / len(positives) if positives else 0.0
    return {"kind": "fixed-candidate-verifier", "cases": rows, "false_acceptances": false_acceptances,
            "supported_recall": recall, "passed": false_acceptances == 0 and recall >= .9
            and not any("error" in row for row in rows)}


async def _pipeline_cases(cases, model, embeddings, settings, pool, store, deadline):
    expected = load_pipeline_expectations(cases)
    index = PostgresContentIndex(pool)
    cache = PostgresEmbeddingCache(pool, embeddings, settings.index_config)
    retriever = SnapshotRetriever(embedding_provider=cache, model_config=settings.index_config, index=index,
                                 canonical_url_template="https://example.invalid/quality/{slug}")
    prefix = "public-quality-" + uuid.uuid4().hex
    owned = []
    rows = []
    try:
        for number, case in enumerate(cases):
            deadline.raise_if_exceeded()
            article_id = f"{prefix}-{number}"
            owned.append(article_id)
            now = datetime.now(timezone.utc)
            snapshot = ArticleSnapshot(article_id=article_id, article_revision=1, slug=article_id,
                title="Acceptance source", content=case["source"], content_hash=compute_content_hash(case["source"]),
                language="tr" if case["id"] == "tr_to_en_backpressure" else "en", fetched_at=now)
            budget = BudgetProfile(name="acceptance", max_model_calls=2, max_total_tokens=MAX_CHAT_TOKENS,
                max_tool_calls=4, max_duration_seconds=max(min(deadline.remaining(), 60), .001))
            context = ExecutionContext(run_id="grounding-acceptance", conversation_id="public-quality",
                question=expected[case["id"]].get("question", case["question"]), language=expected[case["id"]]["language"], article_id=article_id,
                article_revision=1, article_content_hash=snapshot.content_hash, article_snapshot=snapshot,
                budget_profile=budget)
            try:
                result = await run_article_qa(context, None, model=model, retriever=retriever, store=store,
                    policy=BudgetPolicy.from_budget_profile(budget, max_attempts_per_action=1))
                deadline.raise_if_exceeded()
                answer = (result.outcome.answer or "").split("\n\nKaynak bölümü:", 1)[0]
                rules = expected[case["id"]]
                gold = gold_checks(answer, rules)
                answerable = rules.get("answerable", True)
                citation_gate = bool(result.outcome.citations) if answerable else not result.outcome.citations
                passed = result.outcome.status.value == "completed" and citation_gate and bool(gold)
                rows.append({"id": case["id"], "status": result.outcome.status.value,
                    "answerable": answerable, "citations": len(result.outcome.citations), "gold_checks_pass": bool(gold), "passed": passed,
                    "answer": answer, "chat_tokens": result.outcome.usage.total_tokens})
            except Exception as error:
                rows.append({"id": case["id"], "passed": False, "error": type(error).__name__})
    finally:
        # Only IDs allocated by this invocation are deleted. No database, schema,
        # shared vector cache or pre-existing article can be removed here.
        if owned:
            await asyncio.wait_for(pool.execute("DELETE FROM agent.content_articles WHERE article_id=ANY($1::text[])", owned), timeout=5)
    return {"kind": "real-generation-embedding-postgres-retrieval-verification", "cases": rows,
            "passed": len(rows) == len(cases) and all(row["passed"] for row in rows),
            "interpretation": "Finite golden checks and public answers for human review, not general semantic certification"}


async def run_acceptance(cases, scope):
    if os.environ.get("AGENT_RUN_PAID_TESTS") != "1":
        raise ValueError("Paid provider acceptance was not explicitly enabled")
    validate_cases(cases)
    if scope != "verifier":
        load_pipeline_expectations(cases)  # preflight before database or paid requests
    db_url = validate_disposable_db(os.environ) if scope != "verifier" else None
    limits = RequestLimits(scope)
    policy = BudgetPolicy(max_model_calls=limits.max_chat, max_total_tokens=MAX_CHAT_TOKENS,
                          max_duration_seconds=MAX_SECONDS, max_attempts_per_action=1)
    store = PolicyBudgetStore(policy)
    results = []
    pool = None
    async def work():
        nonlocal pool
        if db_url:
            pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2, command_timeout=10, timeout=10)
            tables = await pool.fetchrow("SELECT to_regclass('agent.content_articles') AS articles, "
                                        "to_regclass('agent.content_chunks') AS chunks, to_regclass('agent.embedding_cache') AS cache")
            if not all(tables.values()):
                raise ValueError("The dedicated acceptance database must be migrated before any paid calls")
        async with httpx.AsyncClient(event_hooks={"request": [limits.chat_request]}) as chat_client:
            model = OpenAiModelProvider(LlmProviderSettings.from_env(dict(os.environ)), client=chat_client)
            if scope in {"verifier", "all"}:
                results.append(await _verify_cases(cases, model, policy, store, limits.deadline))
            if pool is not None:
                async with httpx.AsyncClient(event_hooks={"request": [limits.embedding_request]}) as embedding_client:
                    settings = EmbeddingProviderSettings.from_env(dict(os.environ))
                    embeddings = OpenAiEmbeddingProvider(settings, client=embedding_client)
                    results.append(await _pipeline_cases(cases, model, embeddings, settings, pool, store, limits.deadline))
    try:
        # A pre-request deadline alone does not cancel an embedding response
        # that outlives the remaining time. Bound all acceptance work itself.
        timeout_scope = asyncio.timeout(MAX_SECONDS)
        async with timeout_scope:
            await work()
        if timeout_scope.expired():
            raise TimeoutError("Acceptance deadline expired even though a child suppressed cancellation")
        limits.deadline.raise_if_exceeded()
    finally:
        if pool is not None:
            try:
                await asyncio.wait_for(pool.close(), timeout=5)
            except TimeoutError:
                pool.terminate()
    usage = await store.usage("grounding-acceptance")
    return {"scope": scope, "model": os.environ.get("AGENT_LLM_MODEL"), "identity": evaluation_identity(cases), "results": results,
            "limits": limits.report(), "charged_chat_tokens": usage.committed.get("token", 0),
            "passed": bool(results) and all(result["passed"] for result in results),
            "coverage": "Public verifier corpus and/or real QA provider pipeline only; browser, cross-service broker and EC2 capacity are separate"}
