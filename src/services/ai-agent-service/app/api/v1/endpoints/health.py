"""Health check endpoints."""

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.config import settings
from app.api.dependencies import health_snapshot
from app.api.runtime_state import runtime_state

router = APIRouter(tags=["Health"])
CONSUMER_IDLE_WARN_SECONDS = 300


def _build_health_payload() -> tuple[dict, bool]:
    """Build health payload and readiness decision."""
    runtime = runtime_state.snapshot()
    deps = health_snapshot()

    started = runtime.get("started_at") is not None
    broker_ok = deps.get("broker_connected", False)
    cache_ok = deps.get("cache_connected", False)
    llm_ok = deps.get("llm_initialized", False)
    consumer_running = runtime.get("consumer_running", False)
    consumer_idle_seconds = runtime.get("consumer_idle_seconds")
    backlog_over_threshold = deps.get("broker_backlog_over_threshold", False)
    langgraph_enabled = deps.get("langgraph_enabled", False)
    supervisor_initialized = deps.get("supervisor_initialized", False)
    consumer_not_stale = (
        consumer_idle_seconds is None or consumer_idle_seconds <= CONSUMER_IDLE_WARN_SECONDS
    )
    supervisor_ok = (not langgraph_enabled) or supervisor_initialized

    ready = bool(
        started
        and broker_ok
        and cache_ok
        and llm_ok
        and consumer_running
        and consumer_not_stale
        and supervisor_ok
        and not backlog_over_threshold
    )

    status = "healthy" if ready else ("degraded" if started else "starting")
    payload = {
        "status": status,
        "service": "ai-agent-service",
        "model": settings.ollama_model,
        "ready": ready,
        "dependencies": deps,
        "runtime": runtime,
    }
    return payload, ready


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    payload, _ = _build_health_payload()
    return payload


@router.get("/live")
async def liveness_check():
    """Liveness endpoint - process is alive."""
    return {"status": "alive", "service": "ai-agent-service"}


@router.get("/ready")
async def readiness_check():
    """Readiness endpoint - dependencies and consumer are healthy."""
    payload, ready = _build_health_payload()
    status_code = 200 if ready else 503
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "BlogApp AI Agent Service",
        "version": "4.0.0",
        "architecture": "Hexagonal (Ports & Adapters)",
        "model": settings.ollama_model,
        "docs": "/docs",
    }


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
