"""Analysis agent — parallel article analysis via LangGraph sub-graph."""

import asyncio
import logging
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from app.agents.base_agent import BaseSpecializedAgent
from app.services.analysis_service import AnalysisService
from app.services.indexing_service import IndexingService

logger = logging.getLogger(__name__)


class AnalysisState(TypedDict, total=False):
    """State for the analysis sub-graph."""

    content: str
    article_id: str
    title: str
    language: str
    region: str
    # Parallel results
    summary: str | None
    keywords: list[str] | None
    sentiment: dict | None
    seo_description: str | None
    geo_optimization: dict | None
    reading_time: dict | None
    # Indexing outcome
    indexing_status: str | None
    indexing_error: str | None
    # Merged output
    result: dict[str, Any] | None
    error: str | None


class AnalysisAgent(BaseSpecializedAgent):
    """Performs full article analysis with parallel LLM calls.

    Wraps existing ``AnalysisService`` and ``IndexingService`` methods
    as LangGraph nodes, running summarize / keywords / sentiment / seo / geo
    in parallel and merging results.
    """

    def __init__(
        self,
        analysis_service: AnalysisService,
        indexing_service: IndexingService,
    ):
        self._analysis = analysis_service
        self._indexing = indexing_service
        self._graph = self._build_graph()

    @property
    def name(self) -> str:
        return "analyzer"

    def get_graph(self) -> StateGraph:
        return self._graph

    def _build_graph(self) -> Any:
        builder = StateGraph(AnalysisState)

        builder.add_node("index", self._index_node)
        builder.add_node("analyze_parallel", self._analyze_parallel_node)
        builder.add_node("aggregate", self._aggregate_node)

        builder.set_entry_point("index")
        builder.add_edge("index", "analyze_parallel")
        builder.add_edge("analyze_parallel", "aggregate")
        builder.add_edge("aggregate", END)

        return builder.compile()

    async def _index_node(self, state: AnalysisState) -> dict:
        """Index article for RAG retrieval.

        Indexing failures are tracked in state so that the workflow
        can still proceed with analysis, but the caller knows that
        RAG indexing did not succeed.
        """
        try:
            await self._indexing.index_article(
                post_id=state.get("article_id", ""),
                title=state.get("title", ""),
                content=state.get("content", ""),
            )
            return {"indexing_status": "success"}
        except Exception as e:
            logger.error(
                f"[AnalysisAgent:index] Indexing FAILED for article_id="
                f"{state.get('article_id', '?')}: {e}"
            )
            return {"indexing_status": "failed", "indexing_error": str(e)}

    async def _analyze_parallel_node(self, state: AnalysisState) -> dict:
        """Run all analysis tasks in parallel."""
        content = state.get("content", "")
        language = state.get("language", "tr")
        region = state.get("region", "TR")

        tasks = {
            "summary": self._analysis.summarize_article(content, language=language),
            "keywords": self._analysis.extract_keywords(content, language=language),
            "sentiment": self._analysis.analyze_sentiment(content, language=language),
        }

        if hasattr(self._analysis, "_seo_service") and self._analysis._seo_service:
            tasks["seo"] = self._analysis._seo_service.generate_seo_description(
                content, language=language
            )
            tasks["geo"] = self._analysis._seo_service.optimize_for_geo(
                content, region, language
            )
        else:
            tasks["seo"] = self._analysis._generate_seo_description(content, language)

        results = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )
        keys = list(tasks.keys())

        output: dict[str, Any] = {}
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                logger.warning(f"[AnalysisAgent] {key} failed: {result}")
                output[key] = None
            else:
                output[key] = result

        # Reading time is synchronous
        reading_time = self._analysis.calculate_reading_time(content)

        return {
            "summary": output.get("summary"),
            "keywords": output.get("keywords"),
            "sentiment": (
                output["sentiment"].model_dump()
                if output.get("sentiment") and hasattr(output["sentiment"], "model_dump")
                else (
                    {"sentiment": output["sentiment"].sentiment, "confidence": output["sentiment"].confidence}
                    if output.get("sentiment")
                    else None
                )
            ),
            "seo_description": output.get("seo"),
            "geo_optimization": (
                output["geo"].model_dump()
                if output.get("geo") and hasattr(output["geo"], "model_dump")
                else None
            ),
            "reading_time": {
                "reading_time_minutes": reading_time.reading_time_minutes,
                "word_count": reading_time.word_count,
            },
        }

    async def _aggregate_node(self, state: AnalysisState) -> dict:
        """Merge parallel results into a single result dict."""
        sentiment_data = state.get("sentiment") or {}
        reading_data = state.get("reading_time") or {}

        result = {
            "postId": state.get("article_id", ""),
            "summary": state.get("summary", ""),
            "keywords": state.get("keywords", []),
            "seoDescription": state.get("seo_description", ""),
            "readingTime": reading_data.get("reading_time_minutes", 1),
            "sentiment": sentiment_data.get("sentiment", "neutral"),
            "geoOptimization": state.get("geo_optimization"),
        }
        return {"result": result}

    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:
        """Execute full analysis pipeline."""
        initial: AnalysisState = {
            "content": payload.get("content", ""),
            "article_id": payload.get("articleId", ""),
            "title": payload.get("title", ""),
            "language": language,
            "region": payload.get("targetRegion", "TR"),
        }
        final = await self._graph.ainvoke(initial)
        return final.get("result", {})
