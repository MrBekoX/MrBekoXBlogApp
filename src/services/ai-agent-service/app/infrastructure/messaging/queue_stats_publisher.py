"""Publishes queue depth and circuit breaker state to Redis.

Backend reads these keys to make backpressure decisions.
Frontend receives them via SignalR for queue depth signaling.
"""

import json
import logging
from datetime import datetime, timezone

from app.domain.interfaces.i_cache import ICache

logger = logging.getLogger(__name__)

# Redis key constants
QUEUE_STATS_PREFIX = "queue:stats"
CIRCUIT_STATE_KEY = f"{QUEUE_STATS_PREFIX}:ollama:circuit_state"
RETRY_INFLIGHT_KEY = "retry:inflight:count"


class QueueStatsPublisher:
    """Writes queue depth statistics to Redis for cross-service visibility."""

    def __init__(self, cache: ICache, ttl_seconds: int = 30):
        self._cache = cache
        self._ttl = ttl_seconds

    async def publish_queue_depth(
        self, queue_name: str, depth: int, consumer_count: int | None = None
    ) -> None:
        """Write queue depth for a specific queue to Redis."""
        key = f"{QUEUE_STATS_PREFIX}:{queue_name}"
        value = {
            "depth": depth,
            "consumer_count": consumer_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._cache.set_json(key, value, ttl_seconds=self._ttl)
        except Exception as e:
            logger.warning(f"Failed to publish queue stats for {queue_name}: {e}")

    async def publish_circuit_state(self, state: str) -> None:
        """Write Ollama circuit breaker state to Redis."""
        try:
            await self._cache.set_json(
                CIRCUIT_STATE_KEY,
                {"state": state, "updated_at": datetime.now(timezone.utc).isoformat()},
                ttl_seconds=self._ttl,
            )
        except Exception as e:
            logger.warning(f"Failed to publish circuit state: {e}")

    async def get_retry_inflight_count(self) -> int:
        """Get current retry inflight count from Redis."""
        try:
            val = await self._cache.get_json(RETRY_INFLIGHT_KEY)
            return int(val.get("count", 0)) if val else 0
        except Exception:
            return 0

    async def increment_retry_inflight(self) -> int:
        """Atomically increment retry inflight counter. Returns new value."""
        try:
            rc = self._cache.client  # RedisAdapter.client property (raises if not connected)
            new_val = await rc.incr(RETRY_INFLIGHT_KEY)
            await rc.expire(RETRY_INFLIGHT_KEY, 300)  # 5 min TTL safety
            return int(new_val)
        except Exception as e:
            logger.warning(f"Failed to increment retry inflight: {e}")
            return 0

    async def decrement_retry_inflight(self) -> None:
        """Atomically decrement retry inflight counter."""
        try:
            rc = self._cache.client
            val = await rc.decr(RETRY_INFLIGHT_KEY)
            if val < 0:
                await rc.set(RETRY_INFLIGHT_KEY, 0, ex=300)
        except Exception as e:
            logger.warning(f"Failed to decrement retry inflight: {e}")
