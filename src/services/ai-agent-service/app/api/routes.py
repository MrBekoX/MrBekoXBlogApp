"""
FastAPI Application - BlogApp AI Agent Service

Application factory and lifecycle management with Hexagonal Architecture.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logging_utils import sanitize_url
from app.api.dependencies import DependencyContainer, get_llm_provider
from app.services.message_processor_service import MessageProcessorService

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Background task reference
_consumer_task: asyncio.Task | None = None
_message_processor: MessageProcessorService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown of all infrastructure components
    following Hexagonal Architecture principles.
    """
    global _consumer_task, _message_processor

    # === STARTUP ===
    logger.info("=" * 60)
    logger.info("BlogApp AI Agent Service Starting...")
    logger.info("=" * 60)
    logger.info(f"Architecture: Hexagonal (Ports & Adapters)")
    logger.info(f"Environment: {'Development' if settings.debug else 'Production'}")
    logger.info(f"LLM Model: {settings.ollama_model}")
    logger.info(f"RabbitMQ: {settings.rabbitmq_host}:{settings.rabbitmq_port}")
    logger.info(f"Redis: {sanitize_url(settings.redis_url)}")
    logger.info("=" * 60)

    # Initialize all infrastructure via DependencyContainer
    logger.info("Initializing infrastructure components...")
    await DependencyContainer.initialize_all()

    # Get LLM provider and warm up
    logger.info("Warming up LLM model...")
    try:
        llm = DependencyContainer.get_llm()
        await llm.warmup()
        logger.info("LLM model warmed up successfully!")
    except Exception as e:
        logger.warning(f"Model warmup failed (will load on first request): {e}")

    # Create message processor with all dependencies
    from app.services.analysis_service import AnalysisService
    from app.services.seo_service import SeoService
    from app.services.indexing_service import IndexingService
    from app.services.rag_service import RagService
    from app.services.chat_service import ChatService

    llm = DependencyContainer.get_llm()
    cache = DependencyContainer.get_cache()
    broker = DependencyContainer.get_broker()
    embedding = DependencyContainer.get_embedding()
    vector_store = DependencyContainer.get_vector_store()
    web_search = DependencyContainer.get_web_search()

    seo_service = SeoService(llm_provider=llm)
    analysis_service = AnalysisService(llm_provider=llm, seo_service=seo_service)
    rag_service = RagService(embedding_provider=embedding, vector_store=vector_store, llm_provider=llm)
    indexing_service = IndexingService(embedding_provider=embedding, vector_store=vector_store)
    chat_service = ChatService(
        llm_provider=llm,
        rag_service=rag_service,
        web_search_provider=web_search,
        analysis_service=analysis_service
    )

    _message_processor = MessageProcessorService(
        cache=cache,
        message_broker=broker,
        analysis_service=analysis_service,
        indexing_service=indexing_service,
        chat_service=chat_service
    )

    # Start RabbitMQ consumer in background
    try:
        logger.info("Starting message consumer...")
        _consumer_task = asyncio.create_task(
            broker.start_consuming(_message_processor.process_message)
        )
        logger.info("RabbitMQ consumer started successfully")
    except Exception as e:
        logger.warning(f"Failed to start RabbitMQ consumer: {e}")
        logger.info("Service will continue without message consumption")

    logger.info("AI Agent Service started successfully!")

    yield  # Application runs here

    # === SHUTDOWN ===
    logger.info("Shutting down AI Agent Service...")

    if _consumer_task:
        broker = DependencyContainer.get_broker()
        await broker.stop_consuming()
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    await DependencyContainer.shutdown_all()
    logger.info("AI Agent Service stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="BlogApp AI Agent Service",
        description="AI-powered blog analysis using Hexagonal Architecture",
        version="3.0.0",
        lifespan=lifespan,
    )

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
        allow_headers=["Content-Type", "X-Api-Key", "Accept"],
        expose_headers=[],
        max_age=300,
    )

    # Include routers from v1 endpoints
    from app.api.v1.endpoints.health import router as health_router
    from app.api.v1.endpoints.analysis import router as analysis_router
    from app.api.v1.endpoints.chat import router as chat_router

    app.include_router(health_router)
    app.include_router(analysis_router)
    app.include_router(chat_router)

    return app


# Create application instance
app = create_app()
