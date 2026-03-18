"""Content agent — title / excerpt / tags / content improvement generation."""

import logging
from typing import Any

from langgraph.graph import StateGraph

from app.agents.base_agent import BaseSpecializedAgent
from app.services.analysis_service import AnalysisService

logger = logging.getLogger(__name__)


class ContentAgent(BaseSpecializedAgent):
    """Handles content generation tasks (title, excerpt, tags, improvement).

    Wraps existing ``AnalysisService`` methods.
    """

    def __init__(self, analysis_service: AnalysisService):
        self._analysis = analysis_service

    @property
    def name(self) -> str:
        return "content"

    def get_graph(self) -> StateGraph:
        return None  # type: ignore[return-value]

    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:
        content = payload.get("content", "")
        event_type = payload.get("_event_type", "title")

        if event_type == "title":
            summary = await self._analysis.summarize_article(content, 1, language)
            return {"title": summary}
        elif event_type == "excerpt":
            summary = await self._analysis.summarize_article(content, 3, language)
            return {"excerpt": summary}
        elif event_type == "tags":
            keywords = await self._analysis.extract_keywords(content, 5, language)
            return {"tags": keywords}
        elif event_type == "content":
            summary = await self._analysis.summarize_article(content, 3, language)
            return {"improvedContent": summary}
        else:
            raise ValueError(f"ContentAgent: unsupported event_type={event_type}")
