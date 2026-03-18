"""Conversation memory service - short-term Redis + long-term ChromaDB."""

import json
import logging
import re
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.domain.interfaces.i_vector_store import IVectorStore
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider

logger = logging.getLogger(__name__)

STM_MAX_MESSAGES = 100
STM_TTL_SECONDS = 86400
STM_KEY_PREFIX = "chat_history"
LTM_COLLECTION = "user_memories"

IMPORTANCE_KEYWORDS = {
    "tr": [
        "onemli", "kritik", "dikkat", "uyari", "hata", "cozum",
        "ozet", "sonuc", "karar", "strateji", "oneri", "tavsiye",
    ],
    "en": [
        "important", "critical", "warning", "error", "solution",
        "summary", "conclusion", "decision", "strategy", "recommendation",
    ],
}


class ConversationMemoryService:
    """Manages conversation memory with short-term and long-term layers."""

    def __init__(
        self,
        redis_url: str | None = None,
        vector_store: IVectorStore | None = None,
        embedding_provider: IEmbeddingProvider | None = None,
    ):
        self._redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None
        self._vector_store = vector_store
        self._embedding = embedding_provider

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

    def _stm_key(self, session_id: str) -> str:
        return f"{STM_KEY_PREFIX}:{session_id}"

    @staticmethod
    def _stm_guard_key(session_id: str, operation_id: str, role: str) -> str:
        return f"chatmsg:{session_id}:{operation_id}:{role}"

    @staticmethod
    def _ltm_doc_id(session_id: str, role: str, operation_id: str | None) -> str:
        if not operation_id:
            return f"mem_{session_id}_{int(time.time() * 1000)}"
        safe_operation_id = re.sub(r"[^a-zA-Z0-9_-]", "_", operation_id)
        return f"mem_{session_id}_{safe_operation_id}_{role}"

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> None:
        """Append a message to the session memory, skipping duplicates per operation."""
        r = await self._get_redis()
        if operation_id:
            guard_key = self._stm_guard_key(session_id, operation_id, role)
            claimed = await r.set(guard_key, "1", ex=STM_TTL_SECONDS, nx=True)
            if not claimed:
                logger.debug(
                    "[STM] Duplicate message skipped for session=%s operation=%s role=%s",
                    session_id,
                    operation_id,
                    role,
                )
                return

        key = self._stm_key(session_id)
        entry_metadata = dict(metadata or {})
        if operation_id and "operationId" not in entry_metadata:
            entry_metadata["operationId"] = operation_id

        entry = json.dumps({
            "role": role,
            "content": content,
            "ts": time.time(),
            "meta": entry_metadata,
        })

        pipe = r.pipeline()
        pipe.lpush(key, entry)
        pipe.ltrim(key, 0, STM_MAX_MESSAGES - 1)
        pipe.expire(key, STM_TTL_SECONDS)
        await pipe.execute()

        if self._is_important(content):
            await self._store_to_ltm(session_id, role, content, entry_metadata, operation_id)

    async def get_conversation_history(
        self, session_id: str, last_n: int = 10
    ) -> list[dict[str, Any]]:
        """Retrieve the most recent messages in chronological order."""
        r = await self._get_redis()
        key = self._stm_key(session_id)
        raw = await r.lrange(key, 0, last_n - 1)
        return [json.loads(item) for item in reversed(raw)]

    async def _store_to_ltm(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> None:
        """Embed and store an important message in ChromaDB."""
        if not self._vector_store or not self._embedding:
            return

        try:
            embedding = await self._embedding.embed(content)
            doc_id = self._ltm_doc_id(session_id, role, operation_id)
            self._vector_store.add_documents(
                collection_name=LTM_COLLECTION,
                documents=[content],
                embeddings=[embedding],
                ids=[doc_id],
                metadatas=[{
                    "session_id": session_id,
                    "role": role,
                    "ts": time.time(),
                    **(metadata or {}),
                }],
            )
            logger.debug("[LTM] Stored important message %s", doc_id)
        except Exception as e:
            logger.warning("[LTM] Failed to store message: %s", e)

    async def get_relevant_memories(
        self, session_id: str, query: str, k: int = 3
    ) -> list[dict[str, Any]]:
        """Semantic search over long-term memories for a session."""
        if not self._vector_store or not self._embedding:
            return []

        try:
            embedding = await self._embedding.embed(query)
            results = self._vector_store.query(
                collection_name=LTM_COLLECTION,
                query_embeddings=[embedding],
                n_results=k,
                where={"session_id": session_id},
            )

            memories = []
            if results and results.get("documents"):
                for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                    memories.append({"content": doc, "metadata": meta})
            return memories
        except Exception as e:
            logger.warning("[LTM] Semantic search failed: %s", e)
            return []

    @staticmethod
    def _is_important(content: str) -> bool:
        """Keyword-based importance heuristic for LTM persistence."""
        lower = content.lower()
        if len(lower) > 500:
            return True
        all_keywords = IMPORTANCE_KEYWORDS["tr"] + IMPORTANCE_KEYWORDS["en"]
        return any(keyword in lower for keyword in all_keywords)
