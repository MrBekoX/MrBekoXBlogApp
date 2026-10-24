"""Worker budget binding and pending reservations are checked before model calls."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from agent_core.budget.guard import BudgetGuard, CallResult
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.store import PolicyBudgetStore
from agent_core.models import BudgetProfile, ExecutionContext, RouteDecision, AgentMode
from agent_core.entrypoints import PreparedRun
from agent_core.ports import BudgetKind, ModelRequest, ModelUsage
from agent_core.errors import AgentErrorCode, PortError
from agent_core.state.events import usage_record_from_events
import pytest
from messaging.worker import ExecutionWorker, ExecutionDependencies


def test_model_output_accounts_for_already_reserved_capacity():
    async def scenario():
        policy=BudgetPolicy(max_total_tokens=200)
        store=PolicyBudgetStore(policy)
        await store.reserve("run",BudgetKind.TOKEN,100)
        request=await BudgetGuard(store,policy,"run").prepare_model_request(ModelRequest(prompt="q",system="s"))
        assert request.max_output_tokens == 34
    asyncio.run(scenario())


def test_fresh_worker_execution_uses_fenced_run_factory(monkeypatch):
    run_id=str(uuid4())
    context=ExecutionContext(run_id=run_id,conversation_id=str(uuid4()),question="Question",language="en",
        budget_profile=BudgetProfile(name="test",max_total_tokens=8000,max_model_calls=4,max_duration_seconds=30))
    route=RouteDecision(run_id=run_id,selected_mode=AgentMode.FAST,reason="test",requires_web_search=False,
                        decided_at=datetime.now(timezone.utc))
    prepared=PreparedRun(context=context,route=route,prepared_at=datetime.now(timezone.utc))
    sentinel=object()
    observed=[]
    def factory(actual,fence):
        observed.append((actual.run_id,fence))
        return sentinel
    async def execute(actual,**kwargs):
        assert actual is prepared and kwargs["budget"] is sentinel
        return "complete"
    monkeypatch.setattr("messaging.worker.execute_plan",execute)
    worker=ExecutionWorker.__new__(ExecutionWorker)
    worker._deps=ExecutionDependencies(model=None,budget_factory=factory)
    result=asyncio.run(worker._execute_prepared(SimpleNamespace(fencing_token=42), prepared=prepared,
        metered=None,sink=SimpleNamespace(profile_guard=False),cancel=None))
    assert result == "complete" and observed == [(run_id,42)]


def test_checkpoint_resume_rebinds_same_run_to_the_current_fence(monkeypatch):
    run_id=str(uuid4())
    context=ExecutionContext(run_id=run_id,conversation_id=str(uuid4()),question="Question",language="en",
        budget_profile=BudgetProfile(name="test",max_total_tokens=8000,max_model_calls=4,max_duration_seconds=30))
    route=RouteDecision(run_id=run_id,selected_mode=AgentMode.FAST,reason="test",requires_web_search=False,
                        decided_at=datetime.now(timezone.utc))
    prepared=PreparedRun(context=context,route=route,prepared_at=datetime.now(timezone.utc))
    sentinel=object();observed=[]
    def factory(actual,fence):
        observed.append((actual.run_id,fence))
        return sentinel
    async def load(*args,**kwargs):
        return None,prepared.model_dump_json().encode()
    async def resume(request,**kwargs):
        assert request.run_id==run_id and kwargs["budget"] is sentinel
        return "resumed"
    monkeypatch.setattr("messaging.worker.load_resume_payload",load)
    monkeypatch.setattr("messaging.worker.resume",resume)
    worker=ExecutionWorker.__new__(ExecutionWorker)
    worker._deps=ExecutionDependencies(model=None,budget_factory=factory)
    worker._checkpoint=object()
    claimed=SimpleNamespace(run_id=run_id,queue_class="fast",fencing_token=99,
                            deadline_at=datetime.now(timezone.utc)+timedelta(seconds=30))
    result=asyncio.run(worker._try_resume(claimed,metered=None,sink=SimpleNamespace(profile_guard=False),cancel=None))
    assert result=="resumed" and observed==[(run_id,99)]


@pytest.mark.parametrize("fail_kind",[BudgetKind.TOKEN,BudgetKind.MODEL_CALL])
def test_known_provider_usage_survives_failed_budget_commit_without_provider_retry(fail_kind):
    class FailingStore(PolicyBudgetStore):
        async def commit(self,reservation,actual):
            if reservation.kind is fail_kind:
                raise PortError(AgentErrorCode.PROVIDER_ERROR,"Lost database acknowledgement",retryable=True)
            await super().commit(reservation,actual)
    async def scenario():
        policy=BudgetPolicy(max_total_tokens=8000)
        guard=BudgetGuard(FailingStore(policy),policy,"known-usage")
        calls=[]
        async def provider(attempt):
            calls.append(attempt)
            return CallResult(value="answer",usage=ModelUsage(prompt_tokens=1000,completion_tokens=2000))
        with pytest.raises(PortError):
            await guard.guarded(action_id="known-call",kind=BudgetKind.MODEL_CALL,call=provider,token_estimate=4000)
        assert calls==[1]
        usage=usage_record_from_events("known-usage",guard.recorded_events)
        assert usage.total_tokens==3000 and usage.model_calls==1
    asyncio.run(scenario())
