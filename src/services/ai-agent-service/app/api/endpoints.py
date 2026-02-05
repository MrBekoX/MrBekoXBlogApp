"""
API Endpoints - BlogApp AI Agent Service

REST API endpoint handlers for health checks and AI analysis tools.
Protected endpoints require X-Api-Key header.
"""

import hashlib
import logging
from asyncio import TimeoutError as TimeoutException
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings
from app.core.rate_limits import RATE_LIMITS
from app.core.cache import cache
from app.core.auth import verify_api_key
from app.security.m2m_auth import require_analyze_scope, require_chat_scope, require_admin_scope
from app.agent.simple_blog_agent import simple_blog_agent

# Cache TTL: 1 hour (results don't change for same content)
CACHE_TTL_SECONDS = 3600

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


# ==================== Request/Response Models ====================


class AnalyzeRequest(BaseModel):
    """Request model for article analysis."""
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


class CollectSourcesRequest(BaseModel):
    post_id: str = Field(..., description="Article ID")
    title: str = Field(..., min_length=3, description="Article title")
    content: str = Field(..., min_length=10, description="Full article content")
    question: str = Field(..., min_length=3, description="User question about the article")
    language: str = Field(default="tr", description="Language code: tr or en")
    max_results: int = Field(default=10, ge=1, le=20)


# ==================== Helper Functions ====================


def generate_cache_key(prefix: str, content: str, **kwargs) -> str:
    """Generate a cache key based on content hash and parameters."""
    # Create a hash of the content to avoid long keys
    content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
    # Include additional parameters in the key
    params = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return f"ai:{prefix}:{content_hash}:{params}" if params else f"ai:{prefix}:{content_hash}"


def handle_llm_exception(e: Exception, operation: str) -> None:
    """Handle LLM-related exceptions with proper logging and HTTP responses."""
    logger.error(f"{operation} failed: {e}", exc_info=True)
    
    if isinstance(e, TimeoutException):
        raise HTTPException(
            status_code=504,
            detail=f"{operation} timed out. Please try again."
        )
    elif isinstance(e, ValidationError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid response from LLM: {str(e)}"
        )
    elif isinstance(e, ConnectionError):
        raise HTTPException(
            status_code=503,
            detail=f"Service unavailable: {str(e)}"
        )
    elif isinstance(e, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid input: {str(e)}"
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"{operation} failed: {str(e)}"
        )


# ==================== Health & Info Endpoints ====================


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {
        "status": "healthy",
        "service": "ai-agent-service",
        "model": settings.ollama_model,
    }


@router.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "BlogApp AI Agent Service",
        "version": "2.0.0",
        "model": settings.ollama_model,
        "docs": "/docs",
    }


# ==================== AI Analysis Endpoints ====================


@router.post("/api/analyze")
@limiter.limit(RATE_LIMITS["/api/analyze"])
async def full_analysis(
    request: Request,
    analyze_request: AnalyzeRequest,
    claims: dict = Depends(require_analyze_scope)
):
    """
    Perform full article analysis.

    Returns summary, keywords, SEO description, reading time,
    sentiment analysis, and GEO optimization.
    """
    # Anomaly Detection
    from app.monitoring.anomaly_detector import anomaly_detector
    
    # We use client_id or subject from claims as user_id
    user_id = claims.get("client_id") or claims.get("sub", "unknown")
    
    anomaly = await anomaly_detector.record_request(
        user_id=user_id,
        success=True,
        token_count=len(analyze_request.content.split()) # Estimate
    )
    
    if anomaly and anomaly.severity == "critical":
        raise HTTPException(
            status_code=429,
            detail="Too many requests (Anomaly Detected). Please try again later."
        )

    # Check cache first
    cache_key = generate_cache_key(
        "analyze",
        analyze_request.content,
        lang=analyze_request.language,
        region=analyze_request.target_region
    )

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info(f"Cache hit for full_analysis")
        return cached

    try:
        result = await simple_blog_agent.full_analysis(
            content=analyze_request.content,
            target_region=analyze_request.target_region,
            language=analyze_request.language,
        )
        # Store in cache
        await cache.set_json(cache_key, result, CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        handle_llm_exception(e, "Full analysis")


@router.post("/api/summarize")
@limiter.limit(RATE_LIMITS["/api/summarize"])
async def summarize_article(
    request: Request,
    summarize_request: SummarizeRequest,
    _api_key: str = Depends(verify_api_key)
):
    """Generate article summary."""
    cache_key = generate_cache_key(
        "summarize",
        summarize_request.content,
        lang=summarize_request.language,
        max_sent=summarize_request.max_sentences
    )

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info("Cache hit for summarize")
        return cached

    try:
        summary = await simple_blog_agent.summarize_article(
            content=summarize_request.content,
            max_sentences=summarize_request.max_sentences,
            language=summarize_request.language,
        )
        result = {"summary": summary}
        await cache.set_json(cache_key, result, CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        handle_llm_exception(e, "Summarization")


@router.post("/api/keywords")
@limiter.limit(RATE_LIMITS["/api/keywords"])
async def extract_keywords(
    request: Request,
    keywords_request: KeywordsRequest,
    _api_key: str = Depends(verify_api_key)
):
    """Extract keywords from content."""
    cache_key = generate_cache_key(
        "keywords",
        keywords_request.content,
        lang=keywords_request.language,
        count=keywords_request.count
    )

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info("Cache hit for keywords")
        return cached

    try:
        keywords = await simple_blog_agent.extract_keywords(
            content=keywords_request.content,
            count=keywords_request.count,
            language=keywords_request.language,
        )
        result = {"keywords": keywords}
        await cache.set_json(cache_key, result, CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        handle_llm_exception(e, "Keyword extraction")


@router.post("/api/seo-description")
@limiter.limit(RATE_LIMITS["/api/seo-description"])
async def generate_seo_description(
    request: Request,
    seo_request: SeoRequest,
    _api_key: str = Depends(verify_api_key)
):
    """Generate SEO meta description."""
    cache_key = generate_cache_key(
        "seo",
        seo_request.content,
        lang=seo_request.language,
        max_len=seo_request.max_length
    )

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info("Cache hit for seo-description")
        return cached

    try:
        description = await simple_blog_agent.generate_seo_description(
            content=seo_request.content,
            max_length=seo_request.max_length,
            language=seo_request.language,
        )
        result = {"seo_description": description}
        await cache.set_json(cache_key, result, CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        handle_llm_exception(e, "SEO description generation")


@router.post("/api/sentiment")
@limiter.limit(RATE_LIMITS["/api/sentiment"])
async def analyze_sentiment(
    request: Request,
    sentiment_request: SentimentRequest,
    _api_key: str = Depends(verify_api_key)
):
    """Analyze content sentiment."""
    cache_key = generate_cache_key(
        "sentiment",
        sentiment_request.content,
        lang=sentiment_request.language
    )

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info("Cache hit for sentiment")
        return cached

    try:
        result = await simple_blog_agent.analyze_sentiment(
            content=sentiment_request.content,
            language=sentiment_request.language,
        )
        await cache.set_json(cache_key, result, CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        handle_llm_exception(e, "Sentiment analysis")


@router.post("/api/reading-time")
@limiter.limit(RATE_LIMITS["/api/reading-time"])
def calculate_reading_time(
    request: Request,
    reading_time_request: ReadingTimeRequest,
    _api_key: str = Depends(verify_api_key)
):
    """Calculate estimated reading time."""
    result = simple_blog_agent.calculate_reading_time(
        content=reading_time_request.content,
        words_per_minute=reading_time_request.words_per_minute,
    )
    return result


@router.post("/api/geo-optimize")
@limiter.limit(RATE_LIMITS["/api/geo-optimize"])
async def optimize_for_geo(
    request: Request,
    geo_request: GeoOptimizeRequest,
    claims: dict = Depends(require_analyze_scope)
):
    """Optimize content for specific region (GEO targeting)."""
    cache_key = generate_cache_key(
        "geo",
        geo_request.content,
        lang=geo_request.language,
        region=geo_request.target_region
    )

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info("Cache hit for geo-optimize")
        return cached

    try:
        result = await simple_blog_agent.optimize_for_geo(
            content=geo_request.content,
            target_region=geo_request.target_region,
            language=geo_request.language,
        )
        await cache.set_json(cache_key, result, CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        handle_llm_exception(e, "GEO optimization")

        handle_llm_exception(e, "GEO optimization")


@router.post("/api/collect-sources")
@limiter.limit(RATE_LIMITS["/api/collect-sources"])
async def collect_sources(
    request: Request,
    body: CollectSourcesRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Collect trusted web sources based on article content.
    """
    try:
        from app.agent.rag_chat_handler import rag_chat_handler

        sources = await rag_chat_handler.collect_sources(
            post_id=body.post_id,
            articletitle=body.title,
            articlecontent=body.content,
            user_question=body.question,
            language=body.language,
            max_results=body.max_results,
        )

        return {"sources": sources}

    except Exception as e:
        handle_llm_exception(e, "Collect sources")
