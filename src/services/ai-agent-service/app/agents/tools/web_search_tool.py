"""Web search tool for ReAct agent."""

import logging
from typing import Any

from app.domain.interfaces.i_web_search import IWebSearchProvider

logger = logging.getLogger(__name__)


class WebSearchTool:
    """Wraps IWebSearchProvider as a callable tool for the ReAct loop."""

    name: str = "web_search"
    description: str = "Search the web for information related to the query."

    def __init__(self, web_search_provider: IWebSearchProvider):
        self._provider = web_search_provider

    async def __call__(self, query: str, **kwargs: Any) -> str:
        """Execute web search and return formatted results."""
        try:
            max_results = kwargs.get("max_results", 5)
            region = kwargs.get("region", "us-en")
            response = await self._provider.search(
                query=query, max_results=max_results, region=region
            )
            if not response.has_results:
                return "No web search results found."

            lines = []
            for r in response.results[:5]:
                lines.append(f"- {r.title}: {r.snippet}")
            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"[WebSearchTool] Search failed: {e}")
            return f"Web search failed: {e}"
