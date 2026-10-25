"""Real worker/PostgreSQL recovery after a fault before terminal persistence.

The validated backend result is a protocol fixture. No model, broker, backend
action provider, operating-system process crash or semantic acceptance is run.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from agent_core.checkpoint.models import CheckpointKind
from agent_core.checkpoint.resume import load_resume_payload, save_checkpoint
from agent_core.collab.models import CollabResumeInput, CollabStage
from agent_core.entrypoints import PreparedRun, ResumeRequest, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import ValidatedActionResult, compute_content_hash
from messaging.contracts import AgentEnvelope, Producer
from messaging.events import AgentEventPublisher
from messaging.content import ContentSyncState
from messaging.fenced_checkpoint import FencedCheckpointStore
from messaging.job_store import JobStore
from messaging.worker import ExecutionDependencies, ExecutionWorker, WorkerSettings


DB_URL = os.environ.get("AGENT_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="Requires an isolated migrated PostgreSQL test database")


class BeforeTerminalCommit(RuntimeError):
    pass


class NoModelCalls:
    async def complete(self, *args, **kwargs):
        raise AssertionError("Collaboration recovery must not call a model")

    async def stream_complete(self, *args, **kwargs):
        raise AssertionError("Collaboration recovery must not call a model")


@asynccontextmanager
async def collaboration_job():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    run_id, conversation_id, correlation_id, article_id = (str(uuid4()) for _ in range(4))
    deadline = datetime.now(timezone.utc) + timedelta(minutes=10)
    payload = {
        "user_ref": "recovery-test-owner", "question": "Sitenizle iş birliği yapmak istiyorum",
        "language": "en", "mode_preference": "fast", "budget_profile": "default",
        "article_id": article_id, "article_revision": 1,
        "article_content_hash": compute_content_hash("Public collaboration test article"),
    }
    envelope = AgentEnvelope(
        message_id=str(uuid4()), message_type="agent.execute.requested", schema_version=1,
        run_id=run_id, conversation_id=conversation_id, correlation_id=correlation_id,
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        deadline_at=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        producer=Producer.BACKEND_NET, payload=payload,
    )
    await pool.execute("""INSERT INTO agent.jobs
        (job_id,run_id,conversation_id,origin_message_id,payload_hash,payload,envelope,status,
         queue_class,deadline_at,accepted_at,wire_version)
        VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,'accepted','fast',$8,now(),1)""",
        uuid4(), UUID(run_id), UUID(conversation_id), UUID(envelope.message_id), "0" * 64,
        json.dumps(payload), envelope.model_dump_json(exclude_none=True), deadline,
    )
    try:
        yield pool, run_id
    finally:
        await pool.execute("DELETE FROM agent.outbox_events WHERE envelope->>'run_id'=$1", run_id)
        await pool.execute("DELETE FROM agent.cancel_intents WHERE run_id=$1", UUID(run_id))
        await pool.execute("DELETE FROM agent.run_event_sequences WHERE run_id=$1", UUID(run_id))
        await pool.execute("DELETE FROM agent.jobs WHERE run_id=$1", UUID(run_id))
        await pool.close()


def make_worker(pool, store, directory, *, content_state=None):
    return ExecutionWorker(
        store,
        ExecutionDependencies(
            model=NoModelCalls(),
            content_state=content_state,
            checkpoint_factory=lambda inner, run_id, fence: FencedCheckpointStore(inner, pool, run_id, fence),
        ),
        settings=WorkerSettings(worker_id="collaboration-recovery", checkpoint_base_dir=str(directory)),
        publisher=AgentEventPublisher(pool),
    )


async def interrupt_after_resolution(pool, run_id, directory, monkeypatch, *, outcome="accepted"):
    store = JobStore(pool)
    worker = make_worker(pool, store, directory)
    first = await store.claim_next_job("initial", lease_seconds=60)
    assert first.run_id == run_id
    initial = await worker.execute_claimed(first, collab_input=CollabResumeInput(answers={
        "purpose": "open-source contribution", "scope": "Add a public documentation example",
        "timeline": "Next month", "contact": "Public repository issue",
    }))
    assert initial.action == "needs_input"
    _, payload = await load_resume_payload(worker._checkpoint_for(first), run_id)
    prepared = PreparedRun.model_validate_json(payload)
    assert prepared.collab_state.stage is CollabStage.PROPOSAL_REVIEW
    receipt = ValidatedActionResult(
        proposal_id=prepared.collab_state.proposal.proposal_id, run_id=run_id,
        outcome=outcome, applied_article_revision=2 if outcome == "accepted" else None,
        reason="Backend rejected the request" if outcome == "rejected" else None,
        validated_at=datetime.now(timezone.utc),
    )
    continuing = await store.claim_job_for_continuation(run_id, "approval", lease_seconds=60)
    original_complete = store.complete_job

    async def fail_before_terminal(*args, **kwargs):
        raise BeforeTerminalCommit("Injected fault before terminal persistence")

    monkeypatch.setattr(store, "complete_job", fail_before_terminal)
    try:
        with pytest.raises(BeforeTerminalCommit):
            await worker.execute_claimed(continuing, validated_result=receipt)
    finally:
        monkeypatch.setattr(store, "complete_job", original_complete)
    _, payload = await load_resume_payload(worker._checkpoint_for(continuing), run_id)
    prepared = PreparedRun.model_validate_json(payload)
    assert prepared.collab_state.stage is CollabStage.RESOLVED
    assert await pool.fetchval("SELECT status FROM agent.jobs WHERE run_id=$1", UUID(run_id)) == "running"
    assert (await event_counts(pool, run_id)).get("agent.run.completed", 0) == 0
    assert (await event_counts(pool, run_id)).get("agent.run.failed", 0) == 0
    return store, worker, continuing, prepared, receipt


async def reclaim(pool, store, run_id):
    await pool.execute("UPDATE agent.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE run_id=$1", UUID(run_id))
    claimed = await store.claim_next_job("recovery", lease_seconds=60)
    assert claimed.run_id == run_id and claimed.recovered
    return claimed


async def event_counts(pool, run_id):
    rows = await pool.fetch("SELECT envelope->>'message_type' AS kind,count(*) AS amount FROM agent.outbox_events "
                            "WHERE envelope->>'run_id'=$1 GROUP BY envelope->>'message_type'", run_id)
    return {row["kind"]: row["amount"] for row in rows}


@pytest.mark.parametrize("outcome", ["accepted", "rejected"])
def test_recovered_worker_reconciles_a_validated_resolved_checkpoint_without_reexecuting_the_action(tmp_path, monkeypatch, outcome):
    async def scenario():
        async with collaboration_job() as (pool, run_id):
            store, _, continuing, _, _ = await interrupt_after_resolution(pool, run_id, tmp_path, monkeypatch, outcome=outcome)
            reclaimed = await reclaim(pool, store, run_id)
            assert reclaimed.fencing_token > continuing.fencing_token
            restarted = make_worker(pool, store, tmp_path)
            recovered = await restarted.execute_claimed(reclaimed)
            assert recovered.action == "completed"
            row = await pool.fetchrow("SELECT status,result_json FROM agent.jobs WHERE run_id=$1", UUID(run_id))
            assert row["status"] == "completed"
            result = json.loads(row["result_json"]) if isinstance(row["result_json"], str) else row["result_json"]
            assert ("verified and registered" if outcome == "accepted" else "NOT registered") in result["answer"]
            counts = await event_counts(pool, run_id)
            assert counts.get("agent.run.completed") == 1 and counts.get("agent.run.failed", 0) == 0
            assert counts.get("agent.action.proposed") == 1
            assert await store.claim_job_for_continuation(run_id, "duplicate", lease_seconds=60) is None
            # A normal public resume remains a duplicate intervention. Only
            # the worker's internal lease-recovery path may reconcile receipt.
            with pytest.raises(PortError) as duplicate:
                await resume(ResumeRequest(run_id=run_id), checkpoint=restarted._checkpoint_for(reclaimed), model=NoModelCalls())
            assert duplicate.value.code is AgentErrorCode.VALIDATION_ERROR

    asyncio.run(scenario())


@pytest.mark.parametrize("path,replacement", [
    (("collab_state", "resolution"), None),
    (("collab_state", "resolution", "result", "run_id"), "11111111-1111-4111-8111-111111111111"),
    (("collab_state", "resolution", "result", "proposal_id"), "11111111-1111-4111-8111-111111111111"),
    (("collab_state", "resolution", "proposal_content_hash"), "0" * 64),
    (("collab_state", "proposal_content_hash"), None),
    (("collab_state", "proposal", "summary"), "Different proposal summary"),
    (("collab_state", "proposal", "article_id"), "11111111-1111-4111-8111-111111111111"),
    (("collab_state", "proposal", "article_revision"), 99),
    (("collab_state", "proposal", "base_content_hash"), "0" * 64),
    (("context", "run_id"), "11111111-1111-4111-8111-111111111111"),
    (("route", "run_id"), "11111111-1111-4111-8111-111111111111"),
    (("execution_id",), "another-execution"),
], ids=["legacy-no-receipt", "foreign-result-run", "foreign-result-proposal", "wrong-receipt-hash",
        "missing-approved-hash", "changed-summary", "foreign-article", "wrong-article-revision",
        "wrong-article-hash", "foreign-payload-run", "foreign-route-run", "foreign-payload-execution"])
def test_recovery_never_completes_an_unbound_or_missing_resolution(tmp_path, monkeypatch, path, replacement):
    async def scenario():
        async with collaboration_job() as (pool, run_id):
            store, worker, continuing, prepared, _ = await interrupt_after_resolution(pool, run_id, tmp_path, monkeypatch)
            document = json.loads(prepared.model_dump_json())
            target = document
            for part in path[:-1]:
                target = target[part]
            if path == ("collab_state", "resolution"):
                target.pop(path[-1])  # Exact pre-receipt legacy payload shape.
            else:
                target[path[-1]] = replacement
            await save_checkpoint(
                worker._checkpoint_for(continuing), run_id=run_id, execution_id=prepared.execution_id,
                kind=CheckpointKind.PREPARED, checkpoint_id="prepared:run", payload=json.dumps(document).encode(),
            )
            claimed = await reclaim(pool, store, run_id)
            result = await make_worker(pool, store, tmp_path).execute_claimed(claimed)
            assert result.action == "failed"
            counts = await event_counts(pool, run_id)
            assert counts.get("agent.run.completed", 0) == 0 and counts.get("agent.run.failed") == 1
            assert counts.get("agent.action.proposed") == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("intervention", ["not-recovered", "new-input", "new-result", "cancelled", "expired-deadline", "stale-owner", "unpublished"])
def test_resolution_receipt_does_not_bypass_resume_or_job_guards(tmp_path, monkeypatch, intervention):
    async def scenario():
        async with collaboration_job() as (pool, run_id):
            store, _, _, prepared, receipt = await interrupt_after_resolution(pool, run_id, tmp_path, monkeypatch)
            claimed = await reclaim(pool, store, run_id)
            kwargs = {}
            content_state = None
            if intervention == "not-recovered":
                claimed = replace(claimed, recovered=False)
            elif intervention == "new-input":
                kwargs["collab_input"] = CollabResumeInput(answers={"scope": "A new request"})
            elif intervention == "new-result":
                kwargs["validated_result"] = receipt
            elif intervention == "cancelled":
                await pool.execute("INSERT INTO agent.cancel_intents(run_id,requested_by) VALUES($1,'recovery-test-owner')", UUID(run_id))
            elif intervention == "expired-deadline":
                deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
                await pool.execute("UPDATE agent.jobs SET deadline_at=$2 WHERE run_id=$1", UUID(run_id), deadline)
                claimed = replace(claimed, deadline_at=deadline)
            elif intervention == "stale-owner":
                await pool.execute("UPDATE agent.jobs SET fencing_token=nextval('agent.job_fencing_seq'),lease_owner='newer-owner' WHERE run_id=$1", UUID(run_id))
            elif intervention == "unpublished":
                content_state = ContentSyncState()
                content_state.restore_articles([{
                    "article_id": prepared.context.article_id, "revision": 2, "content_hash": None, "deleted": True,
                }])
            result = await make_worker(pool, store, tmp_path, content_state=content_state).execute_claimed(claimed, **kwargs)
            expected = "aborted_cancel" if intervention == "cancelled" else "aborted_lease_lost" if intervention == "stale-owner" else "failed"
            assert result.action == expected
            counts = await event_counts(pool, run_id)
            assert counts.get("agent.run.completed", 0) == 0 and counts.get("agent.action.proposed") == 1

    asyncio.run(scenario())
