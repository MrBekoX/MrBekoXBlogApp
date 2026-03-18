from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class AdminReplayIdempotencyClaim:
    state: str
    request_hash: str
    response_payload: dict[str, Any] | None = None
    error_message: str | None = None


class AdminReplayIdempotencyStore:
    _key_prefix = "http:idempotency:admin:replay"

    def __init__(self, cache: Any):
        self._cache = cache
        self._processing_ttl_seconds = max(30, settings.worker_operation_timeout_seconds)
        self._retention_ttl_seconds = max(
            self._processing_ttl_seconds,
            settings.worker_operation_retention_seconds,
        )

    async def begin_request(
        self,
        operation_id: str,
        request_payload: dict[str, Any],
    ) -> AdminReplayIdempotencyClaim:
        request_hash = self.build_request_hash(request_payload)
        key = self._operation_key(operation_id)
        existing_json = await self._cache.get(key)
        now_ts = time.time()

        if existing_json:
            existing = json.loads(existing_json)
            existing_hash = existing.get("requestHash", "")
            if existing_hash and existing_hash != request_hash:
                return AdminReplayIdempotencyClaim(
                    state="conflict",
                    request_hash=request_hash,
                    error_message="The same Idempotency-Key was used with a different payload.",
                )

            status = existing.get("status", "processing")
            if status == "completed":
                return AdminReplayIdempotencyClaim(
                    state="completed",
                    request_hash=request_hash,
                    response_payload=existing.get("responsePayload"),
                )

            if status == "failed":
                return AdminReplayIdempotencyClaim(
                    state="failed",
                    request_hash=request_hash,
                    error_message=existing.get("errorMessage") or "Previous replay attempt failed.",
                )

            locked_until = float(existing.get("lockedUntil") or 0)
            if locked_until > now_ts:
                return AdminReplayIdempotencyClaim(
                    state="processing",
                    request_hash=request_hash,
                    error_message="This operation is already being processed.",
                )

        processing_record = {
            "status": "processing",
            "requestHash": request_hash,
            "lockedUntil": now_ts + self._processing_ttl_seconds,
            "updatedAt": self._utc_now_iso(),
        }
        await self._cache.set(
            key,
            json.dumps(processing_record),
            ttl_seconds=self._processing_ttl_seconds,
        )
        return AdminReplayIdempotencyClaim(state="started", request_hash=request_hash)

    async def complete_request(
        self,
        operation_id: str,
        request_hash: str,
        response_payload: dict[str, Any],
    ) -> None:
        completed_record = {
            "status": "completed",
            "requestHash": request_hash,
            "lockedUntil": 0,
            "responsePayload": response_payload,
            "updatedAt": self._utc_now_iso(),
            "completedAt": self._utc_now_iso(),
        }
        await self._cache.set(
            self._operation_key(operation_id),
            json.dumps(completed_record),
            ttl_seconds=self._retention_ttl_seconds,
        )

    async def fail_request(
        self,
        operation_id: str,
        request_hash: str,
        error_message: str,
    ) -> None:
        failed_record = {
            "status": "failed",
            "requestHash": request_hash,
            "lockedUntil": 0,
            "errorMessage": error_message[:2000],
            "updatedAt": self._utc_now_iso(),
            "completedAt": self._utc_now_iso(),
        }
        await self._cache.set(
            self._operation_key(operation_id),
            json.dumps(failed_record),
            ttl_seconds=self._retention_ttl_seconds,
        )

    @staticmethod
    def build_request_hash(request_payload: dict[str, Any]) -> str:
        serialized = json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def _operation_key(cls, operation_id: str) -> str:
        return f"{cls._key_prefix}:{operation_id}"

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
