"""
FastAPI Application - BlogApp AI Agent Service

Application factory and lifecycle management with Hexagonal Architecture.
Uses dependency-injector for centralized DI.
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logging_utils import (
    sanitize_url,
    set_request_id,
    clear_request_id,
    setup_logging,
    trace_span,
)
from app.monitoring.metrics import record_http_request
from app.container import container, configure_container, initialize_container, shutdown_container
from app.services.idle_shutdown_service import (
    initialize_idle_shutdown_service,
    record_idle_activity,
)

logger = logging.getLogger(__name__)
setup_logging(level="DEBUG" if settings.debug else "INFO", service_name="ai-agent-service")

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


class MessageProcessorContract(Protocol):
    """Common runtime contract for message processors used by broker consumer."""

    async def process_message(self, body: bytes) -> tuple[bool, str]:
        ...


# Background task reference
_consumer_task: asyncio.Task | None = None
_idle_shutdown_task: asyncio.Task | None = None
_message_processor: MessageProcessorContract | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown of all infrastructure components
    following Hexagonal Architecture principles.
    All dependencies are resolved from the DI container.
    """
    global _consumer_task, _message_processor

    # === STARTUP ===
    rt = container.runtime_state()
    rt.mark_startup()
    logger.info("=" * 60)
    logger.info("BlogApp AI Agent Service Starting...")
    logger.info("=" * 60)
    logger.info("Architecture: Hexagonal (Ports & Adapters) + DI Container")
    logger.info(f"Environment: {'Development' if settings.debug else 'Production'}")
    logger.info(f"LLM Model: {settings.ollama_model}")
    logger.info(f"RabbitMQ: {settings.rabbitmq_host}:{settings.rabbitmq_port}")
    logger.info(f"Redis: {sanitize_url(settings.redis_url)}")
    logger.info("=" * 60)

    # Initialize all infrastructure (cache, embedding, vector store, broker, security wiring)
    logger.info("Initializing infrastructure via DI container...")
    await initialize_container()
    logger.info("DI container initialized")

    # Warm up LLM model
    logger.info("Warming up LLM model...")
    try:
        llm = container.llm_provider()
        await llm.warmup()
        logger.info("LLM model warmed up successfully!")
    except Exception as e:
        logger.warning(f"Model warmup failed (will load on first request): {e}")

    # Warm up embedding model
    try:
        embedding = container.embedding_provider()
        logger.info("Warming up embedding model...")
        await embedding.warmup()
        logger.info("Embedding model warmed up successfully!")
    except Exception as e:
        logger.warning(f"Embedding warmup failed (will load on first request): {e}")

    # Resolve services from container (all synchronous after init)
    indexing_service = container.indexing_service()
    rag_service = container.rag_service()
    chat_service = container.chat_service()
    analysis_service = container.analysis_service()
    broker = container.message_broker()
    cache = container.cache()
    memory_service = container.memory_service()
    vector_store = container.vector_store()

    # Rebuild BM25 index from persisted ChromaDB data (offloaded to thread pool - CPU-bound)
    try:
        logger.info("Rebuilding BM25 index from vector store...")
        loop = asyncio.get_event_loop()
        rebuilt = await loop.run_in_executor(
            None, indexing_service.rebuild_bm25_from_vector_store
        )
        logger.info(f"BM25 index rebuilt for {rebuilt} posts")
    except Exception as e:
        logger.warning(f"BM25 rebuild failed (sparse search degraded): {e}")

    # Eager-initialize RAG service to pre-load Cross-Encoder model
    try:
        logger.info("Initializing RAG service (Cross-Encoder warmup)...")
        await rag_service.initialize()
        logger.info("RAG service initialized (Cross-Encoder loaded)")
    except Exception as e:
        logger.warning(f"RAG service initialization failed (will load on first request): {e}")

    if settings.agent_use_langgraph:
        supervisor = container.supervisor()
        if supervisor is None:
            logger.warning(
                "AGENT_USE_LANGGRAPH=true but supervisor is not initialized; "
                "LangGraph processor will run in legacy fallback mode"
            )
        else:
            logger.info("LangGraph supervisor initialized; enabling supervisor dispatch path")

        _message_processor = container.langgraph_processor()
        logger.info("Using RabbitMQConsumer for message processing")
    else:
        from app.agents.agent_factory import create_chat_agent

        llm = container.llm_provider()
        web_search_tool = container.web_search_tool()
        rag_tool = container.rag_tool()

        try:
            chat_agent = await create_chat_agent(
                llm_provider=llm,
                chat_service=chat_service,
                analysis_service=analysis_service,
                memory_service=memory_service,
                web_search_tool=web_search_tool,
                rag_tool=rag_tool,
                vector_store=vector_store,
                embedding_provider=container.embedding_provider(),
                enable_autonomous=settings.agent_autonomous_enabled,
            )
            logger.info("ChatAgent with ReAct + autonomous agent created successfully")
        except Exception as e:
            chat_agent = None
            logger.warning(f"Failed to create ChatAgent (will use basic chat): {e}")

        from app.services.message_processor_service import MessageProcessorService

        _message_processor = MessageProcessorService(
            cache=cache,
            message_broker=broker,
            analysis_service=analysis_service,
            indexing_service=indexing_service,
            chat_service=chat_service,
            autonomous_agent=chat_agent,
        )
        logger.info("Using MessageProcessorService for RabbitMQ consumer")

    async def _consumer_handler(body: bytes) -> tuple[bool, str]:
        from app.security.kill_switch import KillSwitchState

        ks = container.kill_switch()
        try:
            ks_state = await ks.get_state()
            if ks_state == KillSwitchState.EMERGENCY_SHUTDOWN:
                logger.warning("[Consumer] Message rejected - kill switch EMERGENCY_SHUTDOWN active")
                return False, "kill_switch:emergency_shutdown"
        except Exception:
            pass

        rt.mark_consumer_message_started()
        try:
            if _message_processor is None:
                raise RuntimeError("Message processor is not initialized")
            with trace_span("mq.consume.message"):
                success, reason = await _message_processor.process_message(body)
            rt.mark_consumer_message_finished(success, reason)
            await record_idle_activity()
            return success, reason
        except Exception as exc:
            rt.mark_consumer_error(exc)
            raise

    def _bind_consumer_callbacks(task: asyncio.Task) -> None:
        def _on_consumer_task_done(done_task: asyncio.Task) -> None:
            if done_task.cancelled():
                rt.mark_consumer_stopped("cancelled")
                return
            exc = done_task.exception()
            if exc:
                rt.mark_consumer_stopped(str(exc))
                logger.error(f"Message consumer task exited with error: {exc}")
            else:
                rt.mark_consumer_stopped("completed")

        task.add_done_callback(_on_consumer_task_done)

    async def _start_consumer() -> None:
        global _consumer_task
        if _consumer_task and not _consumer_task.done():
            return
        logger.info("Starting message consumer...")
        from app.infrastructure.messaging.rabbitmq_adapter import (
            QUEUE_CHAT, QUEUE_AUTHORING, QUEUE_BACKGROUND,
        )
        _consumer_task = asyncio.create_task(broker.start_consuming_multi({
            QUEUE_CHAT: _consumer_handler,
            QUEUE_AUTHORING: _consumer_handler,
            QUEUE_BACKGROUND: _consumer_handler,
        }))
        rt.mark_consumer_started()
        _bind_consumer_callbacks(_consumer_task)
        logger.info("RabbitMQ consumer started successfully")

    async def _stop_consumer_for_standby() -> None:
        global _consumer_task
        if not _consumer_task:
            return
        await broker.stop_consuming()
        try:
            await asyncio.wait_for(_consumer_task, timeout=10)
        except asyncio.TimeoutError:
            _consumer_task.cancel()
            try:
                await _consumer_task
            except asyncio.CancelledError:
                pass
        rt.mark_consumer_stopped("standby")
        _consumer_task = None

    async def _resume_consumer_from_standby() -> None:
        await _start_consumer()

    try:
        await _start_consumer()
    except Exception as e:
        logger.warning(f"Failed to start RabbitMQ consumer: {e}")
        rt.mark_consumer_stopped(str(e))
        logger.info("Service will continue without message consumption")

    idle_shutdown_service = initialize_idle_shutdown_service(
        idle_timeout_seconds=settings.idle_timeout_seconds,
        enabled=settings.idle_shutdown_enabled,
        enter_standby=_stop_consumer_for_standby,
        exit_standby=_resume_consumer_from_standby,
        queue_stats_provider=broker.refresh_queue_stats,
    )
    if idle_shutdown_service.enabled:
        _idle_shutdown_task = asyncio.create_task(idle_shutdown_service.run())
        logger.info(
            f"Idle standby controller started (timeout: {settings.idle_timeout_seconds}s)"
        )
    else:
        logger.info("Idle standby controller disabled")

    logger.info("AI Agent Service started successfully!")

    yield  # Application runs here

    # === SHUTDOWN ===
    logger.info("Shutting down AI Agent Service...")

    if _consumer_task:
        await broker.stop_consuming()
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    if _idle_shutdown_task:
        _idle_shutdown_task.cancel()
        try:
            await _idle_shutdown_task
        except asyncio.CancelledError:
            pass

    # Shutdown all lifecycle-managed components
    await shutdown_container()
    rt.mark_shutdown()
    logger.info("AI Agent Service stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Configure container before app starts
    configure_container()

    app = FastAPI(
        title="BlogApp AI Agent Service",
        description="AI-powered blog analysis using Hexagonal Architecture",
        version="4.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        """Propagate correlation ID across logs and responses."""
        incoming_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        correlation_id = (incoming_id.strip()[:128] if incoming_id else f"req_{uuid.uuid4().hex[:16]}")
        set_request_id(correlation_id)
        request.state.correlation_id = correlation_id

        try:
            with trace_span(
                "http.request",
                method=request.method,
                path=request.url.path,
            ):
                response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            clear_request_id()

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        """Record HTTP request metrics."""
        started_at = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            record_http_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_seconds=time.perf_counter() - started_at,
            )

    @app.middleware("http")
    async def standby_activity_middleware(request: Request, call_next):
        """Mark inbound HTTP traffic as wake activity for standby mode."""
        if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
            await record_idle_activity()
        return await call_next(request)

    @app.middleware("http")
    async def kill_switch_middleware(request: Request, call_next):
        """Block requests when the kill switch is activated."""
        from fastapi.responses import JSONResponse

        try:
            ks = container.kill_switch()
            allowed = await ks.is_allowed(
                user_id=request.headers.get("X-User-ID", "anonymous"),
                endpoint=request.url.path,
            )
            if not allowed:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Service temporarily unavailable"},
                )
        except Exception:
            pass  # Fail-open: don't block requests if Redis is down

        return await call_next(request)

    # Security Headers Middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers to all responses."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    @app.middleware("http")
    async def input_validation_middleware(request: Request, call_next):
        """Validate and sanitize input for POST/PUT/PATCH requests."""
        if request.method in ("POST", "PUT", "PATCH"):
            if request.url.path in ("/health", "/docs", "/openapi.json", "/metrics"):
                return await call_next(request)

            try:
                from app.security.input_validator import InputValidator
                from fastapi.responses import JSONResponse

                body = await request.body()
                if body:
                    import json as _json
                    try:
                        parsed = _json.loads(body)
                        validator = InputValidator()
                        for key, value in parsed.items():
                            if isinstance(value, str) and len(value) > 50:
                                result = validator.validate(value)
                                if not result.is_valid:
                                    return JSONResponse(
                                        status_code=400,
                                        content={
                                            "detail": f"Input validation failed: {result.blocked_reason}",
                                            "field": key,
                                        },
                                    )
                    except (_json.JSONDecodeError, AttributeError):
                        pass
            except Exception:
                pass  # Fail-open

        return await call_next(request)

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://mrbekox.dev",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Accept",
            "Authorization",
            "Idempotency-Key",
            "X-Correlation-ID",
            "X-Request-ID",
            "X-Service-Key",
        ],
        expose_headers=["X-Correlation-ID"],
        max_age=300,
    )

    # Include routers from v1 endpoints
    from app.api.v1.endpoints.health import router as health_router
    from app.api.v1.endpoints.admin import router as admin_router

    app.include_router(health_router)
    app.include_router(admin_router)

    return app


# Create application instance
app = create_app()
