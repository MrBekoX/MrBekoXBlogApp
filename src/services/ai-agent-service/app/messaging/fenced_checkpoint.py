"""Authoritative PostgreSQL checkpoints committed with the job fencing check.

File storage is a read-only migration source. Its latest checkpoint may seed an
empty run while the active owner holds the job lock. Once any DB checkpoint
exists, legacy files cannot become authoritative again, even for a missing ID.
Opaque payload validation belongs to the core checkpoint/resume boundary.
"""

from contextlib import asynccontextmanager
from functools import wraps
import re
from uuid import UUID

import asyncpg

from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import CheckpointStore


def _error(code, message, *, retryable=False):
    return PortError(code, message, port="FencedCheckpointStore", retryable=retryable)


def _storage_errors(method):
    @wraps(method)
    async def guarded(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except asyncpg.UndefinedTableError:
            raise _error(AgentErrorCode.CONFIG_ERROR, "The durable checkpoint schema is not migrated.") from None
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, TimeoutError):
            raise _error(AgentErrorCode.PROVIDER_ERROR, "Checkpoint storage is temporarily unavailable.", retryable=True) from None
        except asyncpg.PostgresError:
            raise _error(AgentErrorCode.PROVIDER_ERROR, "Checkpoint storage rejected the operation.") from None
    return guarded


class FencedCheckpointStore:
    def __init__(self, inner: CheckpointStore, pool, run_id: str, fencing_token: int, *, schema: str = "agent"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Invalid checkpoint database schema")
        self.inner, self.pool = inner, pool
        self.run_id, self.fencing_token, self.schema = str(UUID(run_id)), fencing_token, f'"{schema}"'

    def _check_run(self, run_id: str) -> None:
        if run_id != self.run_id:
            raise _error(AgentErrorCode.VALIDATION_ERROR, "Checkpoint belongs to another run.")

    @staticmethod
    def _checkpoint_id(checkpoint_id: str) -> str:
        if not isinstance(checkpoint_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}", checkpoint_id.strip()):
            raise _error(AgentErrorCode.VALIDATION_ERROR, "Invalid checkpoint identifier.")
        return checkpoint_id.strip()

    @staticmethod
    def _payload(payload) -> bytes:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise _error(AgentErrorCode.VALIDATION_ERROR, "Checkpoint payload must contain bytes.")
        return bytes(payload)

    @asynccontextmanager
    async def _locked_job(self):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # The fence check and payload write share one database commit.
                # Losing this session cannot leave a later filesystem write.
                row = await connection.fetchrow(
                    f"SELECT fencing_token,status FROM {self.schema}.jobs WHERE run_id=$1 FOR UPDATE",
                    UUID(self.run_id),
                )
                if row is None or row["fencing_token"] != self.fencing_token or row["status"] != "running":
                    raise _error(AgentErrorCode.CANCELLED, "Checkpoint writer no longer owns the running job.")
                # Evaluate the clock after acquiring the lock: waiting for a
                # previous writer must not preserve an earlier validity result.
                validity = await connection.fetchrow(
                    f"SELECT lease_until>clock_timestamp() AS lease_valid,deadline_at>clock_timestamp() AS deadline_valid "
                    f"FROM {self.schema}.jobs WHERE run_id=$1", UUID(self.run_id),
                )
                if not validity["lease_valid"]:
                    raise _error(AgentErrorCode.CANCELLED, "Checkpoint writer lease expired.")
                if not validity["deadline_valid"]:
                    raise _error(AgentErrorCode.TIMEOUT, "Checkpoint job deadline expired.")
                if await connection.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM {self.schema}.cancel_intents WHERE run_id=$1)", UUID(self.run_id),
                ):
                    raise _error(AgentErrorCode.CANCELLED, "Checkpoint job was cancelled.")
                yield connection

    async def _write(self, connection, checkpoint_id: str, payload: bytes) -> None:
        await connection.execute(
            f"INSERT INTO {self.schema}.job_checkpoints(run_id,checkpoint_id,payload,fencing_token) VALUES($1,$2,$3,$4) "
            "ON CONFLICT(run_id,checkpoint_id) DO UPDATE SET payload=EXCLUDED.payload,fencing_token=EXCLUDED.fencing_token,"
            "version=DEFAULT,updated_at=now()",
            UUID(self.run_id), checkpoint_id, payload, self.fencing_token,
        )

    async def _read(self, connection, checkpoint_id: str | None):
        if checkpoint_id is None:
            row = await connection.fetchrow(
                f"SELECT checkpoint_id,payload FROM {self.schema}.job_checkpoints WHERE run_id=$1 ORDER BY version DESC LIMIT 1",
                UUID(self.run_id),
            )
        else:
            row = await connection.fetchrow(
                f"SELECT checkpoint_id,payload FROM {self.schema}.job_checkpoints WHERE run_id=$1 AND checkpoint_id=$2",
                UUID(self.run_id), checkpoint_id,
            )
        return (row["checkpoint_id"], bytes(row["payload"])) if row is not None else None

    async def _load_or_seed(self, checkpoint_id: str | None):
        async with self.pool.acquire() as connection:
            stored = await self._read(connection, checkpoint_id)
            if stored is not None:
                return stored
            if await self._read(connection, None) is not None:
                return None  # DB authority exists; an absent ID has no file fallback.
        async with self._locked_job() as connection:
            latest = await self._read(connection, None)
            if latest is None:
                try:
                    legacy_id, legacy_payload = await self.inner.load_latest(self.run_id)
                except PortError as error:
                    raise _error(error.code, "Legacy checkpoint could not be loaded.", retryable=error.retryable) from None
                legacy_id = self._checkpoint_id(legacy_id)
                legacy_payload = self._payload(legacy_payload)
                await self._write(connection, legacy_id, legacy_payload)
                latest = legacy_id, legacy_payload
            # Returning None commits any latest-only legacy seed before the
            # public explicit-ID load reports NOT_FOUND outside this transaction.
            return latest if checkpoint_id is None else await self._read(connection, checkpoint_id)

    @_storage_errors
    async def save(self, run_id: str, checkpoint_id: str, payload: bytes) -> None:
        self._check_run(run_id)
        checkpoint_id, payload = self._checkpoint_id(checkpoint_id), self._payload(payload)
        async with self._locked_job() as connection:
            await self._write(connection, checkpoint_id, payload)

    @_storage_errors
    async def load(self, run_id: str, checkpoint_id: str) -> bytes:
        self._check_run(run_id)
        stored = await self._load_or_seed(self._checkpoint_id(checkpoint_id))
        if stored is None:
            raise _error(AgentErrorCode.NOT_FOUND, "Checkpoint was not found.")
        return stored[1]

    @_storage_errors
    async def load_latest(self, run_id: str) -> tuple[str, bytes]:
        self._check_run(run_id)
        stored = await self._load_or_seed(None)
        if stored is None:
            raise _error(AgentErrorCode.NOT_FOUND, "Checkpoint was not found.")
        return stored
