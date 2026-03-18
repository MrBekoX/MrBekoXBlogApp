"""Redis cache adapter - concrete implementation of ICache."""

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.domain.interfaces.i_cache import ICache, CacheLockLease
from app.monitoring.metrics import record_stale_processing_reclaim

logger = logging.getLogger(__name__)

_LOCK_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisAdapter(ICache):
    """Redis implementation of cache, locks, and operation inbox state."""

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or settings.redis_url
        self._client: redis.Redis | None = None
        self._operation_retention_seconds = max(1, settings.worker_operation_retention_seconds)

    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if self._client is None:
            logger.info("Connecting to Redis...")
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("Redis connection established")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis connection closed")

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    async def get(self, key: str) -> str | None:
        return await self.client.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if ttl_seconds:
            await self.client.set(key, value, ex=ttl_seconds)
        else:
            await self.client.set(key, value)

    async def get_json(self, key: str) -> Any | None:
        data = await self.get(key)
        if data:
            return json.loads(data)
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        await self.set(key, json.dumps(value), ttl_seconds)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        return await self.client.exists(key) > 0

    async def is_processed(self, message_id: str) -> bool:
        key = f"processed:event:{message_id}"
        return await self.client.exists(key) > 0

    async def mark_processed(self, message_id: str, ttl_seconds: int = 86400) -> None:
        key = f"processed:event:{message_id}"
        await self.client.set(key, "1", ex=max(1, ttl_seconds))

    async def acquire_lock(self, resource_id: str, ttl_seconds: int = 300) -> CacheLockLease | None:
        key = f"lock:resource:{resource_id}"
        token = secrets.token_urlsafe(32)
        result = await self.client.set(key, token, nx=True, ex=ttl_seconds)
        if result is None:
            return None
        return CacheLockLease(resource_id=resource_id, token=token)

    async def release_lock(self, lease: CacheLockLease) -> bool:
        key = f"lock:resource:{lease.resource_id}"
        try:
            deleted = await self.client.eval(_LOCK_RELEASE_SCRIPT, 1, key, lease.token)
        except Exception as exc:
            logger.warning("Distributed lock release failed for %s: %s", lease.resource_id, exc)
            return False

        if int(deleted or 0) == 0:
            logger.warning("Skipped lock release for %s because token no longer matched", lease.resource_id)
            return False
        return True

    async def claim_operation(
        self,
        consumer_name: str,
        operation_id: str,
        message_id: str,
        correlation_id: str | None = None,
        lock_ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        key = self._operation_key(consumer_name, operation_id)
        now_ts = datetime.now(timezone.utc).timestamp()
        now_iso = self._utc_now_iso()

        for _ in range(5):
            async with self.client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    existing = await pipe.hgetall(key)
                    was_stale_reclaim = False

                    if existing:
                        parsed = self._deserialize_operation(existing)
                        status = parsed.get("status", "processing")
                        locked_until = float(parsed.get("locked_until") or 0)

                        if status == "completed":
                            await pipe.unwatch()
                            parsed["state"] = "duplicate_completed"
                            return parsed

                        if status == "failed":
                            await pipe.unwatch()
                            parsed["state"] = "duplicate_failed"
                            return parsed

                        if locked_until > now_ts:
                            await pipe.unwatch()
                            parsed["state"] = "duplicate_processing"
                            return parsed

                        attempt_count = int(parsed.get("attempt_count") or 0) + 1
                        was_stale_reclaim = True
                    else:
                        parsed = {}
                        attempt_count = 1

                    mapping = {
                        "status": "processing",
                        "message_id": message_id,
                        "correlation_id": correlation_id or parsed.get("correlation_id", ""),
                        "locked_until": str(now_ts + max(1, lock_ttl_seconds)),
                        "attempt_count": str(attempt_count),
                        "started_at": parsed.get("started_at") or now_iso,
                        "updated_at": now_iso,
                        "last_error": "",
                    }

                    pipe.multi()
                    pipe.hset(key, mapping=mapping)
                    pipe.expire(key, self._operation_retention_seconds)
                    pipe.set(
                        self._message_index_key(message_id),
                        operation_id,
                        ex=max(lock_ttl_seconds * 10, self._operation_retention_seconds),
                    )
                    await pipe.execute()

                    if was_stale_reclaim:
                        logger.warning(
                            "Reclaimed stale processing state for %s/%s after lock expiry",
                            consumer_name,
                            operation_id,
                        )
                        record_stale_processing_reclaim(consumer_name)

                    claimed = await self.get_operation(consumer_name, operation_id)
                    if claimed is None:
                        raise RuntimeError("operation_claim_missing")
                    claimed["state"] = "claimed" if not existing else "reclaimed"
                    return claimed
                except redis.WatchError:
                    continue

        raise RuntimeError(f"Failed to claim operation {consumer_name}/{operation_id}")

    async def get_operation(self, consumer_name: str, operation_id: str) -> dict[str, Any] | None:
        data = await self.client.hgetall(self._operation_key(consumer_name, operation_id))
        if not data:
            return None
        return self._deserialize_operation(data)

    async def store_operation_response(
        self,
        consumer_name: str,
        operation_id: str,
        response_payload: dict[str, Any],
        routing_key: str,
    ) -> None:
        key = self._operation_key(consumer_name, operation_id)
        await self.client.hset(
            key,
            mapping={
                "response_payload_json": json.dumps(response_payload),
                "response_routing_key": routing_key,
                "updated_at": self._utc_now_iso(),
            },
        )
        await self.client.expire(key, self._operation_retention_seconds)

    async def mark_operation_completed(self, consumer_name: str, operation_id: str) -> None:
        key = self._operation_key(consumer_name, operation_id)
        await self.client.hset(
            key,
            mapping={
                "status": "completed",
                "locked_until": "0",
                "last_error": "",
                "completed_at": self._utc_now_iso(),
                "updated_at": self._utc_now_iso(),
            },
        )
        await self.client.expire(key, self._operation_retention_seconds)

    async def mark_operation_retryable(self, consumer_name: str, operation_id: str, error: str) -> None:
        key = self._operation_key(consumer_name, operation_id)
        await self.client.hset(
            key,
            mapping={
                "status": "processing",
                "locked_until": "0",
                "last_error": error[:2000],
                "updated_at": self._utc_now_iso(),
            },
        )
        await self.client.expire(key, self._operation_retention_seconds)

    async def mark_operation_failed(self, consumer_name: str, operation_id: str, error: str) -> None:
        key = self._operation_key(consumer_name, operation_id)
        await self.client.hset(
            key,
            mapping={
                "status": "failed",
                "locked_until": "0",
                "last_error": error[:2000],
                "completed_at": self._utc_now_iso(),
                "updated_at": self._utc_now_iso(),
            },
        )
        await self.client.expire(key, self._operation_retention_seconds)

    @staticmethod
    def _operation_key(consumer_name: str, operation_id: str) -> str:
        return f"inbox:{consumer_name}:{operation_id}"

    @staticmethod
    def _message_index_key(message_id: str) -> str:
        return f"message:{message_id}:operation"

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _deserialize_operation(data: dict[str, str]) -> dict[str, Any]:
        record: dict[str, Any] = dict(data)
        if "attempt_count" in record:
            try:
                record["attempt_count"] = int(record["attempt_count"])
            except (TypeError, ValueError):
                record["attempt_count"] = 0
        if "locked_until" in record:
            try:
                record["locked_until"] = float(record["locked_until"])
            except (TypeError, ValueError):
                record["locked_until"] = 0.0
        response_json = record.get("response_payload_json")
        if response_json:
            try:
                record["response_payload"] = json.loads(response_json)
            except json.JSONDecodeError:
                record["response_payload"] = None
        else:
            record["response_payload"] = None
        return record
