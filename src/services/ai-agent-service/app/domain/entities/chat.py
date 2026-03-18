"""Chat-related domain entities."""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
MAX_CONTENT_LENGTH = 100_000


@dataclass
class ChatMessage:
    """A chat message used internally by the agent."""

    role: str
    content: str


class ChatHistoryItem(BaseModel):
    """A single chat history item."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatAuthorizationContext(BaseModel):
    """Authorization context forwarded from the backend chat edge."""

    subjectType: str = Field(default="anonymous")
    subjectId: str | None = Field(default=None)
    roles: list[str] = Field(default_factory=list)
    fingerprint: str | None = Field(default=None)


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
    authContext: ChatAuthorizationContext = Field(default_factory=ChatAuthorizationContext)

    @field_validator("postId")
    @classmethod
    def validate_post_id(cls, value: str) -> str:
        if not GUID_PATTERN.match(value):
            raise ValueError(f"Invalid GUID format: {value}")
        return value

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = value.lower()
        valid_languages = {"tr", "en", "de", "fr", "es"}
        if normalized not in valid_languages:
            return "tr"
        return normalized


class ChatRequestMessage(BaseModel):
    """Message envelope for chat request events."""

    messageId: str
    operationId: str | None = None
    correlationId: str | None = None
    causationId: str | None = None
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
    citations: list[dict] | None = None
