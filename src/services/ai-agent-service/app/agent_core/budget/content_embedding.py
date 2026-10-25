"""Persistent per-source embedding admission, independent of user job leases.

The owner is the hash of an immutable article revision and embedding index
configuration. Pending requests remain charged after a crash. Nothing can
release them, and later redelivery does not obtain a fresh allowance. This is
cost admission, not an exactly-once claim for an external provider request.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
import hashlib
import re
from typing import Any, Mapping
from uuid import UUID, uuid4

import asyncpg

from env_file import env_int

from ..errors import AgentErrorCode, PortError
from ..ports import BudgetKind, BudgetReservation, BudgetUsage


@dataclass(frozen=True)
class ContentEmbeddingLimits:
    max_tokens: int
    max_requests: int

    def __post_init__(self):
        if any(type(value) is not int or not 1 <= value <= 2**63 - 1 for value in (self.max_tokens, self.max_requests)):
            raise PortError(AgentErrorCode.CONFIG_ERROR, "Content embedding limits must be positive integers.",
                            port="ContentEmbeddingLimits")

    @classmethod
    def from_env(cls, env: Mapping[str, str]):
        from ..adapters.openai_embedding import MAX_INPUT_BYTES, MAX_INPUT_COUNT, MAX_TOTAL_INPUT_BYTES
        # Preserve the existing byte/input ceilings as the default allowance
        # per immutable source version, including UTF-8 split segments. These
        # are token/request bounds, not inferred monetary or business targets.
        max_requests = MAX_INPUT_COUNT + (MAX_TOTAL_INPUT_BYTES + MAX_INPUT_BYTES - 1) // MAX_INPUT_BYTES
        return cls(
            max_tokens=env_int("AGENT_CONTENT_SYNC_MAX_EMBEDDING_TOKENS", MAX_TOTAL_INPUT_BYTES, env),
            max_requests=env_int("AGENT_CONTENT_SYNC_MAX_EMBEDDING_REQUESTS", max_requests, env),
        )


def content_embedding_scope(snapshot, model) -> str:
    identity = f"{snapshot.article_id}\n{snapshot.article_revision}\n{snapshot.content_hash}\n{model.model_id}\n{model.dimensions}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _storage_errors(method):
    @wraps(method)
    async def guarded(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except (asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError,
                asyncpg.SerializationError, asyncpg.DeadlockDetectedError, OSError, TimeoutError):
            raise PortError(AgentErrorCode.PROVIDER_ERROR, "Content embedding budget storage is unavailable.",
                            port="ContentEmbeddingBudget", retryable=False) from None
    return guarded


class PostgresContentEmbeddingBudget:
    """BudgetStore token operations backed by an immutable-source cost owner."""

    def __init__(self, pool: Any, scope_id: str, limits: ContentEmbeddingLimits, *, schema: str = "agent"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema) or not re.fullmatch(r"[0-9a-f]{64}", scope_id):
            raise ValueError("Invalid content embedding budget scope or schema")
        self.pool, self.scope_id, self.limits = pool, scope_id, limits
        self.schema = f'"{schema}"'

    def _check_scope(self, run_id: str):
        if run_id != self.scope_id:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Embedding reservation belongs to another source.",
                            port="ContentEmbeddingBudget")

    @asynccontextmanager
    async def _locked(self):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"INSERT INTO {self.schema}.content_embedding_budgets(scope_id,token_limit,request_limit) "
                    "VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                    self.scope_id, self.limits.max_tokens, self.limits.max_requests,
                )
                pinned = await conn.fetchrow(
                    f"SELECT token_limit,request_limit FROM {self.schema}.content_embedding_budgets "
                    "WHERE scope_id=$1 FOR UPDATE", self.scope_id,
                )
                yield conn, min(pinned["token_limit"], self.limits.max_tokens), min(pinned["request_limit"], self.limits.max_requests)

    async def _totals(self, conn):
        return await conn.fetchrow(
            f"SELECT count(*) AS requests, COALESCE(sum(COALESCE(actual_amount,reserved_amount)),0) AS tokens "
            f"FROM {self.schema}.content_embedding_reservations WHERE scope_id=$1", self.scope_id,
        )

    @_storage_errors
    async def reserve(self, run_id: str, kind: BudgetKind, amount: int) -> BudgetReservation:
        self._check_scope(run_id)
        if kind is not BudgetKind.TOKEN or type(amount) is not int or amount < 1:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Invalid content embedding reservation.", port="ContentEmbeddingBudget")
        async with self._locked() as (conn, token_limit, request_limit):
            totals = await self._totals(conn)
            if totals["tokens"] + amount > token_limit or totals["requests"] >= request_limit:
                raise PortError(AgentErrorCode.BUDGET_EXHAUSTED, "Content embedding budget exhausted.", port="ContentEmbeddingBudget")
            reservation_id = uuid4()
            created = await conn.fetchval(
                f"INSERT INTO {self.schema}.content_embedding_reservations(reservation_id,scope_id,reserved_amount,status) "
                "VALUES($1,$2,$3,'reserved') RETURNING created_at", reservation_id, self.scope_id, amount,
            )
            return BudgetReservation(reservation_id=str(reservation_id), run_id=self.scope_id, kind=BudgetKind.TOKEN,
                                     reserved_amount=amount, created_at=created)

    @_storage_errors
    async def commit_embedding(self, reservation: BudgetReservation, actual_amount: int, classification: str) -> None:
        self._check_scope(reservation.run_id)
        if (type(actual_amount) is not int or actual_amount < 1 or reservation.kind is not BudgetKind.TOKEN
                or classification not in {"reported", "estimated", "uncertain"}
                or (classification in {"estimated", "uncertain"} and actual_amount != reservation.reserved_amount)):
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Invalid content embedding usage.", port="ContentEmbeddingBudget")
        async with self._locked() as (conn, _, _):
            row = await conn.fetchrow(
                f"SELECT reserved_amount,actual_amount,status FROM {self.schema}.content_embedding_reservations "
                "WHERE reservation_id=$1 AND scope_id=$2 FOR UPDATE", UUID(reservation.reservation_id), self.scope_id,
            )
            if row is None or row["reserved_amount"] != reservation.reserved_amount:
                raise PortError(AgentErrorCode.VALIDATION_ERROR, "Unknown content embedding reservation.", port="ContentEmbeddingBudget")
            if row["status"] == classification and row["actual_amount"] == actual_amount:
                return
            if row["status"] != "reserved":
                raise PortError(AgentErrorCode.VALIDATION_ERROR, "Content embedding reservation was already resolved.", port="ContentEmbeddingBudget")
            await conn.execute(
                f"UPDATE {self.schema}.content_embedding_reservations SET actual_amount=$2,status=$3,resolved_at=now() "
                "WHERE reservation_id=$1", UUID(reservation.reservation_id), actual_amount, classification,
            )

    async def commit(self, reservation: BudgetReservation, actual_amount: int) -> None:
        await self.commit_embedding(reservation, actual_amount, "reported")

    async def release(self, reservation: BudgetReservation) -> None:
        raise PortError(AgentErrorCode.VALIDATION_ERROR, "Content embedding charges cannot be refunded.", port="ContentEmbeddingBudget")

    @_storage_errors
    async def usage(self, run_id: str) -> BudgetUsage:
        self._check_scope(run_id)
        async with self._locked() as (conn, token_limit, _):
            rows = await conn.fetch(
                f"SELECT status,sum(COALESCE(actual_amount,reserved_amount)) AS amount "
                f"FROM {self.schema}.content_embedding_reservations WHERE scope_id=$1 GROUP BY status", self.scope_id,
            )
            amounts = {row["status"]: int(row["amount"]) for row in rows}
            return BudgetUsage(
                run_id=self.scope_id,
                committed={BudgetKind.TOKEN: amounts.get("reported", 0) + amounts.get("estimated", 0)},
                reserved={BudgetKind.TOKEN: amounts.get("reserved", 0)},
                uncertain={BudgetKind.TOKEN: amounts.get("uncertain", 0)}, limits={BudgetKind.TOKEN: token_limit},
            )
