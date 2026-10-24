"""Real PostgreSQL run budgets: crash recovery, fencing and parallel admission."""

import asyncio
from contextlib import asynccontextmanager
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.postgres import PostgresBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import BudgetKind, ModelRequest


DB_URL = os.environ.get("AGENT_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="Requires an isolated migrated PostgreSQL test database")


@asynccontextmanager
async def job():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    run_id = str(uuid4())
    await pool.execute("""INSERT INTO agent.jobs
        (job_id,run_id,conversation_id,origin_message_id,payload_hash,payload,envelope,status,
         deadline_at,lease_owner,lease_until,fencing_token,execution_attempt)
        VALUES($1,$2,$3,$4,$5,'{}','{}','running',now()+interval '1 hour',
               'budget-test',now()+interval '1 hour',1,1)""",
        uuid4(),UUID(run_id),uuid4(),uuid4(),"0"*64)
    try:
        yield pool, run_id
    finally:
        await pool.execute("DELETE FROM agent.cancel_intents WHERE run_id=$1", UUID(run_id))
        await pool.execute("DELETE FROM agent.jobs WHERE run_id=$1", UUID(run_id))
        await pool.close()


def test_committed_budget_survives_new_store_and_commit_is_idempotent():
    async def scenario():
        async with job() as (pool, run_id):
            policy = BudgetPolicy(max_total_tokens=150)
            store = PostgresBudgetStore(pool, policy, run_id, 1)
            reservation = await store.reserve(run_id, BudgetKind.TOKEN,100)
            await store.commit(reservation,80)
            await store.commit(reservation,80)
            restarted = PostgresBudgetStore(pool,policy,run_id,1)
            assert (await restarted.usage(run_id)).committed[BudgetKind.TOKEN] == 80
            with pytest.raises(PortError) as error:
                await restarted.reserve(run_id,BudgetKind.TOKEN,71)
            assert error.value.code is AgentErrorCode.BUDGET_EXHAUSTED
            remaining = await restarted.reserve(run_id,BudgetKind.TOKEN,70)
            await restarted.release(remaining)
            await restarted.release(remaining)
            with pytest.raises(PortError):
                await store.commit(reservation,79)
            await pool.execute("UPDATE agent.jobs SET status='completed',lease_until=NULL WHERE run_id=$1",UUID(run_id))
            await restarted.commit(reservation,80)
            assert (await restarted.usage(run_id)).committed[BudgetKind.TOKEN] == 80
    asyncio.run(scenario())


def test_crash_reservations_remain_charged_and_stale_worker_cannot_refund():
    async def scenario():
        async with job() as (pool,run_id):
            policy = BudgetPolicy(max_total_tokens=150)
            stale = PostgresBudgetStore(pool,policy,run_id,1)
            reservation = await stale.reserve(run_id,BudgetKind.TOKEN,100)
            await pool.execute("UPDATE agent.jobs SET fencing_token=2,execution_attempt=2 WHERE run_id=$1",UUID(run_id))
            recovered = PostgresBudgetStore(pool,policy,run_id,2)
            usage = await recovered.usage(run_id)
            assert usage.uncertain[BudgetKind.TOKEN] == 100 and not usage.committed
            with pytest.raises(PortError):
                await recovered.reserve(run_id,BudgetKind.TOKEN,51)
            await recovered.reserve(run_id,BudgetKind.TOKEN,50)
            for operation in (lambda: stale.release(reservation), lambda: stale.commit(reservation,1)):
                with pytest.raises(PortError) as error:
                    await operation()
                assert error.value.code is AgentErrorCode.CANCELLED
            usage = await recovered.usage(run_id)
            assert usage.uncertain[BudgetKind.TOKEN] + usage.reserved[BudgetKind.TOKEN] == 150
    asyncio.run(scenario())


def test_parallel_reservations_cannot_both_take_the_last_capacity():
    async def scenario():
        async with job() as (pool,run_id):
            policy = BudgetPolicy(max_total_tokens=10)
            stores = [PostgresBudgetStore(pool,policy,run_id,1) for _ in range(2)]
            outcomes = await asyncio.gather(*(store.reserve(run_id,BudgetKind.TOKEN,6) for store in stores),
                                            return_exceptions=True)
            assert sum(not isinstance(item,Exception) for item in outcomes) == 1
            assert sum(isinstance(item,PortError) and item.code is AgentErrorCode.BUDGET_EXHAUSTED for item in outcomes) == 1
            assert (await stores[0].usage(run_id)).reserved[BudgetKind.TOKEN] == 6
    asyncio.run(scenario())


def test_recovery_from_a_legacy_attempt_does_not_get_a_new_allowance():
    async def scenario():
        async with job() as (pool,run_id):
            await pool.execute("UPDATE agent.jobs SET execution_attempt=2,fencing_token=2 WHERE run_id=$1",UUID(run_id))
            store=PostgresBudgetStore(pool,BudgetPolicy(max_total_tokens=100),run_id,2)
            usage=await store.usage(run_id)
            assert usage.uncertain[BudgetKind.TOKEN] == 100
            with pytest.raises(PortError) as error:
                await store.reserve(run_id,BudgetKind.TOKEN,1)
            assert error.value.code is AgentErrorCode.BUDGET_EXHAUSTED
            assert await pool.fetchval("SELECT count(*) FROM agent.budget_reservations WHERE run_id=$1 "
                                       "AND uncertainty_reason='legacy_attempt'",UUID(run_id)) > 0
    asyncio.run(scenario())


def test_higher_policy_after_restart_cannot_raise_pinned_limits():
    async def scenario():
        async with job() as (pool,run_id):
            await PostgresBudgetStore(pool,BudgetPolicy(max_total_tokens=100),run_id,1).usage(run_id)
            enlarged = PostgresBudgetStore(pool,BudgetPolicy(max_total_tokens=1000),run_id,1)
            assert (await enlarged.usage(run_id)).limits[BudgetKind.TOKEN] == 100
            with pytest.raises(PortError):
                await enlarged.reserve(run_id,BudgetKind.TOKEN,101)
            guard = BudgetGuard(enlarged,BudgetPolicy(max_total_tokens=1000),run_id)
            request = await guard.prepare_model_request(ModelRequest(prompt="q",system="s"),max_output_tokens=1000)
            assert request.max_output_tokens == 34  # 100 - UTF8 input(2) - framing(64)
    asyncio.run(scenario())


@pytest.mark.parametrize("inactive", ["expired-lease","expired-deadline","cancelled","cancel-intent"])
def test_inactive_execution_cannot_start_more_work(inactive):
    async def scenario():
        async with job() as (pool,run_id):
            store = PostgresBudgetStore(pool,BudgetPolicy(max_total_tokens=100),run_id,1)
            reservation = await store.reserve(run_id,BudgetKind.TOKEN,50)
            if inactive == "cancel-intent":
                await pool.execute("INSERT INTO agent.cancel_intents(run_id,requested_by) VALUES($1,'budget-test')",UUID(run_id))
            elif inactive == "cancelled":
                await pool.execute("UPDATE agent.jobs SET status='cancelled' WHERE run_id=$1",UUID(run_id))
            else:
                column = "lease_until" if inactive == "expired-lease" else "deadline_at"
                await pool.execute(f"UPDATE agent.jobs SET {column}=now()-interval '1 second' WHERE run_id=$1",UUID(run_id))
            with pytest.raises(PortError):
                await store.reserve(run_id,BudgetKind.TOKEN,1)
            if inactive in ("expired-lease","cancelled"):
                with pytest.raises(PortError):
                    await store.release(reservation)
            assert (await store.usage(run_id)).reserved[BudgetKind.TOKEN] == 50
    asyncio.run(scenario())
