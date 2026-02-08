"""Chat endpoints - RAG-powered article Q&A API."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.dependencies import get_chat_service
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api", tags=["Chat"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


from fastapi.responses import StreamingResponse

class ChatRequest(BaseModel):
    """Request model for chat."""
    post_id: str = Field(..., description="Article ID")
    message: str = Field(..., min_length=1, description="User message")
    conversation_history: list[dict] | None = Field(default=None, description="Previous messages")
    language: str = Field(default="tr", description="Language code")


@router.post("/stream")
@limiter.limit("60/minute")
async def chat_stream_endpoint(
    request: Request,
    body: ChatRequest,
    service: ChatService = Depends(get_chat_service),
):
    """
    Stream chat response (Server-Sent Events).
    """
    return StreamingResponse(
        service.chat_stream(
            post_id=body.post_id,
            user_message=body.message,
            conversation_history=None, 
            language=body.language
        ),
        media_type="text/event-stream"
    )


class CollectSourcesRequest(BaseModel):
    """Request for collecting web sources."""

    post_id: str = Field(..., description="Article ID")
    title: str = Field(..., min_length=3, description="Article title")
    content: str = Field(..., min_length=10, description="Article content")
    question: str = Field(..., min_length=3, description="User question")
    language: str = Field(default="tr", description="Language code")
    max_results: int = Field(default=10, ge=1, le=20)


@router.post("/collect-sources")
@limiter.limit("20/minute")
async def collect_sources(
    request: Request,
    body: CollectSourcesRequest,
    service: ChatService = Depends(get_chat_service),
):
    """
    Collect trusted web sources based on article content.
    """
    try:
        sources = await service.collect_sources(
            post_id=body.post_id,
            article_title=body.title,
            article_content=body.content,
            user_question=body.question,
            language=body.language,
            max_results=body.max_results
        )
        return {"sources": sources}
    except Exception as e:
        logger.error(f"Collect sources failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again later.")
