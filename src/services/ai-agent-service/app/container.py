"""Dependency Injection Container using dependency-injector.

Central wiring point for all application dependencies.
Domain and core layers remain framework-free — only this module
and the API layer import dependency_injector.

Provider strategy:
  - Singleton: all shared instances (constructed lazily, no async needed)
  - Factory:   per-request / short-lived instances

Lifecycle (connect/disconnect/warmup/shutdown) is managed explicitly
by the lifespan in routes.py, NOT by Resource providers.  This avoids
the async/sync impedance mismatch that Resource providers introduce.
"""

from __future__ import annotations

import logging

from dependency_injector import containers, providers

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

class ApplicationContainer(containers.DeclarativeContainer):
    """Root DI container for AI Agent Service.

    All providers are Singleton or Factory — no async Resource providers.
    Async lifecycle (connect, warmup, shutdown) is handled by the app
    lifespan in routes.py which calls ``initialize()`` and ``shutdown()``.
    """

    # No wiring needed: dependencies.py and health.py call container.xxx()
    # directly without @inject decorators, so auto-wiring would cause a
    # circular import (container not yet instantiated when wiring fires).

    # ── Configuration ──────────────────────────────────────────────────
    config = providers.Configuration()

    settings = providers.Singleton(get_settings)

    # ── Infrastructure: adapters ───────────────────────────────────────

    # Raw async Redis client — created sync, connect handled in lifespan
    redis_client = providers.Singleton(
        lambda url: __import__("redis.asyncio", fromlist=["Redis"]).from_url(
            url, encoding="utf-8", decode_responses=True
        ),
        url=config.redis_url,
    )

    # RedisAdapter (infrastructure adapter for caching layer)
    redis_adapter = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.cache.redis_adapter", fromlist=["RedisAdapter"]
        ).RedisAdapter()
    )

    # Vector store (ChromaDB) — stateless after init, singleton
    vector_store = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.vector_store.chroma_adapter", fromlist=["ChromaAdapter"]
        ).ChromaAdapter()
    )

    # Base Ollama LLM adapter — stateless, singleton
    _base_llm_provider = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.llm.ollama_adapter", fromlist=["OllamaAdapter"]
        ).OllamaAdapter()
    )

    # Base Ollama embedding adapter — stateless, singleton
    _base_embedding_provider = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.embedding.ollama_embedding_adapter",
            fromlist=["OllamaEmbeddingAdapter"],
        ).OllamaEmbeddingAdapter()
    )

    # Web search provider — stateless, singleton
    web_search_provider = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.search.duckduckgo_adapter",
            fromlist=["DuckDuckGoAdapter"],
        ).DuckDuckGoAdapter()
    )

    # RabbitMQ broker — constructed sync, connect/disconnect in lifespan
    message_broker = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.messaging.rabbitmq_adapter", fromlist=["RabbitMQAdapter"]
        ).RabbitMQAdapter(
            stats_publisher=ApplicationContainer.queue_stats_publisher(),
        )
    )

    # ── Priority Queue Infrastructure ───────────────────────────────────
    priority_scheduler = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.messaging.priority_scheduler",
            fromlist=["PriorityScheduler"],
        ).PriorityScheduler(
            total_slots=get_settings().scheduler_total_slots,
            chat_slots=get_settings().scheduler_chat_slots,
            low_priority_slots=get_settings().scheduler_low_priority_slots,
        )
    )

    queue_stats_publisher = providers.Singleton(
        lambda: __import__(
            "app.infrastructure.messaging.queue_stats_publisher",
            fromlist=["QueueStatsPublisher"],
        ).QueueStatsPublisher(
            cache=ApplicationContainer.redis_adapter(),
            ttl_seconds=get_settings().queue_stats_redis_ttl_seconds,
        )
    )

    queue_aware_circuit_breaker = providers.Singleton(
        lambda: __import__(
            "app.core.circuit_breaker",
            fromlist=["QueueAwareCircuitBreaker"],
        ).QueueAwareCircuitBreaker(
            stats_publisher=ApplicationContainer.queue_stats_publisher(),
            failure_threshold=get_settings().circuit_breaker_failure_threshold,
            recovery_timeout=get_settings().circuit_breaker_recovery_timeout,
            chat_fallback_message=get_settings().chat_fallback_message,
        )
    )

    # ── Security ───────────────────────────────────────────────────────

    # Reuse existing module-level singletons to avoid double instantiation.
    kill_switch = providers.Singleton(
        lambda: __import__(
            "app.security.kill_switch", fromlist=["kill_switch"]
        ).kill_switch
    )

    incident_tracker = providers.Singleton(
        lambda: __import__(
            "app.security.incident_tracker", fromlist=["incident_tracker"]
        ).incident_tracker
    )

    content_cleaner = providers.Singleton(
        lambda: __import__(
            "app.services.content_cleaner", fromlist=["ContentCleanerService"]
        ).ContentCleanerService()
    )

    secure_response_handler = providers.Singleton(
        lambda: __import__(
            "app.security.output_handler", fromlist=["SecureResponseHandler"]
        ).SecureResponseHandler()
    )

    backend_auth_client = providers.Singleton(
        lambda: __import__(
            "app.security.backend_authorization_client",
            fromlist=["BackendAuthorizationClient"],
        ).BackendAuthorizationClient()
    )

    # ── Infrastructure: decorated / resilient wrappers ─────────────────

    # Resilient LLM provider with circuit breaker + injected response handler
    llm_provider = providers.Singleton(
        lambda base, handler: __import__(
            "app.services.resilient_llm_provider", fromlist=["ResilientLLMProvider"]
        ).ResilientLLMProvider(base, response_handler=handler),
        base=_base_llm_provider,
        handler=secure_response_handler,
    )

    # Optimized embedding provider — constructed sync, initialize/shutdown in lifespan
    embedding_provider = providers.Singleton(
        lambda base, redis_a: __import__(
            "app.services.optimized_embedding_provider", fromlist=["OptimizedEmbeddingProvider"]
        ).OptimizedEmbeddingProvider(base, redis_a),
        base=_base_embedding_provider,
        redis_a=redis_adapter,
    )

    # Multi-level cache — constructed sync, connect/disconnect in lifespan
    cache = providers.Singleton(
        lambda redis_a, vs: __import__(
            "app.core.multi_level_cache", fromlist=["MultiLevelCache"]
        ).MultiLevelCache(redis_a, vector_store=vs),
        redis_a=redis_adapter,
        vs=vector_store,
    )

    # Rate limiter — factory (per-request with redis client)
    rate_limiter = providers.Factory(
        lambda redis: __import__(
            "app.security.token_rate_limiter", fromlist=["UnifiedRateLimiter"]
        ).UnifiedRateLimiter(redis),
        redis=redis_client,
    )

    # GDPR handler
    gdpr_handler = providers.Singleton(
        lambda c, vs: __import__(
            "app.security.gdpr_handler", fromlist=["GDPRHandler"]
        ).GDPRHandler(cache=c, vector_store=vs),
        c=cache,
        vs=vector_store,
    )

    # ── Services ───────────────────────────────────────────────────────

    seo_service = providers.Singleton(
        lambda llm, cleaner: __import__(
            "app.services.seo_service", fromlist=["SeoService"]
        ).SeoService(llm_provider=llm, content_cleaner=cleaner),
        llm=llm_provider,
        cleaner=content_cleaner,
    )

    analysis_service = providers.Singleton(
        lambda llm, seo, cleaner: __import__(
            "app.services.analysis_service", fromlist=["AnalysisService"]
        ).AnalysisService(llm_provider=llm, seo_service=seo, content_cleaner=cleaner),
        llm=llm_provider,
        seo=seo_service,
        cleaner=content_cleaner,
    )

    rag_service = providers.Singleton(
        lambda emb, vs, llm, auth: __import__(
            "app.services.rag_service", fromlist=["RagService"]
        ).RagService(embedding_provider=emb, vector_store=vs, llm_provider=llm, backend_auth_client=auth),
        emb=embedding_provider,
        vs=vector_store,
        llm=llm_provider,
        auth=backend_auth_client,
    )

    indexing_service = providers.Singleton(
        lambda emb, vs, cleaner: __import__(
            "app.services.indexing_service", fromlist=["IndexingService"]
        ).IndexingService(embedding_provider=emb, vector_store=vs, content_cleaner=cleaner),
        emb=embedding_provider,
        vs=vector_store,
        cleaner=content_cleaner,
    )

    anomaly_detector = providers.Singleton(
        lambda: __import__(
            "app.monitoring.anomaly_detector", fromlist=["AnomalyDetector"]
        ).AnomalyDetector()
    )

    chat_service = providers.Singleton(
        lambda llm, rag, ws, analysis, anomaly: __import__(
            "app.services.chat_service", fromlist=["ChatService"]
        ).ChatService(
            llm_provider=llm,
            rag_service=rag,
            web_search_provider=ws,
            analysis_service=analysis,
            anomaly_detector=anomaly,
        ),
        llm=llm_provider,
        rag=rag_service,
        anomaly=anomaly_detector,
        ws=web_search_provider,
        analysis=analysis_service,
    )

    # Conversation memory — constructed sync, shutdown in lifespan
    memory_service = providers.Singleton(
        lambda url, vs, emb: __import__(
            "app.memory.conversation_memory", fromlist=["ConversationMemoryService"]
        ).ConversationMemoryService(
            redis_url=url,
            vector_store=vs,
            embedding_provider=emb,
        ),
        url=config.redis_url,
        vs=vector_store,
        emb=embedding_provider,
    )

    # ── Agent Tools ────────────────────────────────────────────────────

    web_search_tool = providers.Singleton(
        lambda ws: __import__(
            "app.agents.tools.web_search_tool", fromlist=["WebSearchTool"]
        ).WebSearchTool(web_search_provider=ws),
        ws=web_search_provider,
    )

    rag_tool = providers.Singleton(
        lambda rag: __import__(
            "app.agents.tools.rag_tool", fromlist=["RagRetrieveTool"]
        ).RagRetrieveTool(rag_service=rag),
        rag=rag_service,
    )

    # ── Agents ─────────────────────────────────────────────────────────

    analysis_agent = providers.Singleton(
        lambda a, i: __import__(
            "app.agents.analysis_agent", fromlist=["AnalysisAgent"]
        ).AnalysisAgent(analysis_service=a, indexing_service=i),
        a=analysis_service,
        i=indexing_service,
    )

    content_agent = providers.Singleton(
        lambda a: __import__(
            "app.agents.content_agent", fromlist=["ContentAgent"]
        ).ContentAgent(analysis_service=a),
        a=analysis_service,
    )

    seo_agent = providers.Singleton(
        lambda s: __import__(
            "app.agents.seo_agent", fromlist=["SeoAgent"]
        ).SeoAgent(seo_service=s),
        s=seo_service,
    )

    react_chat_agent = providers.Singleton(
        lambda llm, ws_tool, rag_t: __import__(
            "app.agents.react_chat_agent", fromlist=["ReActChatAgent"]
        ).ReActChatAgent(
            llm_provider=llm,
            web_search_tool=ws_tool,
            rag_tool=rag_t,
        ),
        llm=llm_provider,
        ws_tool=web_search_tool,
        rag_t=rag_tool,
    )

    chat_agent = providers.Singleton(
        lambda cs, analysis, mem, react: __import__(
            "app.agents.chat_agent", fromlist=["ChatAgent"]
        ).ChatAgent(
            chat_service=cs,
            analysis_service=analysis,
            memory_service=mem,
            react_agent=react,
            autonomous_agent=None,
        ),
        cs=chat_service,
        analysis=analysis_service,
        mem=memory_service,
        react=react_chat_agent,
    )

    verification_agent = providers.Singleton(
        lambda llm: __import__(
            "app.agents.verification_agent", fromlist=["VerificationAgent"]
        ).VerificationAgent(llm_provider=llm),
        llm=llm_provider,
    )

    supervisor = providers.Singleton(
        lambda agents, llm, settings_obj, verifier: __import__(
            "app.agents.supervisor", fromlist=["SupervisorAgent"]
        ).SupervisorAgent(
            agents=agents,
            verification_agent=verifier,
            llm_provider=llm if settings_obj.agent_dynamic_routing else None,
        ),
        agents=providers.Dict(
            chat=chat_agent,
            analyzer=analysis_agent,
            content=content_agent,
            seo=seo_agent,
        ),
        llm=llm_provider,
        settings_obj=settings,
        verifier=verification_agent,
    )

    # ── Message Processors ─────────────────────────────────────────────

    message_processor_service = providers.Factory(
        lambda c, mb, a, i, cs, auto, auth: __import__(
            "app.services.message_processor_service",
            fromlist=["MessageProcessorService"],
        ).MessageProcessorService(
            cache=c,
            message_broker=mb,
            analysis_service=a,
            indexing_service=i,
            chat_service=cs,
            autonomous_agent=auto,
            backend_auth_client=auth,
        ),
        c=cache,
        mb=message_broker,
        a=analysis_service,
        i=indexing_service,
        cs=chat_service,
        auto=providers.Object(None),
        auth=backend_auth_client,
    )

    admin_message_processor = providers.Factory(
        lambda mb: __import__(
            "app.messaging.admin_processor", fromlist=["AdminMessageProcessor"]
        ).AdminMessageProcessor(broker=mb),
        mb=message_broker,
    )

    langgraph_processor = providers.Factory(
        lambda c, mb, a, i, cs, sup, auth: __import__(
            "app.messaging.consumer",
            fromlist=["RabbitMQConsumer"],
        ).RabbitMQConsumer(
            cache=c,
            message_broker=mb,
            analysis_service=a,
            indexing_service=i,
            chat_service=cs,
            supervisor=sup,
            backend_auth_client=auth,
        ),
        c=cache,
        mb=message_broker,
        a=analysis_service,
        i=indexing_service,
        cs=chat_service,
        sup=supervisor,
        auth=backend_auth_client,
    )

    # ── Monitoring / Runtime ───────────────────────────────────────────

    # Reuse the existing module-level RuntimeState instance
    runtime_state = providers.Singleton(
        lambda: __import__(
            "app.api.runtime_state", fromlist=["runtime_state"]
        ).runtime_state
    )


# ---------------------------------------------------------------------------
# Module-level container instance
# ---------------------------------------------------------------------------

container = ApplicationContainer()


def configure_container(settings_instance: Settings | None = None) -> ApplicationContainer:
    """Configure the container with application settings.

    Call this once during application bootstrap (before FastAPI starts).
    """
    s = settings_instance or get_settings()
    container.config.from_dict({
        "redis_url": s.redis_url,
        "rabbitmq_url": s.rabbitmq_url,
        "debug": s.debug,
        "ollama_base_url": s.ollama_base_url,
        "ollama_model": s.ollama_model,
        "chroma_persist_dir": s.chroma_persist_dir,
        "agent_use_langgraph": s.agent_use_langgraph,
        "agent_dynamic_routing": s.agent_dynamic_routing,
        "agent_autonomous_enabled": s.agent_autonomous_enabled,
        "agent_hybrid_mode": s.agent_hybrid_mode,
        "agent_react_enabled": getattr(s, "agent_react_enabled", True),
    })
    return container


async def initialize_container() -> None:
    """Initialize all async lifecycle-managed components.

    Call this once during app startup (lifespan). This replaces
    the old DependencyContainer.initialize_all() method.
    """
    # 1. Cache connect
    cache = container.cache()
    await cache.connect()
    logger.info("[Container] Cache connected")

    # 2. Embedding provider init
    embedding = container.embedding_provider()
    await embedding.initialize()
    logger.info("[Container] Embedding provider initialized")

    # 3. Vector store init (synchronous)
    vs = container.vector_store()
    vs.initialize()
    logger.info("[Container] Vector store initialized")

    # 4. Validate ChromaDB dimensions
    s = container.settings()
    if hasattr(embedding, "dimensions") and hasattr(vs, "validate_dimensions"):
        if s.chroma_force_reset:
            logger.warning(
                "[Container] CHROMA_FORCE_RESET=true - force resetting Chroma for %s-dim",
                embedding.dimensions,
            )
            vs.force_reset_all_collections(embedding.dimensions)
        else:
            vs.validate_dimensions(embedding.dimensions)

    # 5. RabbitMQ connect
    broker = container.message_broker()
    await broker.connect()
    logger.info("[Container] RabbitMQ broker connected")

    # 6. Wire security components to Redis
    try:
        redis_client = container.redis_client()
        ks = container.kill_switch()
        it = container.incident_tracker()
        ks.redis = redis_client
        it.redis = redis_client
        logger.info("[Container] Security components wired to Redis")
    except Exception as exc:
        logger.warning("[Container] Security Redis wiring failed: %s", exc)


async def shutdown_container() -> None:
    """Shutdown all async lifecycle-managed components.

    Call this once during app shutdown (lifespan).
    """
    # Memory service
    try:
        mem = container.memory_service()
        await mem.shutdown()
    except Exception:
        logger.debug("[Container] Memory service shutdown failed", exc_info=True)

    # Broker
    try:
        broker = container.message_broker()
        await broker.disconnect()
    except Exception:
        logger.debug("[Container] Broker disconnect failed", exc_info=True)

    # Embedding provider
    try:
        emb = container.embedding_provider()
        await emb.shutdown()
    except Exception:
        logger.debug("[Container] Embedding shutdown failed", exc_info=True)

    # Cache
    try:
        cache = container.cache()
        await cache.disconnect()
    except Exception:
        logger.debug("[Container] Cache disconnect failed", exc_info=True)

    # Redis client
    try:
        redis = container.redis_client()
        await redis.aclose()
    except Exception:
        logger.debug("[Container] Redis client close failed", exc_info=True)

    logger.info("[Container] All resources shut down")
