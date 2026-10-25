"""Acceptance client composition with offline HTTP protocol fixtures only."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from agent_core.adapters import EmbeddingProviderSettings, OpenAiEmbeddingProvider, OpenAiModelProvider
from agent_core.budget.embedding import embedding_budget_scope
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind


SERVICE = Path(__file__).resolve().parents[2]


def acceptance_module():
    spec = importlib.util.spec_from_file_location("grounding_acceptance_client_contract", SERVICE / "tools" / "grounding_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def embedding_response(request):
    count = len(json.loads(request.content)["input"])
    return httpx.Response(200, json={
        "model": "text-embedding-3-small",
        "data": [{"index": index, "embedding": [1.0] + [0.0] * 1535} for index in range(count)],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    })


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("This client contract test must never use a real network transport")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


def test_public_acceptance_composition_uses_the_injected_embedding_client_and_request_limit_hook(monkeypatch):
    module = acceptance_module()
    cases = json.loads((SERVICE / "tests" / "grounding" / "corpus.json").read_text(encoding="utf-8"))
    source = "Public corpus protocol fixture"
    for key, value in {
        "AGENT_RUN_PAID_TESTS": "1", "AGENT_ACCEPTANCE_DISPOSABLE_DB": "1",
        "AGENT_TEST_DB_URL": "postgresql://test:test@localhost/blogdb_agent_quality_test_client_contract",
        "AGENT_LLM_API_KEY": "test-only-never-sent", "AGENT_LLM_MODEL": "configured-model",
        "AGENT_LLM_BASE_URL": "https://provider.invalid/v1",
        "AGENT_EMBEDDING_API_KEY": "test-only-never-sent", "AGENT_EMBEDDING_BASE_URL": "https://provider.invalid/v1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "MAX_EMBEDDING_BYTES", len(source.encode("utf-8")))
    sent, clients = [], []
    original_client = httpx.AsyncClient

    def handle(request):
        sent.append(request)
        return embedding_response(request)

    def client_factory(**kwargs):
        client = original_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    class Pool:
        closed = False
        async def fetchrow(self, *args):
            return {"articles": "a", "chunks": "c", "cache": "e"}
        async def close(self):
            self.closed = True

    pool = Pool()
    async def connect(*args, **kwargs):
        return pool

    async def pipeline_probe(cases, model, embeddings, settings, pool, store, deadline):
        # Exercise the actual acceptance composition and provider transport.
        # Storage/retrieval/generation are outside this protocol fixture.
        assert isinstance(model, OpenAiModelProvider)
        assert isinstance(embeddings, OpenAiEmbeddingProvider)
        assert len(await embeddings.embed([source])) == 1
        with pytest.raises(PortError) as exhausted:
            await embeddings.embed(["x"])
        assert exhausted.value.code is AgentErrorCode.BUDGET_EXHAUSTED
        return {"passed": True, "kind": "offline-client-protocol-fixture"}

    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(module.asyncpg, "create_pool", connect)
    monkeypatch.setattr(module, "_pipeline_cases", pipeline_probe)
    result = asyncio.run(module.run_acceptance(cases, "full-pipeline"))
    assert result["passed"]
    assert result["limits"]["embedding_requests"] == 1
    assert result["limits"]["embedding_input_bytes"] == len(source.encode("utf-8"))
    assert len(sent) == 1 and sent[0].url.path.endswith("/embeddings")
    assert pool.closed and len(clients) == 2 and all(client.is_closed for client in clients)


def test_injected_embedding_client_keeps_budget_guard_hooks_and_caller_lifecycle():
    module = acceptance_module()
    async def scenario():
        sent = []
        limits = module.RequestLimits("full-pipeline")
        async def handle(request):
            sent.append(request)
            return embedding_response(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), event_hooks={"request": [limits.embedding_request]}) as client:
            provider = OpenAiEmbeddingProvider(
                EmbeddingProviderSettings(api_key="test-only", base_url="https://provider.invalid/v1"),
                client=client, require_budget_scope=True,
            )
            with pytest.raises(PortError) as unowned:
                await provider.embed(["source"])
            assert unowned.value.code is AgentErrorCode.CONFIG_ERROR
            assert sent == [] and limits.embedding == 0
            store = PolicyBudgetStore(BudgetPolicy(max_total_tokens=100))
            with embedding_budget_scope("client-owned-run", store) as accounting:
                assert len(await provider.embed(["source"])) == 1
            assert limits.embedding == 1 and accounting.reported_tokens == 3
            assert (await store.usage("client-owned-run")).committed[BudgetKind.TOKEN] == 3
            await provider.aclose()
            await provider.aclose()
            assert not client.is_closed
        assert client.is_closed

    asyncio.run(scenario())


def test_default_embedding_client_is_lazy_and_closed_by_the_provider():
    async def scenario():
        provider = OpenAiEmbeddingProvider(EmbeddingProviderSettings(api_key="test-only"))
        assert provider._client is None
        client = provider._ensure_client()
        assert not client.is_closed
        await provider.aclose()
        assert client.is_closed and provider._client is None
        await provider.aclose()

    asyncio.run(scenario())
