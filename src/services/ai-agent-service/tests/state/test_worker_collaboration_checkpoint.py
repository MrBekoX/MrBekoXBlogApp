"""Exercise the production worker dispatch with real collaboration checkpoints."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_core.checkpoint.resume import load_resume_payload
from agent_core.checkpoint.store import FileCheckpointStore
from agent_core.collab.models import CollabResumeInput, CollabStage
from agent_core.entrypoints import PreparedRun, ResumeRequest, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import RunIntent, RunStatus, compute_content_hash
from conftest import make_context, make_route, make_snapshot, make_validated_result
from messaging.worker import ExecutionDependencies, ExecutionWorker, WorkerSettings, stable_execution_id


class NeverCalledModel:
    async def complete(self, *args, **kwargs):
        raise AssertionError("Collaboration must not call a model")

    async def stream_complete(self, *args, **kwargs):
        raise AssertionError("Collaboration must not call a model")


class RecordingProgress:
    profile_guard = False

    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def make_worker(checkpoint_directory):
    return ExecutionWorker(
        object(), ExecutionDependencies(model=NeverCalledModel()), settings=WorkerSettings(worker_id="test"),
        checkpoint_store=FileCheckpointStore(checkpoint_directory),
    )


async def start_collaboration(checkpoint_directory):
    context = make_context(
        question="I would like to collaborate", language="en", article_snapshot=make_snapshot()
    )
    prepared = PreparedRun(
        context=context,
        route=make_route(intent=RunIntent.COLLABORATION),
        prepared_at=datetime.now(timezone.utc),
        execution_id=stable_execution_id(context.run_id),
    )
    worker = make_worker(checkpoint_directory)
    outcome = await worker._execute_prepared(
        SimpleNamespace(fencing_token=1), prepared=prepared, metered=worker._deps.model,
        sink=RecordingProgress(), cancel=None,
    )
    return prepared, outcome


async def resume_worker(checkpoint_directory, **kwargs):
    # Every continuation builds a fresh worker and store: no in-process state
    # can make a missing checkpoint appear to survive a restart.
    worker = make_worker(checkpoint_directory)
    return await worker._try_resume(
        SimpleNamespace(run_id="run-1", queue_class="fast", fencing_token=2, deadline_at=None),
        metered=worker._deps.model, sink=RecordingProgress(), cancel=None, **kwargs,
    )


async def request_proposal(checkpoint_directory):
    return await resume_worker(checkpoint_directory, collab_input=CollabResumeInput(answers={
        "purpose": "open-source contribution",
        "scope": "Add a documentation example",
        "timeline": "Next month",
        "contact": "Public repository issue",
    }))


def test_fresh_worker_collaboration_persists_needs_input_for_restart(tmp_path):
    async def scenario():
        prepared, outcome = await start_collaboration(tmp_path)
        assert outcome.status is RunStatus.NEEDS_INPUT
        assert outcome.error_code is None
        assert outcome.unresolved_questions
        # A new store instance represents a restarted process, without an
        # in-memory PreparedRun or checkpoint store being carried across it.
        envelope, payload = await load_resume_payload(FileCheckpointStore(tmp_path), prepared.context.run_id)
        restored = PreparedRun.model_validate_json(payload)
        assert envelope.run_id == prepared.context.run_id
        assert restored.execution_id == prepared.execution_id
        assert restored.collab_state.stage is CollabStage.DETAILS_NEEDED
        assert restored.collab_state.questions == outcome.unresolved_questions

    asyncio.run(scenario())


def test_restarted_worker_requires_backend_result_then_rejects_repeated_resume(tmp_path):
    async def scenario():
        await start_collaboration(tmp_path)
        proposal_outcome = await request_proposal(tmp_path)
        assert proposal_outcome.status is RunStatus.NEEDS_INPUT
        proposal = proposal_outcome.action_proposal
        assert proposal is not None
        approval = CollabResumeInput(
            approved_proposal_id=proposal.proposal_id,
            approved_content_hash=compute_content_hash(proposal.summary),
        )
        with pytest.raises(PortError) as no_backend_result:
            await resume_worker(tmp_path, collab_input=approval)
        assert no_backend_result.value.code is AgentErrorCode.VALIDATION_ERROR
        result = make_validated_result(proposal_id=proposal.proposal_id)
        completed = await resume_worker(tmp_path, collab_input=approval, validated_result=result)
        assert completed.status is RunStatus.COMPLETED
        with pytest.raises(PortError) as repeated:
            await resume_worker(tmp_path, validated_result=result)
        assert repeated.value.code is AgentErrorCode.VALIDATION_ERROR

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid_approval", ["wrong_proposal", "old_hash", "wrong_run"])
def test_restarted_worker_rejects_approval_outside_the_saved_proposal(tmp_path, invalid_approval):
    async def scenario():
        await start_collaboration(tmp_path)
        outcome = await request_proposal(tmp_path)
        proposal = outcome.action_proposal
        approval = CollabResumeInput(
            approved_proposal_id="wrong-proposal" if invalid_approval == "wrong_proposal" else proposal.proposal_id,
            approved_content_hash="0" * 64 if invalid_approval == "old_hash" else compute_content_hash(proposal.summary),
        )
        result = make_validated_result(
            proposal_id=proposal.proposal_id, run_id="another-run" if invalid_approval == "wrong_run" else "run-1"
        )
        with pytest.raises(PortError) as raised:
            await resume_worker(tmp_path, collab_input=approval, validated_result=result)
        assert raised.value.code is AgentErrorCode.VALIDATION_ERROR
        _, payload = await load_resume_payload(FileCheckpointStore(tmp_path), "run-1")
        assert PreparedRun.model_validate_json(payload).collab_state.stage is CollabStage.PROPOSAL_REVIEW

    asyncio.run(scenario())


def test_collaboration_checkpoint_rejects_other_execution_and_removed_article(tmp_path):
    async def scenario():
        prepared, _ = await start_collaboration(tmp_path)
        for request, code in (
            (ResumeRequest(run_id="run-1", execution_id="other-execution"), AgentErrorCode.VALIDATION_ERROR),
            (ResumeRequest(run_id="run-1", current_context=make_context()), AgentErrorCode.STALE_SNAPSHOT),
        ):
            with pytest.raises(PortError) as raised:
                await resume(request, checkpoint=FileCheckpointStore(tmp_path), model=NeverCalledModel())
            assert raised.value.code is code
        _, payload = await load_resume_payload(FileCheckpointStore(tmp_path), "run-1")
        assert PreparedRun.model_validate_json(payload).execution_id == prepared.execution_id

    asyncio.run(scenario())


def test_cancelled_collaboration_does_not_advance_its_checkpoint(tmp_path):
    class Cancelled:
        def raise_if_cancelled(self):
            raise PortError(AgentErrorCode.CANCELLED, "Cancelled for test")

    async def scenario():
        await start_collaboration(tmp_path)
        checkpoint = FileCheckpointStore(tmp_path)
        _, before = await load_resume_payload(checkpoint, "run-1")
        with pytest.raises(PortError) as raised:
            await resume(ResumeRequest(run_id="run-1"), checkpoint=checkpoint, model=NeverCalledModel(), cancel=Cancelled())
        assert raised.value.code is AgentErrorCode.CANCELLED
        _, after = await load_resume_payload(checkpoint, "run-1")
        assert after == before

    asyncio.run(scenario())
