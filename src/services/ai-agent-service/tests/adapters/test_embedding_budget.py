"""Real embedding transport accounting with offline HTTP protocol fixtures."""

import asyncio
import json

import httpx
import pytest

from agent_core.adapters import EmbeddingProviderSettings, OpenAiEmbeddingProvider
from agent_core.budget.embedding import embedding_budget_scope
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind


def provider_with_transport(handler):
    provider = OpenAiEmbeddingProvider(EmbeddingProviderSettings(api_key="test-only"))
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


def response_for(request, tokens=3):
    count = len(json.loads(request.content)["input"])
    payload = {
        "model": "text-embedding-3-small",
        "data": [{"index": index, "embedding": [1.0] + [0.0] * 1535} for index in range(count)],
    }
    if tokens is not None:
        payload["usage"] = {"prompt_tokens": tokens, "total_tokens": tokens}
    return httpx.Response(200, json=payload)


def test_embedding_reported_usage_is_committed_to_its_run_before_return():
    async def scenario():
        store = PolicyBudgetStore(BudgetPolicy(max_total_tokens=100))
        provider = provider_with_transport(response_for)
        try:
            with embedding_budget_scope("embedding-run", store) as accounting:
                await provider.embed(["Embedding input"])
            assert (await store.usage("embedding-run")).committed.get(BudgetKind.TOKEN) == 3
            assert accounting.requests == 1
            assert accounting.reported_tokens == 3
            assert accounting.estimated_tokens == accounting.uncertain_tokens == 0
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_embedding_budget_exhaustion_prevents_the_http_request():
    async def scenario():
        sent = []
        def handle(request):
            sent.append(request)
            return response_for(request)
        provider = provider_with_transport(handle)
        store = PolicyBudgetStore(BudgetPolicy(max_total_tokens=5))
        try:
            with embedding_budget_scope("small-run", store):
                with pytest.raises(PortError) as caught:
                    await provider.embed(["Input exceeding five bytes"])
            assert caught.value.code is AgentErrorCode.BUDGET_EXHAUSTED
            assert sent == []
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_missing_embedding_usage_is_an_explicit_conservative_estimate():
    async def scenario():
        store = PolicyBudgetStore(BudgetPolicy(max_total_tokens=100))
        provider = provider_with_transport(lambda request: response_for(request, tokens=None))
        text = "ş🙂 input"
        try:
            with embedding_budget_scope("estimate-run", store) as accounting:
                await provider.embed([text])
            expected = len(text.encode("utf-8"))
            assert (await store.usage("estimate-run")).committed[BudgetKind.TOKEN] == expected
            assert accounting.estimated_tokens == expected and accounting.reported_tokens == 0
            assert accounting.uncertain_tokens == 0
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_retry_after_provider_failure_consumes_another_reservation():
    async def scenario():
        attempts = []
        def handle(request):
            attempts.append(1)
            return httpx.Response(429) if len(attempts) == 1 else response_for(request)
        provider = provider_with_transport(handle)
        store = PolicyBudgetStore(BudgetPolicy(max_total_tokens=100))
        try:
            with embedding_budget_scope("retry-run", store) as accounting:
                with pytest.raises(PortError) as caught:
                    await provider.embed(["Input"])
                assert caught.value.retryable
                await provider.embed(["Input"])
            assert accounting.requests == 2
            assert accounting.reported_tokens == 3
            assert accounting.estimated_tokens == accounting.uncertain_tokens == len("Input")
            assert (await store.usage("retry-run")).committed[BudgetKind.TOKEN] == len("Input") + 3
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_cancelled_embedding_is_charged_and_no_reservation_is_refunded():
    async def scenario():
        started = asyncio.Event()
        async def handle(request):
            started.set()
            await asyncio.Event().wait()
        provider = provider_with_transport(handle)
        store = PolicyBudgetStore(BudgetPolicy(max_total_tokens=100))
        try:
            with embedding_budget_scope("cancelled-run", store) as accounting:
                pending = asyncio.create_task(provider.embed(["Input"]))
                await asyncio.wait_for(started.wait(), timeout=2)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            assert (await store.usage("cancelled-run")).committed[BudgetKind.TOKEN] == len("Input")
            assert accounting.uncertain_tokens == len("Input")
            assert not any(store.reserved_view().values())
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_production_embedding_without_a_budget_owner_does_not_send_http():
    async def scenario():
        provider = OpenAiEmbeddingProvider(EmbeddingProviderSettings(api_key="test-only"), require_budget_scope=True)
        with pytest.raises(PortError) as caught:
            await provider.embed(["Input"])
        assert caught.value.code is AgentErrorCode.CONFIG_ERROR
        assert provider._client is None

    asyncio.run(scenario())


def test_reported_embedding_usage_survives_a_lost_ledger_ack_without_retry():
    class FailingStore(PolicyBudgetStore):
        async def commit(self, reservation, actual_amount):
            raise PortError(AgentErrorCode.PROVIDER_ERROR, "Lost acknowledgement", retryable=True)

    async def scenario():
        provider = provider_with_transport(response_for)
        store = FailingStore(BudgetPolicy(max_total_tokens=100))
        try:
            with embedding_budget_scope("lost-ack-run", store) as accounting:
                with pytest.raises(PortError) as caught:
                    await provider.embed(["Input"])
            assert not caught.value.retryable and caught.value.usage_uncertain
            assert accounting.reported_tokens == 3 and accounting.requests == 1
            assert (await store.usage("lost-ack-run")).reserved[BudgetKind.TOKEN] == len("Input")
        finally:
            await provider.aclose()

    asyncio.run(scenario())
