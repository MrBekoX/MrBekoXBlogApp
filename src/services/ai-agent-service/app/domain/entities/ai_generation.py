"""AI Generation-related domain entities."""

import logging
import re
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

GUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)
MAX_CONTENT_LENGTH = 100_000
VALID_LANGUAGES = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}


def _validate_user_id(v: str) -> str:
    """Validate userId is a valid GUID format."""
    if not GUID_PATTERN.match(v):
        raise ValueError(f'Invalid GUID format: {v}')
    return v


def _validate_language(v: str | None) -> str:
    """Validate and normalize language code."""
    if v is None:
        return "tr"
    v_lower = v.lower()
    if v_lower not in VALID_LANGUAGES:
        logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
        return "tr"
    return v_lower


class AiTitleGenerationPayload(BaseModel):
    """Payload for AI title generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator('userId')(_validate_user_id)
    _validate_language = field_validator('language')(_validate_language)


class AiExcerptGenerationPayload(BaseModel):
    """Payload for AI excerpt generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator('userId')(_validate_user_id)
    _validate_language = field_validator('language')(_validate_language)


class AiTagsGenerationPayload(BaseModel):
    """Payload for AI tags generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator('userId')(_validate_user_id)
    _validate_language = field_validator('language')(_validate_language)


class AiSeoDescriptionGenerationPayload(BaseModel):
    """Payload for AI SEO description generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator('userId')(_validate_user_id)
    _validate_language = field_validator('language')(_validate_language)


class AiContentImprovementPayload(BaseModel):
    """Payload for AI content improvement requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: str | None = Field(default="tr", description="Content language")

    _validate_user_id = field_validator('userId')(_validate_user_id)
    _validate_language = field_validator('language')(_validate_language)


class AiTitleGenerationMessage(BaseModel):
    """Message structure for AI title generation events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: AiTitleGenerationPayload


class AiExcerptGenerationMessage(BaseModel):
    """Message structure for AI excerpt generation events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: AiExcerptGenerationPayload


class AiTagsGenerationMessage(BaseModel):
    """Message structure for AI tags generation events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: AiTagsGenerationPayload


class AiSeoDescriptionGenerationMessage(BaseModel):
    """Message structure for AI SEO description generation events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: AiSeoDescriptionGenerationPayload


class AiContentImprovementMessage(BaseModel):
    """Message structure for AI content improvement events."""

    messageId: str
    correlationId: str | None = None
    timestamp: str
    eventType: str
    payload: AiContentImprovementPayload
