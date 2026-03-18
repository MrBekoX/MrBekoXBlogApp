"""Admin endpoints for quarantine and queue management."""

import logging
from typing import Any
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.dependencies import get_redis_adapter
from app.api.v1.endpoints.admin_idempotency import AdminReplayIdempotencyStore
from app.infrastructure.cache.redis_adapter import RedisAdapter
from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def get_broker() -> RabbitMQAdapter:
    """Dependency to get the broker from container."""
    from app.container import container
    return container.message_broker()


class QuarantineStatsResponse(BaseModel):
    """Response model for quarantine stats."""
    total_messages: int
    taxonomy_counts: dict[str, int]
    oldest_message_age_seconds: int | None


class QueueStatsResponse(BaseModel):
    """Response model for queue stats."""
    queues: dict[str, Any]


class ReplayRequest(BaseModel):
    """Request model for quarantine replay."""
    max_messages: int = 10
    dry_run: bool = False
    taxonomy_prefixes: list[str] | None = None
    max_age_seconds: int | None = None


class ReplayResponse(BaseModel):
    """Response model for quarantine replay."""
    replayed_count: int
    dry_run: bool
    details: dict[str, Any]


@router.get("/quarantine/stats", response_model=QuarantineStatsResponse)
async def get_quarantine_stats(
    broker: RabbitMQAdapter = Depends(get_broker),
) -> dict[str, Any]:
    """Get quarantine queue statistics."""
    try:
        stats = await broker.get_quarantine_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get quarantine stats: {e}")
        return {
            "total_messages": 0,
            "taxonomy_counts": {},
            "oldest_message_age_seconds": None,
            "error": str(e),
        }


@router.get("/queue/stats", response_model=QueueStatsResponse)
async def get_queue_stats(
    broker: RabbitMQAdapter = Depends(get_broker),
) -> dict[str, Any]:
    """Get main queue statistics."""
    try:
        stats = await broker.refresh_queue_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return {"queues": {}, "error": str(e)}


@router.post("/quarantine/replay", response_model=ReplayResponse)
async def replay_quarantine(
    http_request: Request,
    request: ReplayRequest,
    broker: RabbitMQAdapter = Depends(get_broker),
    redis_adapter: RedisAdapter = Depends(get_redis_adapter),
) -> dict[str, Any]:
    """Replay quarantined messages to the main exchange."""
    operation_id = (http_request.headers.get("Idempotency-Key") or "").strip()
    if not operation_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Idempotency-Key header is required."},
        )

    idempotency = AdminReplayIdempotencyStore(redis_adapter)
    claim = await idempotency.begin_request(operation_id, request.model_dump(mode="json"))

    if claim.state == "completed" and claim.response_payload is not None:
        return claim.response_payload

    if claim.state == "processing":
        return JSONResponse(
            status_code=409,
            content={"detail": claim.error_message or "This operation is already being processed."},
        )

    if claim.state == "conflict":
        return JSONResponse(
            status_code=409,
            content={"detail": claim.error_message or "The same Idempotency-Key was used with a different payload."},
        )

    if claim.state == "failed":
        return JSONResponse(
            status_code=422,
            content={"detail": claim.error_message or "Previous replay attempt failed."},
        )

    try:
        result = await broker.replay_quarantine_messages(
            max_messages=request.max_messages,
            dry_run=request.dry_run,
            taxonomy_prefixes=request.taxonomy_prefixes,
            max_age_seconds=request.max_age_seconds,
        )
        await idempotency.complete_request(operation_id, claim.request_hash, result)
        return result
    except Exception as e:
        logger.error(f"Failed to replay quarantine messages: {e}")
        result = {
            "replayed_count": 0,
            "dry_run": request.dry_run,
            "error": str(e),
        }
        await idempotency.complete_request(operation_id, claim.request_hash, result)
        return result
