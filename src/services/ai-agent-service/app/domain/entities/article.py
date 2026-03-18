"""Article-related domain entities."""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
MAX_CONTENT_LENGTH = 100_000
VALID_LANGUAGES = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
VALID_REGIONS = {"TR", "US", "GB", "DE", "FR", "ES", "IT", "NL", "JP", "KR", "CN", "IN", "BR", "AU", "CA"}
VALID_VISIBILITIES = {"published", "restricted"}


class ArticlePayload(BaseModel):
    """Article payload from message with validation."""

    articleId: str = Field(..., description="Article GUID")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    authorId: str | None = None
    visibility: str = Field(default="published", description="Normalized article visibility")
    language: str | None = Field(default="tr", description="Content language")
    targetRegion: str | None = Field(default="TR", description="Target region for GEO")

    @field_validator("articleId")
    @classmethod
    def validate_article_id(cls, value: str) -> str:
        if not GUID_PATTERN.match(value):
            raise ValueError(f"Invalid GUID format: {value}")
        return value

    @field_validator("authorId")
    @classmethod
    def validate_author_id(cls, value: str | None) -> str | None:
        if value is not None and not GUID_PATTERN.match(value):
            raise ValueError(f"Invalid GUID format for authorId: {value}")
        return value

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str | None) -> str:
        if value is None:
            return "published"
        normalized = value.strip().lower()
        if normalized not in VALID_VISIBILITIES:
            return "published"
        return normalized

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str:
        if value is None:
            return "tr"
        normalized = value.lower()
        if normalized not in VALID_LANGUAGES:
            return "tr"
        return normalized

    @field_validator("targetRegion")
    @classmethod
    def validate_target_region(cls, value: str | None) -> str:
        if value is None:
            return "TR"
        normalized = value.upper()
        if normalized not in VALID_REGIONS:
            return "TR"
        return normalized


class ArticleMessage(BaseModel):
    """Message structure for article events."""

    messageId: str
    operationId: str | None = None
    correlationId: str | None = None
    causationId: str | None = None
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
