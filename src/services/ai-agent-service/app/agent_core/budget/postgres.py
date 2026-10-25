"""Fenced, run-wide budget ledger; an external call is reserved before it starts.

Limits are pinned on first use. Outstanding reservations from an older execution
become uncertain charges, not free capacity. A stale worker cannot refund them.
No model input, output or credentials are stored in this ledger.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import wraps
import json
import re
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from ..errors import AgentErrorCode, PortError
from ..ports import BudgetKind, BudgetReservation, BudgetUsage
from .policy import BudgetPolicy


def _storage_errors(method):
    @wraps(method)
    async def guarded(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except (asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError,
                asyncpg.SerializationError, asyncpg.DeadlockDetectedError, OSError, TimeoutError):
            raise PortError(AgentErrorCode.PROVIDER_ERROR, "Run budget storage is temporarily unavailable",
                            port="BudgetStore", retryable=True) from None
    return guarded


class PostgresBudgetStore:
    def __init__(self, pool: Any, policy: BudgetPolicy, run_id: str, fencing_token: int, *, schema: str = "agent"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Invalid budget schema")
        self.pool, self.run_id, self.fencing_token = pool, str(UUID(run_id)), fencing_token
        self.schema = f'"{schema}"'
        self.caps = {
            BudgetKind.MODEL_CALL: policy.max_model_calls, BudgetKind.TOKEN: policy.max_total_tokens,
            BudgetKind.TOOL_CALL: policy.max_tool_attempts, BudgetKind.WEB_SEARCH_CALL: policy.max_search_calls,
            BudgetKind.SOURCE_PAGE_READ: policy.max_source_pages, BudgetKind.RESEARCH_ROUND: policy.max_research_rounds,
        }

    def _check_run(self, run_id: str) -> None:
        if run_id != self.run_id:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Reservation belongs to another run", port="BudgetStore")

    @asynccontextmanager
    async def _locked(self, *, require_active: bool):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                job = await conn.fetchrow(
                    f"SELECT status,fencing_token,lease_until,deadline_at,execution_attempt FROM {self.schema}.jobs "
                    "WHERE run_id=$1 FOR UPDATE", UUID(self.run_id))
                if job is None or job["fencing_token"] != self.fencing_token:
                    raise PortError(AgentErrorCode.CANCELLED, "Budget execution no longer owns the job", port="BudgetStore")
                if require_active:
                    now = await conn.fetchval("SELECT clock_timestamp()")
                    cancelled = await conn.fetchval(
                        f"SELECT EXISTS(SELECT 1 FROM {self.schema}.cancel_intents WHERE run_id=$1)", UUID(self.run_id))
                    if job["deadline_at"] <= now:
                        raise PortError(AgentErrorCode.TIMEOUT, "The run deadline has expired", port="BudgetStore")
                    if (job["status"] != "running" or job["lease_until"] is None
                            or job["lease_until"] <= now or cancelled):
                        raise PortError(AgentErrorCode.CANCELLED, "Budget execution is no longer active", port="BudgetStore")
                created = await conn.fetchval(
                    f"INSERT INTO {self.schema}.run_budgets(run_id,limits) VALUES($1,$2::jsonb) "
                    "ON CONFLICT DO NOTHING RETURNING run_id",
                    UUID(self.run_id), json.dumps({k.value: v for k, v in self.caps.items()}))
                if created is not None and job["execution_attempt"] > 1:
                    # A job started before the durable ledger existed may already
                    # have billed work. Unknown history is not a fresh allowance.
                    await conn.executemany(
                        f"INSERT INTO {self.schema}.budget_reservations "
                        "(reservation_id,run_id,fencing_token,kind,reserved_amount,status,resolved_at,uncertainty_reason) "
                        "VALUES($1,$2,0,$3,$4,'uncertain',now(),'legacy_attempt')",
                        [(uuid4(),UUID(self.run_id),kind.value,cap) for kind,cap in self.caps.items() if cap>0])
                await conn.execute(
                    f"UPDATE {self.schema}.budget_reservations SET status='uncertain',resolved_at=now(),"
                    "uncertainty_reason='lease_recovered' "
                    "WHERE run_id=$1 AND fencing_token<>$2 AND status='reserved'",
                    UUID(self.run_id), self.fencing_token)
                yield conn

    async def _usage(self, conn: Any) -> BudgetUsage:
        raw = await conn.fetchval(f"SELECT limits FROM {self.schema}.run_budgets WHERE run_id=$1", UUID(self.run_id))
        pinned = json.loads(raw) if isinstance(raw, str) else raw
        rows = await conn.fetch(
            f"SELECT kind,status,sum(CASE WHEN status='committed' THEN actual_amount ELSE reserved_amount END) AS amount "
            f"FROM {self.schema}.budget_reservations WHERE run_id=$1 AND status<>'released' GROUP BY kind,status",
            UUID(self.run_id))
        totals = {"committed": {}, "reserved": {}, "uncertain": {}}
        for row in rows:
            totals[row["status"]][BudgetKind(row["kind"])] = int(row["amount"])
        return BudgetUsage(run_id=self.run_id, **totals,
            limits={kind: min(self.caps[kind], int(pinned[kind.value])) for kind in self.caps})

    @_storage_errors
    async def usage(self, run_id: str) -> BudgetUsage:
        self._check_run(run_id)
        async with self._locked(require_active=False) as conn:
            return await self._usage(conn)

    @_storage_errors
    async def reserve(self, run_id: str, kind: BudgetKind, amount: int) -> BudgetReservation:
        self._check_run(run_id)
        if kind not in self.caps or type(amount) is not int or amount < 1:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Invalid budget reservation", port="BudgetStore")
        async with self._locked(require_active=True) as conn:
            usage = await self._usage(conn)
            charged = sum(part.get(kind, 0) for part in (usage.committed, usage.reserved, usage.uncertain))
            if charged + amount > usage.limits[kind]:
                raise PortError(AgentErrorCode.BUDGET_EXHAUSTED, f"Run {kind.value} budget exhausted", port="BudgetStore")
            reservation_id = uuid4()
            created = await conn.fetchval(
                f"INSERT INTO {self.schema}.budget_reservations "
                "(reservation_id,run_id,fencing_token,kind,reserved_amount,status) "
                "VALUES($1,$2,$3,$4,$5,'reserved') RETURNING created_at",
                reservation_id, UUID(self.run_id), self.fencing_token, kind.value, amount)
            return BudgetReservation(reservation_id=str(reservation_id), run_id=self.run_id,
                                     kind=kind, reserved_amount=amount, created_at=created)

    async def _resolve(self, reservation: BudgetReservation, actual: int | None, *, classification: str | None = None) -> None:
        self._check_run(reservation.run_id)
        async with self._locked(require_active=False) as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.schema}.budget_reservations WHERE reservation_id=$1 AND run_id=$2 FOR UPDATE",
                UUID(reservation.reservation_id), UUID(self.run_id))
            if (row is None or row["fencing_token"] != self.fencing_token
                    or row["kind"] != reservation.kind.value or row["reserved_amount"] != reservation.reserved_amount):
                raise PortError(AgentErrorCode.VALIDATION_ERROR, "Unknown or mismatched budget reservation", port="BudgetStore")
            target = "uncertain" if classification == "uncertain" else "released" if actual is None else "committed"
            reason = {"estimated": "provider_estimated", "uncertain": "provider_interrupted"}.get(classification)
            if row["status"] == target and row["actual_amount"] == actual and row["uncertainty_reason"] == reason:
                return  # A retry after a lost DB response must not double charge.
            if row["status"] != "reserved":
                raise PortError(AgentErrorCode.VALIDATION_ERROR, "Budget reservation was already resolved", port="BudgetStore")
            alive = await conn.fetchval(
                f"SELECT status='running' AND lease_until>clock_timestamp() FROM {self.schema}.jobs WHERE run_id=$1",
                UUID(self.run_id))
            if not alive:
                raise PortError(AgentErrorCode.CANCELLED,
                    "An expired execution cannot refund a budget reservation", port="BudgetStore")
            await conn.execute(
                f"UPDATE {self.schema}.budget_reservations SET status=$2,actual_amount=$3,uncertainty_reason=$4,resolved_at=now() WHERE reservation_id=$1",
                UUID(reservation.reservation_id), target, actual, reason)

    @_storage_errors
    async def commit(self, reservation: BudgetReservation, actual_amount: int) -> None:
        if type(actual_amount) is not int or actual_amount < 1:
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Invalid actual budget amount", port="BudgetStore")
        await self._resolve(reservation, actual_amount)

    @_storage_errors
    async def release(self, reservation: BudgetReservation) -> None:
        await self._resolve(reservation, None)

    @_storage_errors
    async def commit_embedding(self, reservation: BudgetReservation, actual_amount: int, classification: str) -> None:
        """Persist reported, estimated and uncertain embedding cost separately."""
        if (reservation.kind is not BudgetKind.TOKEN or type(actual_amount) is not int or actual_amount < 1
                or classification not in {"reported", "estimated", "uncertain"}
                or (classification == "uncertain" and actual_amount != reservation.reserved_amount)):
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "Invalid embedding usage classification", port="BudgetStore")
        await self._resolve(reservation, None if classification == "uncertain" else actual_amount,
                            classification=classification)
