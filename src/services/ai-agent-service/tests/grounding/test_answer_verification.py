"""Offline protocol/pipeline regressions; stub verdicts are not model-quality evidence."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy, Deadline
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.grounding import GroundingEvidence, _parse_verdict, answer_is_covered, split_answer, verify_answer
from agent_core.models import ArticleChunk, ArticleSnapshot, BudgetProfile, ExecutionContext, ProgressKind, compute_content_hash
from agent_core.ports import ModelResponse, ModelUsage
from agent_core.content.index import IndexResult
from agent_core.content.models import IndexedChunk
from agent_core.qa.runner import run_article_qa
from agent_core.qa.guardrails import ground_answer
from agent_core.profile.chunking import ProfileChunk
from agent_core.profile.validation import EvidenceEntry, validate_model_output
from agent_core.models import SourceReference

NOW = datetime.now(timezone.utc)
CORPUS = json.loads((Path(__file__).parent / "corpus.json").read_text(encoding="utf-8"))


def response(text):
    return ModelResponse(text=text, usage=ModelUsage(prompt_tokens=100, completion_tokens=50), finished_at=NOW)


def verdict(answer, source, *, supported):
    return {"segments": [{"id": segment.id, "supported": supported,
        "evidence": [{"source": "S1", "quote": source}] if supported else []}
        for segment in split_answer(answer)]}


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case["id"])
def test_verifier_protocol_preserves_bilingual_paraphrases_and_rejects_negative_verdicts(case):
    class Model:
        async def complete(self, request, *, cancel):
            payload = json.loads(request.prompt)
            assert payload["question"] == case["question"]
            assert request.max_output_tokens > 0
            assert request.temperature is None
            return response(json.dumps(verdict(case["answer"], case["source"], supported=case["supported"])))

    async def scenario():
        policy = BudgetPolicy(max_total_tokens=20000)
        guard = BudgetGuard(PolicyBudgetStore(policy), policy, "verify-contract")
        checked = await verify_answer(answer=case["answer"], question=case["question"],
            evidence=[GroundingEvidence("S1", case["source"])], model=Model(), guard=guard,
            action_id="verify", deadline=Deadline(10))
        assert bool(checked.answer) is case["supported"]
        if case["supported"]:
            assert checked.answer == case["answer"] and checked.labels == ["S1"]
        assert checked.events[0].total_tokens == 150
    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "changed_id", "unknown_source", "invented_quote"])
def test_verdict_cannot_change_coverage_or_invent_evidence(mutation):
    answer = "The first queue blocks producers. The second queue stores pending work."
    source = "The first queue blocks producers. The second queue stores pending work."
    data = verdict(answer, source, supported=True)
    if mutation == "missing": data["segments"].pop()
    if mutation == "duplicate": data["segments"][1]["id"] = "A1"
    if mutation == "changed_id": data["segments"][0]["id"] = "A9"
    if mutation == "unknown_source": data["segments"][0]["evidence"][0]["source"] = "S99"
    if mutation == "invented_quote": data["segments"][0]["evidence"][0]["quote"] = "An invented quotation."
    if mutation in {"missing", "duplicate", "changed_id"}:
        with pytest.raises(PortError):
            _parse_verdict(json.dumps(data), split_answer(answer), [GroundingEvidence("S1", source)])
    else:
        result = _parse_verdict(json.dumps(data), split_answer(answer), [GroundingEvidence("S1", source)])
        assert "A1" in result.rejected


@pytest.mark.parametrize("case_id", ["numeric_fabrication", "range_reversal", "invented_link"])
def test_deterministic_gates_reject_invalid_numbers_and_links_even_if_judge_says_supported(case_id):
    case = next(case for case in CORPUS if case["id"] == case_id)
    result = _parse_verdict(json.dumps(verdict(case["answer"], case["source"], supported=True)),
                           split_answer(case["answer"]), [GroundingEvidence("S1", case["source"])])
    assert result.answer == "" and result.rejected


def test_profile_answer_cannot_hide_an_unrelated_sentence_behind_a_valid_claim():
    text = "Avery writes software and maintains public repositories."
    chunk = ProfileChunk(source_id="test-source", section_id="intro", chunk_index=0, text=text,
        content_hash=compute_content_hash(text), heading_path=["Introduction"], title="Introduction",
        anchor="intro", kind="text", token_count=20)
    output = json.dumps({"answer": "Avery is a licensed cardiac surgeon.",
        "claims": [{"text": text, "sources": ["S1"], "quotes": [text]}]})
    checked = validate_model_output(output, [EvidenceEntry("S1", chunk)], channel_urls=[], known_section_ids=frozenset({"intro"}))
    assert not checked.ok and any("covered" in error for error in checked.errors)


def test_claim_coverage_accepts_markdown_presentation_without_reordering_facts():
    assert answer_is_covered("- First queue blocks producers.\n- Second queue stores pending work.",
                             ["First queue blocks producers.", "Second queue stores pending work."])
    assert not answer_is_covered("First queue blocks producers. An unrelated assertion.", ["First queue blocks producers."])


def test_article_claim_alone_cannot_establish_researched_external_truth():
    source = "The recommended queue size is 9000."
    answer = "The recommended queue size is 9000."
    raw = {"segments": [{"id": "A1", "supported": True,
                          "evidence": [{"source": "A1", "quote": source}]}]}
    result = _parse_verdict(json.dumps(raw), split_answer(answer), [GroundingEvidence("A1", source, role="article_claim")])
    assert not result.answer
    attributed = "The article recommends a queue size of 9000."
    result = _parse_verdict(json.dumps(raw), split_answer(attributed), [GroundingEvidence("A1", source, role="article_claim")])
    assert result.answer == attributed


def test_literal_code_block_can_use_one_nontrivial_quote_without_requoting_every_constant():
    body = "# An approved source code example\n" + "\n".join(f"value_{index} = {index}" for index in range(70))
    source = "```python\n" + body + "\n```"
    raw = {"segments": [{"id": "A1", "supported": True,
        "evidence": [{"source": "S1", "quote": "An approved source code example"}]}]}
    result = _parse_verdict(json.dumps(raw), split_answer(source), [GroundingEvidence("S1", source)])
    assert result.answer == source


def test_actual_qa_graph_accepts_cross_language_evidence_without_literal_question_overlap():
    case = CORPUS[0]
    snapshot = ArticleSnapshot(article_id="article-1", article_revision=1, slug="queue", title="Kuyruk davranışı",
        content=case["source"], content_hash=compute_content_hash(case["source"]), fetched_at=NOW)
    record = IndexedChunk(chunk=ArticleChunk(article_id=snapshot.article_id, article_revision=1, chunk_index=0,
        content=snapshot.content, char_start=0, char_end=len(snapshot.content)), content_hash=snapshot.content_hash,
        heading_path=[snapshot.title], anchor="queue", language="tr")
    context = ExecutionContext(run_id="cross-language", conversation_id="conversation", question=case["question"],
        language="en", article_id=snapshot.article_id, article_revision=1, article_content_hash=snapshot.content_hash,
        article_snapshot=snapshot, budget_profile=BudgetProfile(name="test", max_model_calls=4,
            max_total_tokens=24000, max_tool_calls=8, max_duration_seconds=30))
    published = []

    class Progress:
        async def publish(self, event): published.append(event)

    class Retriever:
        async def ensure_indexed(self, *args, **kwargs): return IndexResult(snapshot.article_id, 1, 1, False)
        async def retrieve(self, *args, **kwargs): return [record]

    class Model:
        async def stream_complete(self, request, *, cancel, on_delta):
            await on_delta(case["answer"])
            assert not any(event.kind is ProgressKind.GENERATION_DELTA for event in published)
            return response(case["answer"])
        async def complete(self, request, *, cancel):
            assert not any(event.kind is ProgressKind.GENERATION_DELTA for event in published)
            return response(json.dumps(verdict(case["answer"], case["source"], supported=True)))

    result = asyncio.run(run_article_qa(context, None, model=Model(), retriever=Retriever(), progress=Progress()))
    assert case["answer"] in result.outcome.answer
    assert len(result.outcome.citations) == 1 and result.outcome.usage.total_tokens == 300
    assert any(event.kind is ProgressKind.GENERATION_DELTA for event in published)


def test_literal_fast_filter_does_not_authorize_reversed_subjects():
    case = next(case for case in CORPUS if case["id"] == "subject_object_reversal")
    record = IndexedChunk(chunk=ArticleChunk(article_id="article", article_revision=1, chunk_index=0,
        content=case["source"], char_start=0, char_end=len(case["source"])), content_hash=compute_content_hash(case["source"]),
        heading_path=["Cache"], anchor="cache")
    assert ground_answer(case["answer"], [record], min_overlap=3)[0] == ""


@pytest.mark.parametrize("malformed", [False, True])
def test_research_summary_checks_actual_claims_before_stream_and_completion(malformed):
    from agent_core.research.nodes import ResearchDeps, make_control, make_finalize
    from agent_core.research.models import ClaimEvidenceRecord, ClaimRecord, CoverageAssessment, ResearchFlowConfig, SourceLedgerEntry, SupportKind
    from agent_core.graph.nodes import TaskContext
    from agent_core.state.artifacts import InMemoryArtifactStore
    source = "The recommended queue size is 1000 and the source guide documents the upper limit."
    draft = "The recommended queue size is 900000; pay at https://invented.invalid/checkout."
    context = ExecutionContext(run_id="research-verification", conversation_id="research-conversation",
        question="What queue size does the guide recommend?", language="en",
        budget_profile=BudgetProfile(name="test", max_model_calls=4, max_total_tokens=24000,
                                     max_tool_calls=8, max_web_search_calls=4, max_duration_seconds=30))
    policy = BudgetPolicy.from_budget_profile(context.budget_profile)
    guard = BudgetGuard(PolicyBudgetStore(policy), policy, context.run_id)
    tasks = TaskContext(run_id=context.run_id, guard=guard, artifacts=InMemoryArtifactStore())
    entry = SourceLedgerEntry(source_id=SourceReference(kind="web", url="https://example.com/guide", accessed_at=NOW).source_id,
        url="https://example.com/guide", final_url="https://example.com/guide", title="Guide", accessed_at=NOW,
        content_hash=compute_content_hash(source), artifact_id="artifact-1")
    claim = ClaimRecord(claim_id="claim-1", article_id="article-1", article_revision=1,
        text=source, char_start=0, char_end=len(source))
    evidence = ClaimEvidenceRecord(evidence_id="ev-1", claim_id=claim.claim_id, source_id=entry.source_id,
        url=entry.final_url, excerpt=source, char_start=0, char_end=len(source),
        source_content_hash=entry.content_hash, support=SupportKind.SUPPORTS, rationale="Exact verified source span")
    events = []

    class Progress:
        async def publish(self, event): events.append(event)

    class Model:
        async def complete(self, request, *, cancel):
            if request.metadata.get("flow") == "evidence_relation_verification":
                return response(json.dumps({"relations": [{"id": "R0", "relation": "supports", "quote": source}]}))
            # Even a wrong semantic verdict cannot authorize new numbers/URLs.
            return response("{}" if malformed else json.dumps(verdict(draft, source, supported=True)))

    deps = ResearchDeps(context=context, route=None, model=Model(), tools={}, content=None, policy=policy,
        guard=guard, tasks=tasks, config=ResearchFlowConfig(), deadline=Deadline(30), progress=Progress())
    state = {"context": context, "claims": [claim], "evidence": [evidence], "sources": [entry],
        "coverage": CoverageAssessment(round=1), "draft_summary": draft}

    async def scenario():
        checked = await make_control(deps)(state)
        final = (await make_finalize(deps)({**state, **checked}))["outcome"]
        assert final.status.value == "partial"
        assert "900000" not in final.report and "invented.invalid" not in final.report
        assert final.usage.total_tokens == 300
        assert not any("900000" in event.message or "invented.invalid" in event.message for event in events)
    asyncio.run(scenario())


def test_profile_runner_abstains_when_claim_quote_is_real_but_claim_meaning_is_false():
    from agent_core.models import AgentMode, ConversationTopic, RouteDecision
    from agent_core.profile import CanonicalProfileRepository
    from agent_core.profile.runner import run_profile_rag
    directory = Path(__file__).resolve().parents[4] / "content" / "author-profile"
    repository = CanonicalProfileRepository(directory)
    snapshot = repository.active_snapshot()
    context = ExecutionContext(run_id="profile-semantic", conversation_id="profile-conversation",
        question="Sample eğitim geçmişi nedir?", language="en", conversation_topic=ConversationTopic.WHO_AM_I,
        profile_snapshot=snapshot, budget_profile=BudgetProfile(name="test", max_model_calls=6,
            max_total_tokens=32000, max_duration_seconds=30))
    route = RouteDecision(run_id=context.run_id, selected_mode=AgentMode.FAST, reason="profile", requires_web_search=False, decided_at=NOW)
    false_answer = "Sample is a licensed cardiac surgeon."

    class Model:
        async def complete(self, request, *, cancel):
            if request.metadata.get("flow") == "evidence_verification":
                return response(json.dumps(verdict(false_answer, "", supported=False)))
            return response(json.dumps({"answer": false_answer, "claims": [{"text": false_answer,
                "sources": ["S1"], "quotes": ["Demo University, Bilgisayar Mühendisliği"]}]}))

    result = asyncio.run(run_profile_rag(context, route, model=Model(), knowledge=repository))
    assert "cardiac surgeon" not in (result.outcome.answer or "")
    assert not result.outcome.citations
    assert result.state["path"] in {"validation_failed", "abstained"}
    assert result.outcome.usage.model_calls == 4


def test_profile_verifier_receives_approved_asof_year_absent_from_body():
    from agent_core.models import AgentMode, ConversationTopic, RouteDecision
    from agent_core.profile import CanonicalProfileRepository
    from agent_core.profile.runner import run_profile_rag
    from agent_core.profile.chunking import chunk_document
    directory = Path(__file__).resolve().parents[4] / "content" / "author-profile"
    repository = CanonicalProfileRepository(directory)
    snapshot = repository.active_snapshot()
    document = repository.load(snapshot)
    education = next(chunk for chunk in chunk_document(document) if chunk.section_id == "education" and chunk.chunk_index == 0)
    assert education.as_of == "2026-01-01" and "2026" not in education.evidence_text
    context = ExecutionContext(run_id="profile-asof", conversation_id="profile-conversation",
        question="What did Sample study?", language="en", conversation_topic=ConversationTopic.WHO_AM_I,
        profile_snapshot=snapshot, budget_profile=BudgetProfile(name="test", max_model_calls=4,
            max_total_tokens=32000, max_duration_seconds=30))
    route = RouteDecision(run_id=context.run_id, selected_mode=AgentMode.FAST, reason="profile", requires_web_search=False, decided_at=NOW)
    answer = "As of 2026, Sample's profile states that he studied Computer Engineering at Demo University."
    body_quote = "Demo University, Bilgisayar Mühendisliği"
    calls = []

    class Model:
        async def complete(self, request, *, cancel):
            calls.append(request.metadata.get("flow"))
            if request.metadata.get("flow") == "evidence_verification":
                data = json.loads(request.prompt)
                source = next(item for item in data["sources"] if body_quote in item["text"])
                assert "beyan tarihi: 2026-01-01" in source["text"]
                return response(json.dumps({"segments": [{"id": "A1", "supported": True, "evidence": [
                    {"source": source["id"], "quote": "beyan tarihi: 2026-01-01"},
                    {"source": source["id"], "quote": body_quote}]}]}))
            return response(json.dumps({"answer": answer, "claims": [{"text": answer,
                "sources": ["S1"], "quotes": [body_quote]}]}))

    result = asyncio.run(run_profile_rag(context, route, model=Model(), knowledge=repository))
    assert result.state["path"] == "rag" and result.outcome.answer == answer
    assert result.outcome.citations and calls == ["profile_rag", "evidence_verification"]
