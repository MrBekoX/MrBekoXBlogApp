"""Article-related domain entities."""

import re
from typing import Any
from pydantic import BaseModel, Field, field_validator

# Validation patterns
GUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

# Maximum content length (100KB)
MAX_CONTENT_LENGTH = 100_000

# Valid languages and regions
VALID_LANGUAGES = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
VALID_REGIONS = {"TR", "US", "GB", "DE", "FR", "ES", "IT", "NL", "JP", "KR", "CN", "IN", "BR", "AU", "CA"}


class ArticlePayload(BaseModel):
    """Article payload from message with validation."""

    articleId: str = Field(..., description="Article GUID")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    authorId: str | None = None
    language: str | None = Field(default="tr", description="Content language")
    targetRegion: str | None = Field(default="TR", description="Target region for GEO")

    @field_validator('articleId')
    @classmethod
    def validate_article_id(cls, v: str) -> str:
        """Validate articleId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('authorId')
    @classmethod
    def validate_author_id(cls, v: str | None) -> str | None:
        """Validate authorId is a valid GUID format if provided."""
        if v is not None and not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format for authorId: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: str | None) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        if v_lower not in VALID_LANGUAGES:
            return "tr"
        return v_lower

    @field_validator('targetRegion')
    @classmethod
    def validate_target_region(cls, v: str | None) -> str:
        """Validate and normalize target region."""
        if v is None:
            return "TR"
        v_upper = v.upper()
        if v_upper not in VALID_REGIONS:
            return "TR"
        return v_upper


class ArticleMessage(BaseModel):
    """Message structure for article events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: ArticlePayload


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
    geo_optimization: dict[str, Any] | None = None
    processed_at: str
