"""
AI Agent Service - Entry Point

Main entry point for the BlogApp AI Agent Service.
Uses Hexagonal Architecture (Ports & Adapters) for clean separation of concerns.

Usage:
    python -m app.main
    # OR with uvicorn directly
    uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload
"""

import logging

from app.core.config import settings


def setup_logging() -> None:
    """Configure logging based on settings."""
    # Set INFO level for production
    log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("aio_pika").setLevel(logging.WARNING)
    logging.getLogger("aiormq").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    """Main entry point - starts uvicorn server."""
    import uvicorn

    setup_logging()

    uvicorn.run(
        "app.api:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
