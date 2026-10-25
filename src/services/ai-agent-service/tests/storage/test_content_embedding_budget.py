"""Real PostgreSQL admission for source-scoped content embedding requests."""

import asyncio
from contextlib import asynccontextmanager
import os
import json
import hashlib
from uuid import uuid4

import asyncpg
import pytest
import httpx

from agent_core.budget.content_embedding import ContentEmbeddingLimits, PostgresContentEmbeddingBudget
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind
from agent_core.adapters import EmbeddingProviderSettings, OpenAiEmbeddingProvider
from agent_core.budget.embedding import embedding_budget_scope
from agent_core.content.postgres import PostgresEmbeddingCache


DB_URL = os.environ.get("AGENT_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="Requires an isolated migrated PostgreSQL test database")


@asynccontextmanager
async def source():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    scope_id = uuid4().hex + uuid4().hex
    try:
        yield pool, scope_id
    finally:
        await pool.execute("DELETE FROM agent.content_embedding_budgets WHERE scope_id=$1", scope_id)
        await pool.close()


def test_source_budget_persists_exact_usage_and_request_count_across_restart():
    async def scenario():
        async with source() as (pool, scope_id):
            limits = ContentEmbeddingLimits(100, 2)
            original = PostgresContentEmbeddingBudget(pool, scope_id, limits)
            reservation = await original.reserve(scope_id, BudgetKind.TOKEN, 40)
            await original.commit_embedding(reservation, 7, "reported")
            await original.commit_embedding(reservation, 7, "reported")
            restarted = PostgresContentEmbeddingBudget(pool, scope_id, limits)
            assert (await restarted.usage(scope_id)).committed[BudgetKind.TOKEN] == 7
            second = await restarted.reserve(scope_id, BudgetKind.TOKEN, 10)
            await restarted.commit_embedding(second, 10, "estimated")
            with pytest.raises(PortError) as caught:
                await restarted.reserve(scope_id, BudgetKind.TOKEN, 1)
            assert caught.value.code is AgentErrorCode.BUDGET_EXHAUSTED
            statuses = await pool.fetch("SELECT status FROM agent.content_embedding_reservations WHERE scope_id=$1", scope_id)
            assert {row["status"] for row in statuses} == {"reported", "estimated"}

    asyncio.run(scenario())


def test_content_crash_reservations_and_uncertain_cost_are_never_restored_as_capacity():
    async def scenario():
        async with source() as (pool, scope_id):
            store = PostgresContentEmbeddingBudget(pool, scope_id, ContentEmbeddingLimits(10, 4))
            pending = await store.reserve(scope_id, BudgetKind.TOKEN, 6)
            restarted = PostgresContentEmbeddingBudget(pool, scope_id, ContentEmbeddingLimits(1000, 1000))
            assert (await restarted.usage(scope_id)).limits[BudgetKind.TOKEN] == 10
            assert (await restarted.usage(scope_id)).reserved[BudgetKind.TOKEN] == 6
            with pytest.raises(PortError):
                await restarted.reserve(scope_id, BudgetKind.TOKEN, 5)
            await store.commit_embedding(pending, 6, "uncertain")
            assert (await restarted.usage(scope_id)).uncertain[BudgetKind.TOKEN] == 6
            with pytest.raises(PortError):
                await restarted.release(pending)
            with pytest.raises(PortError):
                await restarted.commit_embedding(pending, 1, "reported")

    asyncio.run(scenario())


def test_parallel_content_requests_cannot_take_the_same_remaining_capacity():
    async def scenario():
        async with source() as (pool, scope_id):
            stores = [PostgresContentEmbeddingBudget(pool, scope_id, ContentEmbeddingLimits(10, 4)) for _ in range(2)]
            results = await asyncio.gather(*(store.reserve(scope_id, BudgetKind.TOKEN, 6) for store in stores), return_exceptions=True)
            assert sum(not isinstance(result, Exception) for result in results) == 1
            assert sum(isinstance(result, PortError) and result.code is AgentErrorCode.BUDGET_EXHAUSTED for result in results) == 1
            assert (await stores[0].usage(scope_id)).reserved[BudgetKind.TOKEN] == 6

    asyncio.run(scenario())


def test_content_budget_rejects_foreign_source_and_mismatched_reservation():
    async def scenario():
        async with source() as (pool, scope_id):
            store = PostgresContentEmbeddingBudget(pool, scope_id, ContentEmbeddingLimits(10, 4))
            reservation = await store.reserve(scope_id, BudgetKind.TOKEN, 6)
            for operation in (
                lambda: store.reserve("another-source", BudgetKind.TOKEN, 1),
                lambda: store.commit(reservation.model_copy(update={"reserved_amount": 1}), 1),
                lambda: store.commit(reservation.model_copy(update={"reservation_id": str(uuid4())}), 1),
                lambda: store.commit_embedding(reservation, 1, "uncertain"),
                lambda: store.commit_embedding(reservation, 1, "estimated"),
            ):
                with pytest.raises(PortError) as caught:
                    await operation()
                assert caught.value.code is AgentErrorCode.VALIDATION_ERROR
            assert (await store.usage(scope_id)).reserved[BudgetKind.TOKEN] == 6

    asyncio.run(scenario())


def test_real_postgres_cache_hit_does_not_send_or_charge_an_embedding_request():
    async def scenario():
        async with source() as (pool, scope_id):
            settings = EmbeddingProviderSettings(api_key="test-only")
            provider = OpenAiEmbeddingProvider(settings, require_budget_scope=True)
            requests = []
            def handle(request):
                requests.append(json.loads(request.content))
                return httpx.Response(200, json={
                    "model": settings.model, "data": [{"index": 0, "embedding": [1.0] + [0.0] * 1535}],
                    "usage": {"prompt_tokens": 3, "total_tokens": 3},
                })
            provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
            text = "cache-contract-" + uuid4().hex
            key = hashlib.sha256(text.encode()).hexdigest()
            try:
                store = PostgresContentEmbeddingBudget(pool, scope_id, ContentEmbeddingLimits(100, 4))
                cache = PostgresEmbeddingCache(pool, provider, settings.index_config)
                with embedding_budget_scope(scope_id, store) as cold:
                    first = await cache.embed([text])
                # New cache instance exercises the PostgreSQL cache after a
                # process-style restart, not a retained in-memory vector.
                with embedding_budget_scope(scope_id, store) as hit:
                    second = await PostgresEmbeddingCache(pool, provider, settings.index_config).embed([text])
                assert first == second and len(requests) == 1
                assert cold.requests == 1 and cold.reported_tokens == 3
                assert hit.requests == hit.reported_tokens == hit.estimated_tokens == 0
                assert (await store.usage(scope_id)).committed[BudgetKind.TOKEN] == 3
            finally:
                await pool.execute("DELETE FROM agent.embedding_cache WHERE input_hash=$1", key)
                await provider.aclose()

    asyncio.run(scenario())
