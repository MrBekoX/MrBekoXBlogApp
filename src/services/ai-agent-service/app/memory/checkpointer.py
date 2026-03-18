"""LangGraph Checkpointer - Redis-based state persistence for agents.

Provides checkpointing for LangGraph agents to:
- Persist agent state across executions
- Resume interrupted conversations
- Enable time-travel debugging
"""

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Checkpoint config
CHECKPOINT_TTL = 86400  # 24 hours
CHECKPOINT_KEY_PREFIX = "lg_checkpoint"
CHECKPOINT_THREAD_PREFIX = "lg_thread"


class RedisCheckpointer:
    """Redis-based checkpointer for LangGraph agents.
    
    Stores checkpoints as JSON blobs in Redis with TTL.
    Compatible with LangGraph's checkpointer interface.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        ttl: int = CHECKPOINT_TTL,
    ):
        self._redis_url = redis_url or settings.redis_url
        self._ttl = ttl
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url, encoding="utf-8", decode_responses=True
            )
        return self._redis

    async def shutdown(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def _checkpoint_key(self, thread_id: str, checkpoint_id: str) -> str:
        return f"{CHECKPOINT_KEY_PREFIX}:{thread_id}:{checkpoint_id}"

    def _thread_key(self, thread_id: str) -> str:
        return f"{CHECKPOINT_THREAD_PREFIX}:{thread_id}"

    async def put(
        self,
        thread_id: str,
        checkpoint: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a checkpoint.

        Args:
            thread_id: Thread/conversation ID
            checkpoint: State to checkpoint
            metadata: Optional metadata

        Returns:
            Checkpoint ID
        """
        r = await self._get_redis()
        checkpoint_id = f"cp_{int(time.time() * 1000)}"
        key = self._checkpoint_key(thread_id, checkpoint_id)

        data = {
            "checkpoint": checkpoint,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }

        # Store checkpoint
        await r.setex(key, self._ttl, json.dumps(data))

        # Update thread index
        thread_key = self._thread_key(thread_id)
        await r.setex(thread_key, self._ttl, checkpoint_id)

        logger.debug(f"[Checkpointer] Stored checkpoint {checkpoint_id} for thread {thread_id}")
        return checkpoint_id

    async def get(
        self,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a checkpoint.

        Args:
            thread_id: Thread/conversation ID
            checkpoint_id: Specific checkpoint, or latest if None

        Returns:
            Checkpoint data or None if not found
        """
        r = await self._get_redis()

        if checkpoint_id is None:
            # Get latest checkpoint ID from thread index
            thread_key = self._thread_key(thread_id)
            checkpoint_id = await r.get(thread_key)
            if not checkpoint_id:
                return None

        key = self._checkpoint_key(thread_id, checkpoint_id)
        data = await r.get(key)

        if not data:
            return None

        return json.loads(data)

    async def list_checkpoints(
        self,
        thread_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List all checkpoints for a thread.

        Args:
            thread_id: Thread/conversation ID
            limit: Maximum checkpoints to return

        Returns:
            List of checkpoint metadata
        """
        r = await self._get_redis()
        pattern = f"{CHECKPOINT_KEY_PREFIX}:{thread_id}:*"
        keys = await r.keys(pattern)

        checkpoints = []
        for key in keys[:limit]:
            data = await r.get(key)
            if data:
                checkpoints.append(json.loads(data))

        # Sort by timestamp
        checkpoints.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return checkpoints

    async def delete(
        self,
        thread_id: str,
        checkpoint_id: str,
    ) -> bool:
        """Delete a specific checkpoint.

        Args:
            thread_id: Thread/conversation ID
            checkpoint_id: Checkpoint to delete

        Returns:
            True if deleted, False if not found
        """
        r = await self._get_redis()
        key = self._checkpoint_key(thread_id, checkpoint_id)
        deleted = await r.delete(key)

        if deleted:
            logger.debug(f"[Checkpointer] Deleted checkpoint {checkpoint_id}")

        return bool(deleted)

    async def delete_thread(self, thread_id: str) -> int:
        """Delete all checkpoints for a thread.

        Args:
            thread_id: Thread/conversation ID

        Returns:
            Number of checkpoints deleted
        """
        r = await self._get_redis()
        pattern = f"{CHECKPOINT_KEY_PREFIX}:{thread_id}:*"
        keys = await r.keys(pattern)

        if keys:
            deleted = await r.delete(*keys)
            # Also delete thread index
            await r.delete(self._thread_key(thread_id))
            logger.debug(f"[Checkpointer] Deleted {deleted} checkpoints for thread {thread_id}")
            return deleted

        return 0


class MemorySaver:
    """Simplified checkpointer interface compatible with LangGraph.
    
    Wraps RedisCheckpointer to match LangGraph's MemorySaver interface.
    """

    def __init__(self, checkpointer: RedisCheckpointer | None = None):
        self._checkpointer = checkpointer or RedisCheckpointer()

    async def aget(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Get checkpoint from config."""
        thread_id = config.get("configurable", {}).get("thread_id", "")
        if not thread_id:
            return None
        return await self._checkpointer.get(thread_id)

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Put checkpoint with config."""
        thread_id = config.get("configurable", {}).get("thread_id", "")
        if not thread_id:
            thread_id = f"auto_{int(time.time() * 1000)}"
        return await self._checkpointer.put(thread_id, checkpoint, metadata)

    async def shutdown(self) -> None:
        await self._checkpointer.shutdown()


# Global checkpointer instance
_checkpointer: RedisCheckpointer | None = None


def get_checkpointer() -> RedisCheckpointer:
    """Get the global checkpointer instance."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = RedisCheckpointer()
    return _checkpointer


def get_memory_saver() -> MemorySaver:
    """Get a MemorySaver instance for LangGraph."""
    return MemorySaver(get_checkpointer())
