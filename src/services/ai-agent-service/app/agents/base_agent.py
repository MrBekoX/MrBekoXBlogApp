"""Base class for all specialized agents."""

from abc import ABC, abstractmethod
from typing import Any

from langgraph.graph import StateGraph


class BaseSpecializedAgent(ABC):
    """Abstract base for specialized LangGraph sub-agents.

    Each concrete agent builds its own LangGraph sub-graph and exposes
    an ``execute`` entry point that the Supervisor calls.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent name used for routing."""

    @abstractmethod
    def get_graph(self) -> StateGraph:
        """Build and return the compiled LangGraph sub-graph."""

    @abstractmethod
    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:
        """Execute the agent's task and return results.

        Args:
            payload: The message payload from the event.
            language: Content language code.

        Returns:
            Dict with agent-specific result keys.
        """
