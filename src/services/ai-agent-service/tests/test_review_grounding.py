"""Offline regressions for evidence binding and publication ordering."""

import asyncio
from datetime import datetime, timezone

import pytest

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy, Deadline
from agent_core.budget.store import PolicyBudgetStore
from agent_core.content.models import IndexedChunk
from agent_core.graph.nodes import TaskContext
from agent_core.models import ArticleChunk, BudgetProfile, ExecutionContext, ProgressKind, compute_content_hash
from agent_core.ports import ModelResponse, ModelUsage
from agent_core.qa.guardrails import ground_answer, neutralize_attributions, select_citations
from agent_core.qa.models import QaFlowConfig
from agent_core.qa.nodes import QaDeps, make_control, make_generate
from agent_core.analysis.models import AnalysisConfig
from agent_core.analysis.nodes import AnalysisDeps, make_control as analysis_control, make_generate as analysis_generate
from agent_core.state.artifacts import InMemoryArtifactStore


def record(text, index=0):
    return IndexedChunk(chunk=ArticleChunk(article_id="article-1", article_revision=1, chunk_index=index,
        content=text, char_start=0, char_end=len(text)), content_hash=compute_content_hash(text),
        heading_path=["Queue"], anchor="queue", canonical_url="https://example.com/posts/queue#queue")


@pytest.mark.parametrize("claim", [
    "According to the article the recommended queue size range is 9000 to 10000.",
    "The recommended queue size range is 100 to 9000.",
    "## The recommended queue size range is 9000 to 10000.",
    "The recommended queue size range is not 100 to 1000.",
    "The recommended queue size range is 1000 to 100.",
])
def test_numeric_and_negation_contradictions_cannot_receive_a_citation(claim):
    source = record("The recommended queue size range is 100 to 1000.")
    answer, cited, removed = ground_answer(claim, [source], min_overlap=3)
    assert answer == "" and cited == [] and removed == 1
    assert select_citations(claim, [source], min_overlap=3) == []


def test_attribution_check_rejects_partial_number_overlap():
    claim = "According to the article the recommended queue size range is 100 to 9000."
    answer, removed = neutralize_attributions(claim, "The recommended queue size range is 100 to 1000.")
    assert answer == "" and removed == 1


def test_turkish_negation_suffix_and_unquoted_code_identifiers_are_checked():
    source = record("Önerilen kuyruk kapasitesi 100 olmalıdır.")
    assert ground_answer("Önerilen kuyruk kapasitesi 100 olmamalıdır.", [source], min_overlap=3)[0] == ""
    source = record("The bounded queue raises QueueFull when capacity is exhausted.")
    assert ground_answer("The bounded queue raises ArbitraryError when capacity is exhausted.", [source], min_overlap=3)[0] == ""


def test_unrelated_spans_cannot_supply_a_missing_number():
    source = record("The recommended queue size range is 100 to 1000.\nAn unrelated timer has 9000 ticks.")
    assert ground_answer("The recommended queue size range is 100 to 9000.", [source], min_overlap=3)[1] == []


def test_valid_claims_keep_only_their_own_source_and_reject_unsupported_entities():
    source = record("The bounded queue raises `QueueFull` when capacity is exhausted.")
    unrelated = record("Deployment uses a remote service and PostgreSQL storage.", 1)
    valid = "The bounded queue raises `QueueFull` when capacity is exhausted."
    answer, cited, removed = ground_answer(valid, [unrelated, source], min_overlap=3)
    assert answer == valid and cited == [source] and removed == 0
    assert ground_answer(valid.replace("QueueFull", "ArbitraryError"), [source], min_overlap=3)[0] == ""


def test_only_literal_source_code_can_be_published_as_a_fenced_example():
    source = record("```python\nqueue = Queue(maxsize=100)\n```")
    valid = source.chunk.content
    assert ground_answer(valid, [source], min_overlap=3)[:2] == (valid, [source])
    assert ground_answer(valid.replace("100", "9000"), [source], min_overlap=3)[0] == ""


@pytest.mark.parametrize("analysis", [False, True])
def test_unverified_drafts_are_never_streamed_and_control_publishes_only_supported_text(analysis):
    async def scenario():
        context = ExecutionContext(run_id="grounding-run", conversation_id="grounding-conversation",
            question="What is the recommended queue size?", language="en", mode_preference="fast",
            budget_profile=BudgetProfile(name="test", max_total_tokens=20000, max_model_calls=2,
                                         max_duration_seconds=30))
        policy = BudgetPolicy.from_budget_profile(context.budget_profile)
        guard = BudgetGuard(PolicyBudgetStore(policy), policy, context.run_id)
        tasks = TaskContext(run_id=context.run_id, guard=guard, artifacts=InMemoryArtifactStore())
        draft = "The recommended queue size range is 9000 to 10000."
        emitted = []

        class Progress:
            async def publish(self, event):
                emitted.append(event)

        class Model:
            async def stream_complete(self, request, *, cancel, on_delta):
                await on_delta(draft)
                return ModelResponse(text=draft, usage=ModelUsage(prompt_tokens=100, completion_tokens=20),
                                     finished_at=datetime.now(timezone.utc))
            async def complete(self, request, *, cancel):
                import json
                result = {"segments": [{"id": "A1", "supported": False, "evidence": []}]}
                return ModelResponse(text=json.dumps(result), usage=ModelUsage(prompt_tokens=20, completion_tokens=10),
                                     finished_at=datetime.now(timezone.utc))

        source = record("The recommended queue size range is 100 to 1000.")
        kwargs = dict(context=context, route=None, retriever=None, model=Model(), content=None,
            policy=policy, guard=guard, tasks=tasks, progress=Progress(), deadline=Deadline(30))
        deps = AnalysisDeps(config=AnalysisConfig(), **kwargs) if analysis else QaDeps(config=QaFlowConfig(), **kwargs)
        generate = analysis_generate(deps) if analysis else make_generate(deps)
        control = analysis_control(deps) if analysis else make_control(deps)
        state = {"context": context, "retrieved": [source]}
        generated = await generate(state)
        assert not any(event.kind is ProgressKind.GENERATION_DELTA for event in emitted)
        controlled = await control({**state, **generated})
        assert controlled["citations"] == []
        assert "could not verify" in controlled["answer"]
        assert "9000" not in controlled["answer"]
        assert not any("9000" in event.message for event in emitted)
        assert any(event.kind is ProgressKind.GENERATION_DELTA for event in emitted)
    asyncio.run(scenario())
