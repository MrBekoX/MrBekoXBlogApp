"""API v1 endpoints."""

from app.api.v1.endpoints.analysis import router as analysis_router
from app.api.v1.endpoints.chat import router as chat_router
from app.api.v1.endpoints.health import router as health_router

__all__ = ["analysis_router", "chat_router", "health_router"]
