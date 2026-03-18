"""Memory Search Tool - Search past conversations and learned information.

Integrates with the conversation memory service for long-term recall.
"""

import logging
from typing import Any

from app.memory.conversation_memory import ConversationMemoryService

logger = logging.getLogger(__name__)


class MemorySearchTool:
    """Tool for searching past conversations and stored memories.

    Enables the agent to recall information from previous interactions,
    creating continuity across sessions.
    """

    def __init__(
        self,
        memory_service: ConversationMemoryService,
        max_results: int = 5,
    ):
        self._memory = memory_service
        self._max_results = max_results

    async def __call__(
        self,
        query: str,
        session_id: str = "",
        k: int | None = None,
    ) -> str:
        """Search memories for relevant information.

        Args:
            query: Search query
            session_id: Optional session ID for session-specific search
            k: Number of results (default from constructor)

        Returns:
            Formatted string with relevant memories
        """
        if not self._memory:
            return "Memory service not available."

        k = k or self._max_results

        try:
            # Search long-term memories
            memories = await self._memory.get_relevant_memories(
                session_id=session_id or "global",
                query=query,
                k=k,
            )

            if not memories:
                return "No relevant memories found."

            # Format results
            results = []
            for i, mem in enumerate(memories, 1):
                content = mem.get("content", "")
                meta = mem.get("metadata", {})
                role = meta.get("role", "unknown")

                # Truncate long content
                if len(content) > 300:
                    content = content[:297] + "..."

                results.append(f"[{i}] ({role}): {content}")

            return "\n".join(results)

        except Exception as e:
            logger.error(f"[MemorySearch] Search failed: {e}")
            return f"Memory search error: {e}"

    async def search_sessions(
        self,
        query: str,
        session_ids: list[str],
        k_per_session: int = 2,
    ) -> dict[str, str]:
        """Search across multiple sessions.

        Args:
            query: Search query
            session_ids: List of session IDs to search
            k_per_session: Results per session

        Returns:
            Dict mapping session_id to results
        """
        results = {}

        for session_id in session_ids:
            try:
                result = await self(
                    query=query,
                    session_id=session_id,
                    k=k_per_session,
                )
                if "No relevant memories" not in result:
                    results[session_id] = result
            except Exception as e:
                logger.warning(f"[MemorySearch] Session {session_id} search failed: {e}")

        return results

    async def get_recent_context(
        self,
        session_id: str,
        last_n: int = 5,
    ) -> str:
        """Get recent conversation history for a session.

        Args:
            session_id: Session ID
            last_n: Number of recent messages

        Returns:
            Formatted conversation history
        """
        if not self._memory:
            return "Memory service not available."

        try:
            history = await self._memory.get_conversation_history(
                session_id=session_id,
                last_n=last_n,
            )

            if not history:
                return "No recent conversation history."

            lines = []
            for msg in history:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                lines.append(f"{role.capitalize()}: {content[:200]}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"[MemorySearch] History retrieval failed: {e}")
            return f"History retrieval error: {e}"


class MemoryStoreTool:
    """Tool for storing information to long-term memory.

    Allows the agent to explicitly save important information for future recall.
    """

    def __init__(
        self,
        memory_service: ConversationMemoryService,
    ):
        self._memory = memory_service

    async def __call__(
        self,
        content: str,
        session_id: str = "",
        role: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store information to long-term memory.

        Args:
            content: Content to store
            session_id: Associated session ID
            role: Role label (user, assistant, system)
            metadata: Additional metadata

        Returns:
            Confirmation message
        """
        if not self._memory:
            return "Memory service not available."

        try:
            await self._memory.add_message(
                session_id=session_id or "global",
                role=role,
                content=content,
                metadata=metadata or {"explicitly_stored": True},
            )

            logger.info(f"[MemoryStore] Stored content of length {len(content)}")
            return f"Stored to memory: {content[:100]}..."

        except Exception as e:
            logger.error(f"[MemoryStore] Storage failed: {e}")
            return f"Memory storage error: {e}"
