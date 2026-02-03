"""Chat-related domain entities."""

import re
from dataclasses import dataclass
from pydantic import BaseModel, Field, field_validator

GUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)
MAX_CONTENT_LENGTH = 100_000


@dataclass
class ChatMessage:
    """A chat message (dataclass for internal use)."""

    role: str  # 'user' or 'assistant'
    content: str


class ChatHistoryItem(BaseModel):
    """A single chat history item (Pydantic for validation)."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequestPayload(BaseModel):
    """Payload for chat message requests."""

    sessionId: str = Field(..., min_length=1)
    postId: str = Field(..., description="Post GUID")
    articleTitle: str = Field(default="", max_length=500)
    articleContent: str = Field(default="", max_length=MAX_CONTENT_LENGTH)
    userMessage: str = Field(..., min_length=1, max_length=2000)
    conversationHistory: list[ChatHistoryItem] = Field(default_factory=list)
    language: str = Field(default="tr")
    enableWebSearch: bool = Field(default=False)

    @field_validator('postId')
    @classmethod
    def validate_post_id(cls, v: str) -> str:
        """Validate postId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Validate and normalize language code."""
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es"}
        if v_lower not in valid_languages:
            return "tr"
        return v_lower


class ChatRequestMessage(BaseModel):
    """Message structure for chat request events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: ChatRequestPayload


@dataclass
class ChatResponse:
    """Response from the chat handler."""

    response: str
    sources_used: int
    is_rag_response: bool
    context_preview: str | None = None
    sources: list[dict] | None = None
