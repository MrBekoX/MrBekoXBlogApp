"""Real PostgreSQL connection-loss fencing and checkpoint persistence checks."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from agent_core.checkpoint.store import FileCheckpointStore
from agent_core.checkpoint.models import CheckpointEnvelope, CheckpointKind
from agent_core.checkpoint.resume import load_resume_payload
from agent_core.entrypoints import ResumeRequest, resume
from agent_core.errors import AgentErrorCode, PortError
from messaging.fenced_checkpoint import FencedCheckpointStore


DB_URL = os.environ.get("AGENT_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="Requires an isolated migrated PostgreSQL test database")


class LegacySource:
    def __init__(self, inner):
        self.inner, self.reads, self.writes = inner, 0, 0

    async def save(self, *args):
        self.writes += 1
        raise AssertionError("Authoritative checkpoint writes must not reach files")

    async def load_latest(self, run_id):
        self.reads += 1
        return await self.inner.load_latest(run_id)


@asynccontextmanager
async def running_job():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    run_id = str(uuid4())
    await pool.execute("""INSERT INTO agent.jobs
        (job_id,run_id,conversation_id,origin_message_id,payload_hash,payload,envelope,status,
         deadline_at,lease_owner,lease_until,fencing_token,execution_attempt)
        VALUES($1,$2,$3,$4,$5,'{}','{}','running',now()+interval '1 hour',
               'checkpoint-disconnect-test',now()+interval '1 hour',1,1)""",
        uuid4(), UUID(run_id), uuid4(), uuid4(), "0" * 64)
    try:
        yield pool, run_id
    finally:
        await pool.execute("DELETE FROM agent.cancel_intents WHERE run_id=$1", UUID(run_id))
        await pool.execute("DELETE FROM agent.jobs WHERE run_id=$1", UUID(run_id))
        await pool.close()


@pytest.mark.parametrize("pause_after_write", [False, True])
def test_disconnected_old_owner_cannot_overwrite_new_owners_checkpoint(tmp_path, pause_after_write):
    async def scenario():
        async with running_job() as (pool, run_id):
            legacy = FileCheckpointStore(tmp_path)
            await legacy.save(run_id, "prepared:run", b"immutable-legacy")
            started, release = asyncio.Event(), asyncio.Event()
            writer_pids = []
            file_writes = []

            class ReadOnlyLegacy:
                async def save(self, *args):
                    file_writes.append(args)
                    raise AssertionError("Authoritative checkpoint writes must not reach files")
                async def load_latest(self, run_id):
                    return await legacy.load_latest(run_id)

            class PausedConnection:
                def __init__(self, connection):
                    self.connection = connection
                def __getattr__(self, name):
                    return getattr(self.connection, name)
                async def fetchval(self, query, *args):
                    result = await self.connection.fetchval(query, *args)
                    if not pause_after_write and "cancel_intents" in query:
                        started.set()
                        await release.wait()
                    return result
                async def execute(self, query, *args):
                    result = await self.connection.execute(query, *args)
                    if pause_after_write and "INSERT INTO" in query and "job_checkpoints" in query:
                        started.set()
                        await release.wait()
                    return result

            class ObservedPool:
                @asynccontextmanager
                async def acquire(self):
                    async with pool.acquire() as connection:
                        writer_pids.append(connection.get_server_pid())
                        yield PausedConnection(connection)

            stale = FencedCheckpointStore(ReadOnlyLegacy(), ObservedPool(), run_id, 1)
            saving = asyncio.create_task(stale.save(run_id, "prepared:run", b"stale-owner"))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                assert await pool.fetchval("SELECT pg_terminate_backend($1)", writer_pids[0])
                await pool.execute("UPDATE agent.jobs SET fencing_token=2,execution_attempt=2 WHERE run_id=$1", UUID(run_id))
                current = FencedCheckpointStore(ReadOnlyLegacy(), pool, run_id, 2)
                await current.save(run_id, "prepared:run", b"new-owner")
                release.set()
                result = await asyncio.wait_for(asyncio.gather(saving, return_exceptions=True), timeout=10)
                assert isinstance(result[0], PortError), "The dead database transaction must report a safe storage error"
                assert result[0].code is AgentErrorCode.PROVIDER_ERROR
                assert await current.load(run_id, "prepared:run") == b"new-owner"
                assert await legacy.load(run_id, "prepared:run") == b"immutable-legacy"
                assert file_writes == []
            finally:
                release.set()
                await asyncio.gather(saving, return_exceptions=True)

    asyncio.run(scenario())


def test_authoritative_overwrite_and_latest_use_committed_versions_after_restart(tmp_path):
    async def scenario():
        async with running_job() as (pool, run_id):
            source = LegacySource(FileCheckpointStore(tmp_path))
            store = FencedCheckpointStore(source, pool, run_id, 1)
            await store.save(run_id, "prepared:first", b"first")
            first_version = await pool.fetchval("SELECT version FROM agent.job_checkpoints WHERE run_id=$1 AND checkpoint_id='prepared:first'", UUID(run_id))
            await store.save(run_id, "prepared:second", b"second")
            second_version = await pool.fetchval("SELECT version FROM agent.job_checkpoints WHERE run_id=$1 AND checkpoint_id='prepared:second'", UUID(run_id))
            await store.save(run_id, "prepared:first", b"overwritten")
            overwritten_version = await pool.fetchval("SELECT version FROM agent.job_checkpoints WHERE run_id=$1 AND checkpoint_id='prepared:first'", UUID(run_id))
            assert first_version < second_version < overwritten_version
            # Wall-clock ties must not change write ordering.
            await pool.execute("UPDATE agent.job_checkpoints SET updated_at='2026-10-25 00:00:00+00' WHERE run_id=$1", UUID(run_id))
            restarted = FencedCheckpointStore(source, pool, run_id, 1)
            assert await restarted.load_latest(run_id) == ("prepared:first", b"overwritten")
            assert await restarted.load(run_id, "prepared:second") == b"second"
            assert await pool.fetchval("SELECT count(*) FROM agent.job_checkpoints WHERE run_id=$1", UUID(run_id)) == 2
            assert source.reads == source.writes == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("first_load", ["latest", "old-id"])
def test_only_the_latest_legacy_state_seeds_an_empty_run_and_files_cannot_override_it(tmp_path, first_load):
    async def scenario():
        async with running_job() as (pool, run_id):
            legacy = FileCheckpointStore(tmp_path)
            await legacy.save(run_id, "prepared:old", b"obsolete")
            await legacy.save(run_id, "prepared:latest", b"legacy-current")
            source = LegacySource(legacy)
            store = FencedCheckpointStore(source, pool, run_id, 1)
            if first_load == "latest":
                assert await store.load_latest(run_id) == ("prepared:latest", b"legacy-current")
            else:
                with pytest.raises(PortError) as missing:
                    await store.load(run_id, "prepared:old")
                assert missing.value.code is AgentErrorCode.NOT_FOUND
            assert await pool.fetchval("SELECT count(*) FROM agent.job_checkpoints WHERE run_id=$1", UUID(run_id)) == 1
            # A retired process changing the legacy files cannot affect DB
            # authority, including an explicit old ID absent from the DB.
            await legacy.save(run_id, "prepared:latest", b"stale-file-change")
            assert await store.load_latest(run_id) == ("prepared:latest", b"legacy-current")
            with pytest.raises(PortError) as missing:
                await store.load(run_id, "prepared:old")
            assert missing.value.code is AgentErrorCode.NOT_FOUND
            assert source.reads == 1 and source.writes == 0

    asyncio.run(scenario())


def test_parallel_legacy_importers_recheck_database_authority_under_the_job_lock(tmp_path):
    async def scenario():
        async with running_job() as (pool, run_id):
            legacy = FileCheckpointStore(tmp_path)
            await legacy.save(run_id, "prepared:run", b"legacy-current")
            class SlowLegacy(LegacySource):
                async def load_latest(self, run_id):
                    self.reads += 1
                    await asyncio.sleep(.05)
                    return await self.inner.load_latest(run_id)
            source = SlowLegacy(legacy)
            stores = [FencedCheckpointStore(source, pool, run_id, 1) for _ in range(2)]
            results = await asyncio.gather(*(store.load_latest(run_id) for store in stores))
            assert results == [("prepared:run", b"legacy-current")] * 2
            assert source.reads == 1 and source.writes == 0
            assert await pool.fetchval("SELECT count(*) FROM agent.job_checkpoints WHERE run_id=$1", UUID(run_id)) == 1

    asyncio.run(scenario())


def test_stale_owner_cannot_seed_legacy_state_into_an_empty_database(tmp_path):
    async def scenario():
        async with running_job() as (pool, run_id):
            legacy = FileCheckpointStore(tmp_path)
            await legacy.save(run_id, "prepared:run", b"legacy-current")
            source = LegacySource(legacy)
            await pool.execute("UPDATE agent.jobs SET fencing_token=2 WHERE run_id=$1", UUID(run_id))
            with pytest.raises(PortError) as stale:
                await FencedCheckpointStore(source, pool, run_id, 1).load_latest(run_id)
            assert stale.value.code is AgentErrorCode.CANCELLED
            assert source.reads == 0
            assert await pool.fetchval("SELECT count(*) FROM agent.job_checkpoints WHERE run_id=$1", UUID(run_id)) == 0

    asyncio.run(scenario())


def test_unknown_commit_acknowledgement_does_not_create_a_later_external_write(tmp_path):
    async def scenario():
        async with running_job() as (pool, run_id):
            source = LegacySource(FileCheckpointStore(tmp_path))
            class LostAcknowledgementConnection:
                def __init__(self, connection):
                    self.connection = connection
                def __getattr__(self, name):
                    return getattr(self.connection, name)
                @asynccontextmanager
                async def transaction(self):
                    async with self.connection.transaction():
                        yield
                    raise asyncpg.ConnectionDoesNotExistError("PRIVATE_ACK_DETAILS")
            class LostAcknowledgementPool:
                @asynccontextmanager
                async def acquire(self):
                    async with pool.acquire() as connection:
                        yield LostAcknowledgementConnection(connection)
            uncertain = FencedCheckpointStore(source, LostAcknowledgementPool(), run_id, 1)
            with pytest.raises(PortError) as lost:
                await uncertain.save(run_id, "prepared:run", b"committed-before-lost-ack")
            assert lost.value.code is AgentErrorCode.PROVIDER_ERROR and lost.value.retryable
            assert "PRIVATE_ACK_DETAILS" not in str(lost.value)
            assert await FencedCheckpointStore(source, pool, run_id, 1).load_latest(run_id) == (
                "prepared:run", b"committed-before-lost-ack"
            )
            await pool.execute("UPDATE agent.jobs SET fencing_token=2 WHERE run_id=$1", UUID(run_id))
            current = FencedCheckpointStore(source, pool, run_id, 2)
            await current.save(run_id, "prepared:run", b"new-owner")
            with pytest.raises(PortError) as stale:
                await uncertain.save(run_id, "prepared:run", b"stale-retry")
            assert stale.value.code is AgentErrorCode.CANCELLED
            assert await current.load_latest(run_id) == ("prepared:run", b"new-owner")
            assert source.writes == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("explicit_id", [False, True])
def test_database_read_failure_never_becomes_a_legacy_file_fallback(tmp_path, explicit_id):
    async def scenario():
        async with running_job() as (pool, run_id):
            legacy = FileCheckpointStore(tmp_path)
            await legacy.save(run_id, "prepared:run", b"must-not-fallback")
            source = LegacySource(legacy)
            class FailedReadConnection:
                def __init__(self, connection):
                    self.connection = connection
                def __getattr__(self, name):
                    return getattr(self.connection, name)
                async def fetchrow(self, *args):
                    raise asyncpg.ConnectionDoesNotExistError("PRIVATE_QUERY_AND_PAYLOAD")
            class FailedReadPool:
                @asynccontextmanager
                async def acquire(self):
                    async with pool.acquire() as connection:
                        yield FailedReadConnection(connection)
            store = FencedCheckpointStore(source, FailedReadPool(), run_id, 1)
            with pytest.raises(PortError) as failed:
                if explicit_id:
                    await store.load(run_id, "prepared:run")
                else:
                    await store.load_latest(run_id)
            assert failed.value.code is AgentErrorCode.PROVIDER_ERROR
            assert "PRIVATE_QUERY_AND_PAYLOAD" not in str(failed.value)
            assert source.reads == source.writes == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("expired_column,expected", [("lease_until", AgentErrorCode.CANCELLED), ("deadline_at", AgentErrorCode.TIMEOUT)])
def test_checkpoint_validity_is_checked_after_waiting_for_the_job_lock(tmp_path, expired_column, expected):
    async def scenario():
        async with running_job() as (pool, run_id):
            store = FencedCheckpointStore(LegacySource(FileCheckpointStore(tmp_path)), pool, run_id, 1)
            async with pool.acquire() as blocker:
                async with blocker.transaction():
                    await blocker.execute(f"UPDATE agent.jobs SET {expired_column}=clock_timestamp()+interval '.05 seconds' WHERE run_id=$1", UUID(run_id))
                    saving = asyncio.create_task(store.save(run_id, "prepared:run", b"expired-while-waiting"))
                    await asyncio.sleep(.15)
                    assert not saving.done()
            with pytest.raises(PortError) as expired:
                await asyncio.wait_for(saving, timeout=10)
            assert expired.value.code is expected
            assert await pool.fetchval("SELECT count(*) FROM agent.job_checkpoints WHERE run_id=$1", UUID(run_id)) == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["foreign-run", "future-schema", "corrupt-payload"])
def test_imported_opaque_payload_still_requires_core_resume_validation(tmp_path, invalid):
    async def scenario():
        async with running_job() as (pool, run_id):
            legacy = FileCheckpointStore(tmp_path)
            if invalid == "corrupt-payload":
                payload = b"not-a-checkpoint"
            else:
                envelope = CheckpointEnvelope.wrap(
                    checkpoint_id="prepared:run", run_id=str(uuid4()) if invalid == "foreign-run" else run_id,
                    execution_id="checkpoint-test", kind=CheckpointKind.PREPARED,
                    payload=b"{}", saved_at=datetime.now(timezone.utc),
                )
                if invalid == "future-schema":
                    envelope = envelope.model_copy(update={"schema_version": 999})
                payload = envelope.model_dump_json().encode()
            await legacy.save(run_id, "prepared:run", payload)
            store = FencedCheckpointStore(LegacySource(legacy), pool, run_id, 1)
            with pytest.raises(PortError) as invalid_resume:
                if invalid == "corrupt-payload":
                    await resume(ResumeRequest(run_id=run_id), checkpoint=store, model=None)
                else:
                    await load_resume_payload(store, run_id)
            assert invalid_resume.value.code is AgentErrorCode.VALIDATION_ERROR
            assert await store.load(run_id, "prepared:run") == payload  # Storage stays opaque.

    asyncio.run(scenario())


def test_deleting_a_job_cascades_its_authoritative_checkpoint_rows(tmp_path):
    async def scenario():
        async with running_job() as (pool, run_id):
            store = FencedCheckpointStore(LegacySource(FileCheckpointStore(tmp_path)), pool, run_id, 1)
            await store.save(run_id, "prepared:run", b"owned-by-job")
            await pool.execute("DELETE FROM agent.jobs WHERE run_id=$1", UUID(run_id))
            assert await pool.fetchval("SELECT count(*) FROM agent.job_checkpoints WHERE run_id=$1", UUID(run_id)) == 0

    asyncio.run(scenario())
