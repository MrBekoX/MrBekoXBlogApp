"""B6 iş deposu sözleşmesinin test double'ı (B7 testleri kullanır).

B6 worker'ı PARALEL geliştirildiği için (W5 dispatch kuralı: "Store sözleşmesinin
B6 tarafını (claim/complete) test double ile temsil et") bu double, ortak store
sözleşmesinin B6 yarısını SÖZLEŞME METNİNE göre uygular:

- ``claim_next_job``: queued→running, execution_attempt+=1, fencing_token üretir.
  Sözleşmede claim'e cancel guard'ı yazılmamıştır; worker BAŞLANGIÇ kontrolü
  ``start_allowed`` ile cancel_intents'e bakar (plan: "Worker güvenli sınırlarda
  iptali kontrol etsin").
- ``complete_job``/``fail_job``: ATOMİK guard — status='running' VE fencing eş
  VE aktif cancel intent YOK → terminal yazılır; aksi 'rejected'.

GERÇEK B6 store'u ile uçtan uca iptal yarışı testleri BÜTÜNLEŞTİRME fazında
koşulacaktır (dispatch notu); bu double yalnız sözleşme davranışını temsil eder.
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any

import asyncpg

__all__ = ["B6WorkerStoreDouble"]


class B6WorkerStoreDouble:
    """Ortak sözleşmenin B6 tarafının DB üstünde çalışan test double'ı."""

    def __init__(self, pool: asyncpg.Pool, schema: str = "agent", worker_id: str = "worker-double") -> None:
        self._pool = pool
        self._schema = schema
        self._worker_id = worker_id

    async def claim_next_job(self, *, queue_class: str = "fast") -> dict[str, Any] | None:
        """queued işi lease ile running'e geçirir (FOR UPDATE SKIP LOCKED)."""

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"UPDATE {self._schema}.jobs SET "
                    "status = 'running', "
                    "lease_owner = $2, "
                    "lease_until = now() + make_interval(secs => $3), "
                    "execution_attempt = execution_attempt + 1, "
                    "fencing_token = $4 "
                    "WHERE run_id = ("
                    f"  SELECT run_id FROM {self._schema}.jobs "
                    "  WHERE status = 'queued' AND queue_class = $1 "
                    "  ORDER BY accepted_at LIMIT 1 "
                    "  FOR UPDATE SKIP LOCKED) "
                    "RETURNING run_id, execution_attempt, fencing_token, conversation_id, correlation_id",
                    queue_class,
                    self._worker_id,
                    30.0,
                    f"fnc-{secrets.token_hex(8)}",
                )
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "execution_attempt": int(row["execution_attempt"]),
            "fencing_token": str(row["fencing_token"]),
            "conversation_id": str(row["conversation_id"]),
            "correlation_id": str(row["correlation_id"]),
        }

    async def complete_job(self, run_id: str, result_json: dict[str, Any], fencing_token: str) -> str:
        """Sözleşme guard'ı: running + fencing eş + cancel intent yok → completed; aksi 'rejected'."""

        async with self._pool.acquire() as conn:
            updated = await conn.fetchrow(
                f"UPDATE {self._schema}.jobs SET status = 'completed', result_json = $3::jsonb "
                "WHERE run_id = $1 AND status = 'running' AND fencing_token = $2 "
                f"AND NOT EXISTS (SELECT 1 FROM {self._schema}.cancel_intents WHERE run_id = $1) "
                "RETURNING run_id",
                uuid.UUID(run_id),
                fencing_token,
                json.dumps(result_json),
            )
        return "completed" if updated is not None else "rejected"

    async def fail_job(self, run_id: str, error: dict[str, Any], fencing_token: str) -> str:
        """complete_job ile aynı guard; terminal 'failed'."""

        async with self._pool.acquire() as conn:
            updated = await conn.fetchrow(
                f"UPDATE {self._schema}.jobs SET status = 'failed', result_json = $3::jsonb "
                "WHERE run_id = $1 AND status = 'running' AND fencing_token = $2 "
                f"AND NOT EXISTS (SELECT 1 FROM {self._schema}.cancel_intents WHERE run_id = $1) "
                "RETURNING run_id",
                uuid.UUID(run_id),
                fencing_token,
                json.dumps(error),
            )
        return "failed" if updated is not None else "rejected"
