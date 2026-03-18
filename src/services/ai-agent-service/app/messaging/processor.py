"""Message models for RabbitMQ event processing.

These models are used by MessageProcessorService and RabbitMQConsumer
for parsing incoming messages.
"""

import logging
import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# RabbitMQ Constants
EXCHANGE_NAME = "blog.events"
AI_ANALYSIS_COMPLETED_ROUTING_KEY = "ai.analysis.completed"
CHAT_RESPONSE_ROUTING_KEY = "chat.message.completed"

# Validation patterns
GUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

# Maximum content length (100KB)
MAX_CONTENT_LENGTH = 100_000


class TargetRegion(str, Enum):
    """Supported target regions for GEO optimization."""
    TR = "TR"
    US = "US"
    GB = "GB"
    DE = "DE"
    FR = "FR"
    ES = "ES"
    IT = "IT"
    NL = "NL"
    JP = "JP"
    KR = "KR"
    CN = "CN"
    IN = "IN"
    BR = "BR"
    AU = "AU"
    CA = "CA"


class SupportedLanguage(str, Enum):
    """Supported content languages."""
    TR = "tr"
    EN = "en"
    DE = "de"
    FR = "fr"
    ES = "es"


class AiTitleGenerationPayload(BaseModel):
    """Payload for AI title generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiExcerptGenerationPayload(BaseModel):
    """Payload for AI excerpt generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiTagsGenerationPayload(BaseModel):
    """Payload for AI tags generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiSeoDescriptionGenerationPayload(BaseModel):
    """Payload for AI SEO description generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiContentImprovementPayload(BaseModel):
    """Payload for AI content improvement requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class ArticlePayload(BaseModel):
    """Article payload from message with validation."""

    articleId: str = Field(..., description="Article GUID")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    authorId: Optional[str] = None
    language: Optional[str] = Field(default="tr", description="Content language")
    targetRegion: Optional[str] = Field(default="TR", description="Target region for GEO")

    @field_validator('articleId')
    @classmethod
    def validate_article_id(cls, v: str) -> str:
        """Validate articleId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('authorId')
    @classmethod
    def validate_author_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate authorId is a valid GUID format if provided."""
        if v is not None and not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format for authorId: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        # Accept common language codes
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower

    @field_validator('targetRegion')
    @classmethod
    def validate_target_region(cls, v: Optional[str]) -> str:
        """Validate and normalize target region."""
        if v is None:
            return "TR"
        v_upper = v.upper()
        # Accept common region codes
        valid_regions = {"TR", "US", "GB", "DE", "FR", "ES", "IT", "NL", "JP", "KR", "CN", "IN", "BR", "AU", "CA"}
        if v_upper not in valid_regions:
            logger.warning(f"Unknown region '{v}', defaulting to 'TR'")
            return "TR"
        return v_upper


class ArticleMessage(BaseModel):
    """Message structure for article events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: ArticlePayload


class AiTitleGenerationMessage(BaseModel):
    """Message structure for AI title generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiTitleGenerationPayload


class AiExcerptGenerationMessage(BaseModel):
    """Message structure for AI excerpt generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiExcerptGenerationPayload


class AiTagsGenerationMessage(BaseModel):
    """Message structure for AI tags generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiTagsGenerationPayload


class AiSeoDescriptionGenerationMessage(BaseModel):
    """Message structure for AI SEO description generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiSeoDescriptionGenerationPayload


class AiContentImprovementMessage(BaseModel):
    """Message structure for AI content improvement events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiContentImprovementPayload


class ProcessingResult(BaseModel):
    """Result of article processing."""

    article_id: str
    summary: str
    keywords: list[str]
    seo_description: str
    reading_time_minutes: float
    word_count: int
    sentiment: str
    sentiment_confidence: int
    geo_optimization: Optional[dict[str, Any]] = None
    processed_at: str


# Chat Message Models
class ChatHistoryItem(BaseModel):
    """A single chat history item."""
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
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: ChatRequestPayload
