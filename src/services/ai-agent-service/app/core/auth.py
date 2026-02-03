"""API Key authentication for HTTP endpoints."""

import logging
from typing import Optional

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

logger = logging.getLogger(__name__)

# API Key header configuration
api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify API Key for protected endpoints.

    Args:
        api_key: API key from X-Api-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    # If API key is not configured, skip validation (development mode)
    if not settings.api_key:
        logger.warning("API Key not configured - endpoints are unprotected!")
        return ""

    if not api_key:
        logger.warning("API Key required but not provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key required. Provide X-Api-Key header."
        )

    if api_key != settings.api_key:
        logger.warning("Invalid API Key provided")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key"
        )

    return api_key


async def verify_api_key_optional(api_key: Optional[str] = Security(api_key_header)) -> Optional[str]:
    """
    Optional API Key verification - doesn't raise if missing.
    Use this for endpoints that work both with and without authentication.

    Args:
        api_key: API key from X-Api-Key header

    Returns:
        The API key if valid, None otherwise
    """
    if not settings.api_key:
        return None

    if not api_key:
        return None

    if api_key != settings.api_key:
        return None

    return api_key
