"""SEO agent — wraps SeoService for LangGraph dispatch."""

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from app.agents.base_agent import BaseSpecializedAgent
from app.services.seo_service import SeoService

logger = logging.getLogger(__name__)


class SeoAgent(BaseSpecializedAgent):
    """Handles SEO description generation via the existing SeoService."""

    def __init__(self, seo_service: SeoService):
        self._seo = seo_service

    @property
    def name(self) -> str:
        return "seo"

    def get_graph(self) -> StateGraph:
        # Thin agent — no sub-graph needed, execute() suffices.
        return None  # type: ignore[return-value]

    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:
        content = payload.get("content", "")
        description = await self._seo.generate_seo_description(
            content=content, language=language
        )
        return {"description": description}
