"""AI generation-related domain entities."""

import logging
import re

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
MAX_CONTENT_LENGTH = 100_000
VALID_LANGUAGES = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}


def _validate_user_id(value: str) -> str:
    if not GUID_PATTERN.match(value):
        raise ValueError(f"Invalid GUID format: {value}")
    return value


def _validate_language(value: str | None) -> str:
    if value is None:
        return "tr"
    normalized = value.lower()
    if normalized not in VALID_LANGUAGES:
        logger.warning("Unknown language '%s', defaulting to 'tr'", value)
        return "tr"
    return normalized


class MessageEnvelope(BaseModel):
    """Common envelope for broker messages."""

    messageId: str
    operationId: str | None = None
    correlationId: str | None = None
    causationId: str | None = None
    timestamp: str
    eventType: str


class AiTitleGenerationPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiExcerptGenerationPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiTagsGenerationPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiSeoDescriptionGenerationPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiContentImprovementPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiSummarizePayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    maxSentences: int = Field(default=5, ge=1, le=20)
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiKeywordsPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    maxKeywords: int = Field(default=10, ge=1, le=30)
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiSentimentPayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiReadingTimePayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiGeoOptimizePayload(BaseModel):
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    targetRegion: str = Field(default="TR", max_length=10)
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiCollectSourcesPayload(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    userId: str = Field(..., description="User GUID")
    maxSources: int = Field(default=5, ge=1, le=20)
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator("userId")(_validate_user_id)
    _validate_language = field_validator("language")(_validate_language)


class AiTitleGenerationMessage(MessageEnvelope):
    payload: AiTitleGenerationPayload


class AiExcerptGenerationMessage(MessageEnvelope):
    payload: AiExcerptGenerationPayload


class AiTagsGenerationMessage(MessageEnvelope):
    payload: AiTagsGenerationPayload


class AiSeoDescriptionGenerationMessage(MessageEnvelope):
    payload: AiSeoDescriptionGenerationPayload


class AiContentImprovementMessage(MessageEnvelope):
    payload: AiContentImprovementPayload


class AiSummarizeMessage(MessageEnvelope):
    payload: AiSummarizePayload


class AiKeywordsMessage(MessageEnvelope):
    payload: AiKeywordsPayload


class AiSentimentMessage(MessageEnvelope):
    payload: AiSentimentPayload


class AiReadingTimeMessage(MessageEnvelope):
    payload: AiReadingTimePayload


class AiGeoOptimizeMessage(MessageEnvelope):
    payload: AiGeoOptimizePayload


class AiCollectSourcesMessage(MessageEnvelope):
    payload: AiCollectSourcesPayload
