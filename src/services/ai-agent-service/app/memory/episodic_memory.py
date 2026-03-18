"""Episodic Memory - Store and retrieve task execution episodes for learning.

Enables the agent to learn from past experiences by storing
Task → Plan → Execution → Outcome pairs.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.domain.interfaces.i_vector_store import IVectorStore
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.agents.planner_agent import Plan

logger = logging.getLogger(__name__)

# Collection name for episodic memories
EPISODIC_COLLECTION = "agent_episodes"


@dataclass
class Episode:
    """Represents a single execution episode."""

    episode_id: str
    task: str
    plan: Plan | dict[str, Any]
    execution_trace: list[dict[str, Any]]
    outcome: str
    success: bool
    confidence: float
    duration_seconds: float
    iterations: int
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "task": self.task,
            "plan": self.plan.to_dict() if isinstance(self.plan, Plan) else self.plan,
            "execution_trace": self.execution_trace,
            "outcome": self.outcome,
            "success": self.success,
            "confidence": self.confidence,
            "duration_seconds": self.duration_seconds,
            "iterations": self.iterations,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Episode":
        return cls(
            episode_id=data["episode_id"],
            task=data["task"],
            plan=data["plan"],
            execution_trace=data.get("execution_trace", []),
            outcome=data["outcome"],
            success=data["success"],
            confidence=data.get("confidence", 0.5),
            duration_seconds=data.get("duration_seconds", 0),
            iterations=data.get("iterations", 0),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {}),
        )


class EpisodicMemory:
    """Manages episodic memory for agent learning.

    Features:
    - Store successful/failed execution episodes
    - Retrieve similar past episodes by task similarity
    - Suggest plans based on past successful executions
    - Learn from failures to avoid repeating mistakes
    """

    def __init__(
        self,
        vector_store: IVectorStore | None = None,
        embedding_provider: IEmbeddingProvider | None = None,
        max_episodes: int = 1000,
    ):
        self._vector_store = vector_store
        self._embedding = embedding_provider
        self._max_episodes = max_episodes
        self._recent_episodes: list[Episode] = []
        self._lock = asyncio.Lock()

    async def store_episode(
        self,
        task: str,
        plan: Plan,
        execution_trace: list[dict[str, Any]],
        outcome: str,
        success: bool,
        confidence: float = 0.5,
        duration_seconds: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store an execution episode.

        Args:
            task: The task that was executed
            plan: The plan used
            execution_trace: Step-by-step execution trace
            outcome: Final outcome/answer
            success: Whether execution was successful
            confidence: Confidence score of the outcome
            duration_seconds: How long execution took
            metadata: Additional metadata

        Returns:
            Episode ID
        """
        episode_id = f"ep_{int(time.time() * 1000)}"

        episode = Episode(
            episode_id=episode_id,
            task=task,
            plan=plan,
            execution_trace=execution_trace,
            outcome=outcome,
            success=success,
            confidence=confidence,
            duration_seconds=duration_seconds,
            iterations=len(execution_trace),
            metadata=metadata or {},
        )

        # Store in recent episodes cache (lock protects append + slice-replace)
        async with self._lock:
            self._recent_episodes.append(episode)
            if len(self._recent_episodes) > 100:
                self._recent_episodes = self._recent_episodes[-100:]

        # Store in vector store for semantic search
        if self._vector_store and self._embedding:
            await self._store_to_vector_db(episode)

        logger.info(
            f"[EpisodicMemory] Stored episode {episode_id}: "
            f"success={success}, confidence={confidence:.2f}"
        )

        return episode_id

    async def _store_to_vector_db(self, episode: Episode) -> None:
        """Store episode to vector database."""
        if not self._vector_store or not self._embedding:
            return

        try:
            # Create searchable text from episode
            search_text = self._create_searchable_text(episode)

            # Generate embedding
            embedding = await self._embedding.embed(search_text)

            # Store with metadata
            self._vector_store.add_documents(
                collection_name=EPISODIC_COLLECTION,
                documents=[search_text],
                embeddings=[embedding],
                ids=[episode.episode_id],
                metadatas=[{
                    "task": episode.task[:500],
                    "success": episode.success,
                    "confidence": episode.confidence,
                    "iterations": episode.iterations,
                    "timestamp": episode.timestamp,
                    "episode_json": json.dumps(episode.to_dict()),
                }],
            )

        except Exception as e:
            logger.warning(f"[EpisodicMemory] Vector storage failed: {e}")

    def _create_searchable_text(self, episode: Episode) -> str:
        """Create searchable text representation of episode."""
        parts = [
            f"Task: {episode.task}",
            f"Outcome: {episode.outcome[:500]}",
        ]

        # Add successful plan steps for better matching
        if episode.success and isinstance(episode.plan, Plan):
            for step in episode.plan.steps:
                parts.append(f"Step: {step.action} - {step.description}")

        return " | ".join(parts)

    async def retrieve_similar_episodes(
        self,
        task: str,
        k: int = 3,
        success_only: bool = False,
    ) -> list[Episode]:
        """Retrieve similar past episodes.

        Args:
            task: Query task
            k: Maximum episodes to retrieve
            success_only: Only return successful episodes

        Returns:
            List of similar episodes
        """
        episodes = []

        # First check recent episodes (fast path)
        recent_matches = await self._search_recent_episodes(task, k)
        episodes.extend(recent_matches)

        # Then search vector store
        if self._vector_store and self._embedding and len(episodes) < k:
            try:
                embedding = await self._embedding.embed(task)

                where_filter = None
                if success_only:
                    where_filter = {"success": True}

                results = self._vector_store.query(
                    collection_name=EPISODIC_COLLECTION,
                    query_embeddings=[embedding],
                    n_results=k - len(episodes),
                    where=where_filter,
                )

                if results and results.get("metadatas"):
                    for meta in results["metadatas"][0]:
                        try:
                            episode_json = meta.get("episode_json", "{}")
                            episode_data = json.loads(episode_json)
                            episode = Episode.from_dict(episode_data)

                            # Avoid duplicates
                            if episode.episode_id not in [e.episode_id for e in episodes]:
                                episodes.append(episode)
                        except Exception as e:
                            logger.debug(f"[EpisodicMemory] Failed to parse episode: {e}")

            except Exception as e:
                logger.warning(f"[EpisodicMemory] Vector search failed: {e}")

        logger.info(
            f"[EpisodicMemory] Retrieved {len(episodes)} similar episodes for task"
        )
        return episodes[:k]

    async def _search_recent_episodes(self, task: str, k: int) -> list[Episode]:
        """Search recent episodes by keyword matching (snapshot under lock)."""
        async with self._lock:
            snapshot = list(self._recent_episodes)

        task_lower = task.lower()
        matches = []
        for episode in reversed(snapshot):
            episode_lower = episode.task.lower()
            overlap = sum(1 for word in task_lower.split() if word in episode_lower)
            if overlap >= 2:
                matches.append(episode)
                if len(matches) >= k:
                    break
        return matches

    async def suggest_plan(
        self,
        task: str,
    ) -> tuple[Plan | None, float]:
        """Suggest a plan based on similar successful episodes.

        Args:
            task: The task to plan for

        Returns:
            Tuple of (suggested_plan, confidence)
        """
        similar = await self.retrieve_similar_episodes(
            task=task,
            k=5,
            success_only=True,
        )

        if not similar:
            return None, 0.0

        # Find best matching episode
        best_episode = None
        best_score = 0.0

        for episode in similar:
            # Score based on similarity indicators
            score = episode.confidence
            if episode.success:
                score += 0.2
            if episode.iterations <= 3:  # Efficient execution
                score += 0.1

            if score > best_score:
                best_score = score
                best_episode = episode

        if best_episode and isinstance(best_episode.plan, Plan):
            logger.info(
                f"[EpisodicMemory] Suggesting plan from episode "
                f"{best_episode.episode_id} (score: {best_score:.2f})"
            )
            return best_episode.plan, min(best_score, 1.0)

        if best_episode and isinstance(best_episode.plan, dict):
            # Reconstruct plan from dict
            try:
                from app.agents.planner_agent import PlanStep

                steps = [
                    PlanStep(
                        step_number=s["step_number"],
                        step_type=StepType(s["step_type"]),
                        action=s["action"],
                        description=s["description"],
                        input_hint=s["input_hint"],
                        expected_output=s["expected_output"],
                        status=s.get("status", "pending"),
                    )
                    for s in best_episode.plan.get("steps", [])
                ]

                plan = Plan(
                    task=task,
                    steps=steps,
                    success_criteria=best_episode.plan.get("success_criteria", ""),
                    max_iterations=best_episode.plan.get("max_iterations", 5),
                )
                return plan, min(best_score, 1.0)
            except Exception as e:
                logger.warning(f"[EpisodicMemory] Failed to reconstruct plan: {e}")

        return None, 0.0

    async def get_failure_patterns(
        self,
        task: str,
    ) -> list[dict[str, Any]]:
        """Get patterns from failed executions of similar tasks.

        Args:
            task: The task to check

        Returns:
            List of failure patterns to avoid
        """
        failed_episodes = await self.retrieve_similar_episodes(
            task=task,
            k=10,
            success_only=False,
        )

        patterns = []
        for episode in failed_episodes:
            if not episode.success:
                # Extract failure information
                pattern = {
                    "episode_id": episode.episode_id,
                    "failed_step": None,
                    "error_type": "unknown",
                    "suggestion": "Try alternative approach",
                }

                # Analyze execution trace for failure point
                for step in episode.execution_trace:
                    if step.get("status") == "failed":
                        pattern["failed_step"] = step.get("action")
                        if "error" in step:
                            pattern["error_type"] = self._categorize_error(
                                step["error"]
                            )
                        break

                patterns.append(pattern)

        return patterns

    @staticmethod
    def _categorize_error(error: str) -> str:
        """Categorize an error message."""
        lower = error.lower()

        if "timeout" in lower:
            return "timeout"
        elif "not found" in lower:
            return "not_found"
        elif "permission" in lower or "unauthorized" in lower:
            return "permission"
        elif "connection" in lower:
            return "connection"
        elif "invalid" in lower:
            return "invalid_input"
        else:
            return "unknown"

    def get_stats(self) -> dict[str, Any]:
        """Get episodic memory statistics."""
        if not self._recent_episodes:
            return {
                "total_episodes": 0,
                "success_rate": 0,
                "avg_iterations": 0,
            }

        total = len(self._recent_episodes)
        successful = sum(1 for e in self._recent_episodes if e.success)
        total_iterations = sum(e.iterations for e in self._recent_episodes)

        return {
            "total_episodes": total,
            "success_rate": successful / total if total > 0 else 0,
            "avg_iterations": total_iterations / total if total > 0 else 0,
            "recent_cached": len(self._recent_episodes),
        }


# Import StepType for plan reconstruction
from app.agents.planner_agent import StepType
