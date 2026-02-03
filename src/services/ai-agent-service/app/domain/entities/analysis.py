"""Analysis-related domain entities."""

from typing import Any
from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request model for full article analysis."""

    content: str = Field(..., min_length=10, description="Article content to analyze")
    language: str = Field(default="tr", description="Content language (tr, en)")
    target_region: str = Field(default="TR", description="Target region for GEO optimization")


class SummarizeRequest(BaseModel):
    """Request model for summarization."""

    content: str = Field(..., min_length=10)
    max_sentences: int = Field(default=3, ge=1, le=10)
    language: str = Field(default="tr")


class KeywordsRequest(BaseModel):
    """Request model for keyword extraction."""

    content: str = Field(..., min_length=10)
    count: int = Field(default=5, ge=1, le=20)
    language: str = Field(default="tr")


class SeoRequest(BaseModel):
    """Request model for SEO description."""

    content: str = Field(..., min_length=10)
    max_length: int = Field(default=160, ge=50, le=300)
    language: str = Field(default="tr")


class SentimentRequest(BaseModel):
    """Request model for sentiment analysis."""

    content: str = Field(..., min_length=10)
    language: str = Field(default="tr")


class ReadingTimeRequest(BaseModel):
    """Request model for reading time calculation."""

    content: str = Field(..., min_length=1)
    words_per_minute: int = Field(default=200, ge=100, le=500)


class GeoOptimizeRequest(BaseModel):
    """Request model for GEO optimization."""

    content: str = Field(..., min_length=10)
    target_region: str = Field(default="TR")
    language: str = Field(default="tr")


class SentimentResult(BaseModel):
    """Result of sentiment analysis."""

    sentiment: str  # "positive", "negative", "neutral"
    confidence: int  # 0-100
    reasoning: str | None = None


class ReadingTimeResult(BaseModel):
    """Result of reading time calculation."""

    word_count: int
    reading_time_minutes: int
    words_per_minute: int


class GeoOptimizationResult(BaseModel):
    """Result of GEO optimization."""

    optimized_title: str
    meta_description: str
    geo_keywords: list[str]
    cultural_adaptations: str
    language_adjustments: str
    target_audience: str


class FullAnalysisResult(BaseModel):
    """Result of full article analysis."""

    summary: str
    keywords: list[str]
    seo_description: str
    sentiment: SentimentResult
    reading_time: ReadingTimeResult
    geo_optimization: GeoOptimizationResult | None = None
