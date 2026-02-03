"""Health check endpoints."""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {
        "status": "healthy",
        "service": "ai-agent-service",
        "model": settings.ollama_model,
    }


@router.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "BlogApp AI Agent Service",
        "version": "3.0.0",
        "architecture": "Hexagonal (Ports & Adapters)",
        "model": settings.ollama_model,
        "docs": "/docs",
    }
