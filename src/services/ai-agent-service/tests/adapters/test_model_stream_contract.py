"""Offline checks for real chat transport and end-to-end generation costs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from agent_core.adapters.config import LlmProviderSettings
from agent_core.adapters.openai_provider import MAX_EVENT_BYTES, OpenAiModelProvider
from agent_core.analysis.nodes import make_generate as analysis_generate
from agent_core.budget.guard import (
    BudgetGuard, CallResult, estimate_model_input_tokens, estimate_model_tokens,
)
from agent_core.budget.policy import BudgetPolicy, Deadline
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.graph.nodes import TaskContext
from agent_core.models import AgentMode, BudgetProfile, ExecutionContext
from agent_core.models import ArticleChunk, ArticleSnapshot, compute_content_hash
from agent_core.content.models import IndexedChunk
from agent_core.ports import BudgetKind, ModelRequest, ModelResponse, ModelUsage
from agent_core.qa.nodes import make_generate as qa_generate
from agent_core.qa.runner import run_article_qa
from agent_core.research.nodes import make_report
from agent_core.state.artifacts import InMemoryArtifactStore


def event(payload) -> str:
    return "data: " + (json.dumps(payload) if not isinstance(payload, str) else payload) + "\n\n"


def content(text="A complete answer.") -> dict:
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}


STOP = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
USAGE = {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 2000}}


def run_response(body: str, *, request: ModelRequest | None = None):
    async def run():
        sent = []

        def handle(message):
            sent.append(json.loads(message.content))
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = OpenAiModelProvider(LlmProviderSettings(api_key="test-only", model="test"), client=client)
            return await provider.complete(request or ModelRequest(prompt="Question", max_output_tokens=2500)), sent

    return asyncio.run(run())


def test_valid_stream_preserves_actual_usage_and_output_limit():
    response, sent = run_response(event(content()) + event(STOP) + event(USAGE) + event("[DONE]"))
    assert response.text == "A complete answer."
    assert response.usage.total_tokens == 3000
    assert not response.usage_estimated
    assert sent[0]["max_tokens"] == 2500


@pytest.mark.parametrize("body", [
    event(content()),  # clean HTTP EOF is still an incomplete completion
    event(content()) + event(STOP),
    event(content()) + event("[DONE]"),
    event({"error": {"message": "sensitive-provider-value"}}) + event("[DONE]"),
    event("{bad-sensitive-provider-value"),
    event(["not-an-object"]),
    event({"choices": "not-a-list"}),
    event({"choices": [None]}),
    event({"choices": [{"delta": {"content": 123}}]}),
    event(content()) + event({"choices": [{"delta": {}, "finish_reason": "length"}]}),
    event(content()) + event({"choices": [{"delta": {}, "finish_reason": "content_filter"}]}),
    event(content()) + event(STOP) + event(content("late content")) + event("[DONE]"),
    event(content()) + event(STOP) + event({"choices": [], "usage": {"prompt_tokens": True, "completion_tokens": 3}}),
    event(content()) + event(STOP) + event({"choices": [], "usage": {"prompt_tokens": -1, "completion_tokens": 3}}),
    event(STOP) + event("[DONE]"),
    "data: " + "x" * (MAX_EVENT_BYTES + 1),
])
def test_invalid_or_incomplete_stream_never_returns_success(body):
    with pytest.raises(PortError) as caught:
        run_response(body)
    assert caught.value.code is AgentErrorCode.PROVIDER_ERROR
    assert caught.value.usage_uncertain
    assert not caught.value.retryable
    assert "sensitive-provider-value" not in str(caught.value)


def test_missing_usage_estimates_actual_system_prompt_and_output():
    request = ModelRequest(prompt="question", system="System policy", max_output_tokens=50)
    response, _ = run_response(event(content("hello")) + event(STOP) + event("[DONE]"), request=request)
    assert response.usage_estimated
    assert response.usage.prompt_tokens == estimate_model_input_tokens(request)
    assert response.usage.completion_tokens == len("hello".encode("utf-8"))


def make_context():
    return ExecutionContext(
        run_id="cost-run", conversation_id="cost-conversation", question="What is the queue size?",
        language="en", budget_profile=BudgetProfile(name="cost-test", max_model_calls=2,
                                                    max_total_tokens=10000, max_duration_seconds=60),
    )


@pytest.mark.parametrize("factory,mode", [
    (qa_generate, AgentMode.FAST), (analysis_generate, AgentMode.ANALYSIS), (make_report, AgentMode.DEEP_RESEARCH),
])
def test_real_generation_nodes_commit_3000_tokens_and_bound_output(factory, mode):
    async def run():
        requests = []

        class Model:
            async def stream_complete(self, request, **kwargs):
                requests.append(request)
                return ModelResponse(text="A complete answer.", usage=ModelUsage(prompt_tokens=1000, completion_tokens=2000),
                                     finished_at=datetime.now(timezone.utc))

        context = make_context()
        policy = BudgetPolicy(max_total_tokens=10000)
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, context.run_id)
        tasks = TaskContext(run_id=context.run_id, guard=guard, artifacts=InMemoryArtifactStore())
        deps = SimpleNamespace(guard=guard, tasks=tasks, model=Model(), progress=None, deadline=None, mode=mode)
        state = {"context": context, "retrieved": [], "claims": [], "evidence_records": []}
        result = await factory(deps)(state)
        assert requests[0].max_output_tokens is not None
        assert 0 < requests[0].max_output_tokens < policy.max_total_tokens
        assert result["usage_events"][0].total_tokens == 3000
        assert not result["usage_events"][0].estimated
        assert (await store.usage(context.run_id)).committed[BudgetKind.TOKEN] == 3000
        assert not any(store.reserved_view().values())

    asyncio.run(run())


def test_remaining_budget_includes_system_input_and_caps_output():
    async def run():
        request = ModelRequest(prompt="question", system="system policy", max_output_tokens=500)
        input_bound = estimate_model_input_tokens(request)
        policy = BudgetPolicy(max_total_tokens=input_bound + 11)
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, "r")
        reservation = await store.reserve("r", BudgetKind.TOKEN, 10)
        await store.commit(reservation, 10)
        prepared = await guard.prepare_model_request(request)
        assert prepared.max_output_tokens == 1
        assert estimate_model_tokens(prepared) == input_bound + 1
        reservation = await store.reserve("r", BudgetKind.TOKEN, 1)
        await store.commit(reservation, 1)
        with pytest.raises(PortError) as caught:
            await guard.prepare_model_request(request)
        assert caught.value.code is AgentErrorCode.BUDGET_EXHAUSTED

    asyncio.run(run())


def test_token_reservation_rejection_does_not_leak_call_reservation():
    async def run():
        policy = BudgetPolicy(max_total_tokens=100)
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, "r")

        async def forbidden(_attempt):
            raise AssertionError("The provider must not be called")

        with pytest.raises(PortError):
            await guard.guarded(action_id="a", kind=BudgetKind.MODEL_CALL, call=forbidden, token_estimate=101)
        assert not any(store.reserved_view().values())
        assert (await store.usage("r")).committed == {}

    asyncio.run(run())


@pytest.mark.parametrize("failure", [
    RuntimeError("unexpected"),
    PortError(AgentErrorCode.PROVIDER_ERROR, "partial stream", usage_uncertain=True),
])
def test_unknown_provider_cost_closes_reservations_conservatively(failure):
    async def run():
        policy = BudgetPolicy(max_total_tokens=100)
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, "r")
        events = []

        async def fail(_attempt):
            raise failure

        with pytest.raises(type(failure)):
            await guard.guarded(action_id="a", kind=BudgetKind.MODEL_CALL, call=fail,
                                token_estimate=80, events_sink=events)
        assert (await store.usage("r")).committed[BudgetKind.TOKEN] == 80
        assert events[0].uncertain and events[0].estimated
        assert not any(store.reserved_view().values())

    asyncio.run(run())


def test_deadline_interrupts_an_inflight_call_and_preserves_uncertain_cost():
    async def run():
        policy = BudgetPolicy(max_total_tokens=100)
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, "r")

        async def slow(_attempt):
            await asyncio.sleep(10)

        with pytest.raises(PortError) as caught:
            await guard.guarded(action_id="a", kind=BudgetKind.MODEL_CALL, call=slow,
                                token_estimate=80, deadline=Deadline(0.01))
        assert caught.value.code is AgentErrorCode.TIMEOUT
        assert (await store.usage("r")).committed[BudgetKind.TOKEN] == 80
        assert not any(store.reserved_view().values())

    asyncio.run(run())


@pytest.mark.parametrize("fail_after_generation", [False, True])
def test_terminal_usage_keeps_actual_cost_even_when_source_control_fails(monkeypatch, fail_after_generation):
    async def run():
        text = "The recommended queue size range is between 100 and 1000."
        snapshot = ArticleSnapshot(article_id="article-1", article_revision=1, content=text,
                                   content_hash=compute_content_hash(text), title="Queue sizing", slug="queue",
                                   language="en", fetched_at=datetime.now(timezone.utc))
        record = IndexedChunk(chunk=ArticleChunk(article_id=snapshot.article_id, article_revision=1,
                                                chunk_index=0, content=text, char_start=0, char_end=len(text)),
                              content_hash=snapshot.content_hash, heading_path=["Queue sizing"], anchor="queue-sizing",
                              language="en", published=True, canonical_url="https://example.com/queue")

        class Retriever:
            async def ensure_indexed(self, *args, **kwargs):
                return None

            async def retrieve(self, *args, **kwargs):
                return [record]

        class Model:
            async def stream_complete(self, request, **kwargs):
                return ModelResponse(text=text, usage=ModelUsage(prompt_tokens=1000, completion_tokens=2000),
                                     finished_at=datetime.now(timezone.utc))

        if fail_after_generation:
            async def fail(_state):
                raise PortError(AgentErrorCode.PROVIDER_ERROR, "Source control failed after a paid call")

            monkeypatch.setattr("agent_core.qa.runner.make_control", lambda _deps: fail)
        context = make_context().model_copy(update={"article_snapshot": snapshot, "article_id": snapshot.article_id,
                                                   "article_revision": 1, "article_content_hash": snapshot.content_hash})
        result = await run_article_qa(context, None, model=Model(), retriever=Retriever())
        assert result.outcome.status.value == ("failed" if fail_after_generation else "completed")
        assert result.outcome.usage.total_tokens == 3000
        assert result.outcome.usage.model_calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("cancel_request", [False, True])
def test_chat_timeout_and_cancellation_close_the_inflight_stream(cancel_request):
    async def run():
        closed = asyncio.Event()

        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.sleep(10)
                yield b"data: [DONE]\n\n"

            async def aclose(self):
                closed.set()

        class Token:
            cancelled = False

            def raise_if_cancelled(self):
                if self.cancelled:
                    raise PortError(AgentErrorCode.CANCELLED, "Cancelled in the test")

        token = Token()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=SlowStream(), headers={"content-type": "text/event-stream"})
        )) as client:
            provider = OpenAiModelProvider(LlmProviderSettings(api_key="test-only", model="test",
                                                               request_timeout_seconds=1 if cancel_request else 0.02),
                                           client=client)
            pending = asyncio.create_task(provider.complete(ModelRequest(prompt="Question", max_output_tokens=10),
                                                              cancel=token))
            if cancel_request:
                await asyncio.sleep(0.01)
                token.cancelled = True
            with pytest.raises(PortError) as caught:
                await pending
            assert caught.value.code is (AgentErrorCode.CANCELLED if cancel_request else AgentErrorCode.TIMEOUT)
            assert closed.is_set()

    asyncio.run(run())
