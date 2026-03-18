"""Dependency resolution layer for the AI agent service.

All dependencies are resolved from the central DI container
(app.container.ApplicationContainer). This module provides
FastAPI-compatible Depends() functions and backward-compatible
aliases for code that imports from here.

The old DependencyContainer class is preserved as a thin facade
over the container to avoid breaking existing health-check and
consumer code.
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as redis
from fastapi import Depends, HTTPException

from app.container import container
from app.core.config import settings
from app.domain.interfaces.i_cache import ICache
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.interfaces.i_message_broker import IMessageBroker
from app.domain.interfaces.i_vector_store import IVectorStore
from app.domain.interfaces.i_web_search import IWebSearchProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FastAPI Depends() functions — thin wrappers over the container
# ---------------------------------------------------------------------------

def get_llm_provider() -> ILLMProvider:
    """Return the shared LLM provider."""
    return container.llm_provider()


def get_redis_adapter():
    """Return the shared Redis adapter."""
    return container.redis_adapter()


def get_vector_store() -> IVectorStore:
    """Return the shared vector store."""
    return container.vector_store()


def get_cache() -> ICache:
    """Return the shared multi-level cache."""
    return container.cache()


def get_embedding_provider() -> IEmbeddingProvider:
    """Return the shared embedding provider."""
    return container.embedding_provider()


def get_message_broker() -> IMessageBroker:
    """Return the shared message broker."""
    return container.message_broker()


def get_web_search_provider() -> IWebSearchProvider:
    """Return the shared web search provider."""
    return container.web_search_provider()


def get_rabbitmq_adapter():
    """Return the concrete RabbitMQ adapter for admin operations."""
    from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter

    broker = container.message_broker()
    if not isinstance(broker, RabbitMQAdapter):
        raise HTTPException(status_code=503, detail="RabbitMQ adapter is unavailable")
    return broker


async def get_redis_client() -> redis.Redis:
    """Provide the async Redis client for rate limiter etc."""
    return container.redis_client()


async def get_rate_limiter(
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """Provide the shared token rate limiter."""
    return container.rate_limiter(redis=redis_client)


def get_seo_service(
    llm: ILLMProvider = Depends(get_llm_provider),
):
    """Return the shared SEO service."""
    return container.seo_service()


def get_analysis_service(
    llm: ILLMProvider = Depends(get_llm_provider),
    seo=Depends(get_seo_service),
):
    """Return the shared analysis service."""
    return container.analysis_service()


def get_rag_service(
    embedding: IEmbeddingProvider = Depends(get_embedding_provider),
    vector_store: IVectorStore = Depends(get_vector_store),
    llm: ILLMProvider = Depends(get_llm_provider),
):
    """Return the shared RAG service."""
    return container.rag_service()


def get_indexing_service(
    embedding: IEmbeddingProvider = Depends(get_embedding_provider),
    vector_store: IVectorStore = Depends(get_vector_store),
):
    """Return the shared indexing service."""
    return container.indexing_service()


def get_memory_service():
    """Return the shared conversation memory service."""
    return container.memory_service()


def get_chat_service(
    llm: ILLMProvider = Depends(get_llm_provider),
    rag=Depends(get_rag_service),
    web_search: IWebSearchProvider = Depends(get_web_search_provider),
    analysis=Depends(get_analysis_service),
):
    """Return the shared chat service."""
    return container.chat_service()


async def get_cache_adapter() -> ICache:
    """Async wrapper for code paths that expect an awaitable cache dependency."""
    cache_instance = container.cache()
    connect = getattr(cache_instance, "connect", None)
    if callable(connect):
        await connect()
    return cache_instance


async def get_message_broker_adapter() -> IMessageBroker:
    """Async wrapper for code paths that expect an awaitable broker dependency."""
    broker = container.message_broker()
    is_connected = getattr(broker, "is_connected", None)
    if callable(is_connected) and not is_connected():
        await broker.connect()
    return broker


async def get_autonomous_agent() -> Any | None:
    """Return a shared-config autonomous agent for legacy consumers."""
    if not settings.agent_autonomous_enabled:
        return None

    from app.agents.tools.web_search_tool import WebSearchTool as AgentWebSearchTool
    from app.agents.tools.rag_tool import RagRetrieveTool
    from app.agents.autonomous_agent import ExecutionMode
    from app.agents.agent_factory import create_autonomous_agent

    web_search_tool = AgentWebSearchTool(web_search_provider=container.web_search_provider())
    rag_tool = RagRetrieveTool(rag_service=container.rag_service())
    mode = ExecutionMode.HYBRID if settings.agent_hybrid_mode else ExecutionMode.AUTONOMOUS

    return await create_autonomous_agent(
        llm_provider=container.llm_provider(),
        vector_store=container.vector_store(),
        embedding_provider=container.embedding_provider(),
        memory_service=container.memory_service(),
        web_search_tool=web_search_tool,
        rag_tool=rag_tool,
        mode=mode,
    )


def get_chat_agent():
    """Return the shared ChatAgent instance."""
    return container.chat_agent()


def get_analysis_agent(
    analysis_service=Depends(get_analysis_service),
    indexing_service=Depends(get_indexing_service),
):
    """Return the AnalysisAgent with shared dependencies."""
    return container.analysis_agent()


def get_message_processor(
    cache: ICache = Depends(get_cache),
    broker: IMessageBroker = Depends(get_message_broker),
    analysis=Depends(get_analysis_service),
    indexing=Depends(get_indexing_service),
    chat=Depends(get_chat_service),
):
    """Return the legacy message processor with shared dependencies."""
    return container.message_processor_service()


def get_langgraph_processor(
    cache: ICache = Depends(get_cache),
    broker: IMessageBroker = Depends(get_message_broker),
    analysis=Depends(get_analysis_service),
    indexing=Depends(get_indexing_service),
    chat=Depends(get_chat_service),
):
    """Return the LangGraph message processor with shared dependencies."""
    return container.langgraph_processor()


async def get_message_processor_service():
    """Return MessageProcessorService using the shared runtime services."""
    cache_adapter = await get_cache_adapter()
    broker = await get_message_broker_adapter()
    autonomous_agent = await get_autonomous_agent()
    from app.services.message_processor_service import MessageProcessorService

    return MessageProcessorService(
        cache=cache_adapter,
        message_broker=broker,
        analysis_service=container.analysis_service(),
        indexing_service=container.indexing_service(),
        chat_service=container.chat_service(),
        autonomous_agent=autonomous_agent,
    )


async def shutdown_services() -> None:
    """Shutdown shared runtime services for legacy callers."""
    from app.container import shutdown_container
    await shutdown_container()


def health_snapshot() -> dict[str, Any]:
    """Return lightweight runtime health for readiness endpoints.

    This is the canonical function for health checks - use this instead of
    DependencyContainer.health_snapshot() in new code.
    """
    from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter

    broker_connected = False
    cache_connected = False
    llm_initialized = False
    embedding_initialized = False
    vector_store_ready = False
    broker_queue_depth: int | None = None
    broker_queue_consumers: int | None = None
    broker_backlog_over_threshold = False
    broker_queue_warn_threshold: int | None = None
    broker_queue_observed_at: str | None = None
    security_redis_wired = False

    try:
        vs = container.vector_store()
        vector_store_ready = vs is not None
    except Exception:
        pass

    try:
        broker = container.message_broker()
        broker_connected = broker.is_connected() if hasattr(broker, "is_connected") else True
        if hasattr(broker, "get_queue_stats"):
            queue_stats = broker.get_queue_stats()
            broker_queue_depth = queue_stats.get("message_count")
            broker_queue_consumers = queue_stats.get("consumers")
            broker_queue_warn_threshold = getattr(broker, "queue_warn_threshold", 1000)
            broker_backlog_over_threshold = broker_queue_depth is not None and broker_queue_warn_threshold is not None and broker_queue_depth > broker_queue_warn_threshold
            broker_queue_observed_at = queue_stats.get("observed_at")
    except Exception:
        pass

    try:
        cache = container.cache()
        cache_connected = cache.is_connected() if hasattr(cache, "is_connected") else True
    except Exception:
        pass

    try:
        llm = container.llm_provider()
        llm_initialized = llm.is_initialized() if hasattr(llm, "is_initialized") else True
    except Exception:
        pass

    try:
        emb = container.embedding_provider()
        embedding_initialized = emb.is_initialized() if hasattr(emb, "is_initialized") else True
    except Exception:
        pass

    try:
        from app.security.kill_switch import kill_switch
        from app.security.incident_tracker import incident_tracker
        security_redis_wired = kill_switch.redis is not None and incident_tracker.redis is not None
    except Exception:
        pass

    try:
        supervisor = container.supervisor()
        langgraph_enabled = container.settings().agent_use_langgraph
        supervisor_initialized = supervisor is not None if langgraph_enabled else True
    except Exception:
        langgraph_enabled = False
        supervisor_initialized = False

    return {
        "broker_connected": broker_connected,
        "cache_connected": cache_connected,
        "llm_initialized": llm_initialized,
        "embedding_initialized": embedding_initialized,
        "vector_store_ready": vector_store_ready,
        "security_redis_wired": security_redis_wired,
        "broker_queue_depth": broker_queue_depth,
        "broker_queue_consumers": broker_queue_consumers,
        "broker_backlog_over_threshold": broker_backlog_over_threshold,
        "broker_queue_warn_threshold": broker_queue_warn_threshold,
        "broker_queue_observed_at": broker_queue_observed_at,
        "langgraph_enabled": langgraph_enabled,
        "supervisor_initialized": supervisor_initialized,
    }


# ---------------------------------------------------------------------------
# DependencyContainer — backward-compatible facade over the container
# ---------------------------------------------------------------------------

class DependencyContainer:
    """Thin facade preserving the old DependencyContainer API.

    Delegates all lookups to the central DI container. Existing code
    that calls DependencyContainer.get_*() continues to work unchanged.
    """

    @classmethod
    def get_llm(cls) -> ILLMProvider:
        return container.llm_provider()

    @classmethod
    def get_redis_adapter(cls):
        return container.redis_adapter()

    @classmethod
    def get_cache(cls) -> ICache:
        return container.cache()

    @classmethod
    def get_vector_store(cls) -> IVectorStore:
        return container.vector_store()

    @classmethod
    def get_embedding(cls) -> IEmbeddingProvider:
        return container.embedding_provider()

    @classmethod
    def get_broker(cls) -> IMessageBroker:
        return container.message_broker()

    @classmethod
    def get_web_search(cls) -> IWebSearchProvider:
        return container.web_search_provider()

    @classmethod
    def get_seo_service(cls):
        return container.seo_service()

    @classmethod
    def get_analysis_service(cls):
        return container.analysis_service()

    @classmethod
    def get_rag_service(cls):
        return container.rag_service()

    @classmethod
    def get_indexing_service(cls):
        return container.indexing_service()

    @classmethod
    def get_memory_service(cls):
        return container.memory_service()

    @classmethod
    def get_chat_service(cls):
        return container.chat_service()

    @classmethod
    def get_gdpr_handler(cls):
        return container.gdpr_handler()

    @classmethod
    def get_supervisor(cls):
        return container.supervisor()

    @classmethod
    async def initialize_all(cls) -> None:
        """Initialize shared infrastructure and service graph via container."""
        from app.container import initialize_container
        await initialize_container()

    @classmethod
    async def shutdown_all(cls) -> None:
        """Shutdown shared infrastructure components."""
        from app.container import shutdown_container
        await shutdown_container()

    @classmethod
    def health_snapshot(cls) -> dict[str, Any]:
        """Return lightweight runtime health for readiness endpoints."""
        from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter

        broker_connected = False
        cache_connected = False
        llm_initialized = False
        embedding_initialized = False
        vector_store_ready = False
        broker_queue_depth: int | None = None
        broker_queue_consumers: int | None = None
        broker_backlog_over_threshold = False
        broker_queue_warn_threshold: int | None = None
        broker_queue_observed_at: str | None = None
        security_redis_wired = False

        try:
            vs = container.vector_store()
            vector_store_ready = vs is not None
        except Exception:
            pass

        try:
            broker = container.message_broker()
            if broker:
                broker_connected = bool(broker.is_connected())
                if isinstance(broker, RabbitMQAdapter):
                    queue_stats = broker.get_cached_queue_stats()
                    broker_queue_depth = queue_stats.get("message_count")
                    broker_queue_consumers = queue_stats.get("consumer_count")
                    broker_backlog_over_threshold = bool(queue_stats.get("backlog_over_threshold", False))
                    broker_queue_warn_threshold = queue_stats.get("warn_threshold")
                    broker_queue_observed_at = queue_stats.get("observed_at")
        except Exception:
            pass

        try:
            cache_obj = container.cache()
            if cache_obj:
                attr = getattr(cache_obj, "is_connected", False)
                cache_connected = bool(attr() if callable(attr) else attr)
        except Exception:
            pass

        try:
            llm = container.llm_provider()
            if llm:
                llm_initialized = bool(llm.is_initialized())
        except Exception:
            pass

        try:
            emb = container.embedding_provider()
            if emb:
                attr = getattr(emb, "is_initialized", False)
                embedding_initialized = bool(attr() if callable(attr) else attr)
        except Exception:
            pass

        try:
            ks = container.kill_switch()
            it = container.incident_tracker()
            security_redis_wired = ks.redis is not None and it.redis is not None
        except Exception:
            pass

        return {
            "broker_connected": broker_connected,
            "cache_connected": cache_connected,
            "llm_initialized": llm_initialized,
            "embedding_initialized": embedding_initialized,
            "vector_store_ready": vector_store_ready,
            "broker_queue_depth": broker_queue_depth,
            "broker_queue_consumers": broker_queue_consumers,
            "broker_backlog_over_threshold": broker_backlog_over_threshold,
            "broker_queue_warn_threshold": broker_queue_warn_threshold,
            "broker_queue_observed_at": broker_queue_observed_at,
            "langgraph_enabled": settings.agent_use_langgraph,
            "supervisor_initialized": container.supervisor() is not None,
            "seo_service_initialized": True,
            "analysis_service_initialized": True,
            "rag_service_initialized": True,
            "indexing_service_initialized": True,
            "memory_service_initialized": True,
            "chat_service_initialized": True,
            "security_redis_wired": security_redis_wired,
        }
