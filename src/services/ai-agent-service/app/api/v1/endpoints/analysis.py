"""Analysis endpoints - Blog content analysis API."""

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import verify_api_key
from app.api.dependencies import (
    get_analysis_service,
    get_seo_service,
    get_cache,
)
from app.domain.interfaces.i_cache import ICache
from app.domain.entities.analysis import (
    AnalyzeRequest,
    SummarizeRequest,
    KeywordsRequest,
    SeoRequest,
    SentimentRequest,
    ReadingTimeRequest,
    GeoOptimizeRequest,
)
from app.services.analysis_service import AnalysisService
from app.services.seo_service import SeoService

router = APIRouter(prefix="/api", tags=["Analysis"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

# Cache TTL: 1 hour
CACHE_TTL = 3600


def _cache_key(prefix: str, content: str, **kwargs) -> str:
    """Generate cache key from content hash and parameters."""
    content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
    params = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return f"ai:{prefix}:{content_hash}:{params}" if params else f"ai:{prefix}:{content_hash}"


@router.post("/analyze")
@limiter.limit("10/minute")
async def full_analysis(
    request: Request,
    body: AnalyzeRequest,
    service: AnalysisService = Depends(get_analysis_service),
    cache: ICache = Depends(get_cache),
    _: str = Depends(verify_api_key)
):
    """
    Perform full article analysis.

    Returns summary, keywords, SEO description, reading time,
    sentiment analysis, and GEO optimization.
    """
    cache_key = _cache_key("analyze", body.content, lang=body.language, region=body.target_region)

    cached = await cache.get_json(cache_key)
    if cached:
        logger.info("Cache hit for full_analysis")
        return cached

    try:
        result = await service.full_analysis(
            content=body.content,
            target_region=body.target_region,
            language=body.language
        )
        response = result.model_dump()
        await cache.set_json(cache_key, response, CACHE_TTL)
        return response
    except Exception as e:
        logger.error(f"Full analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summarize")
@limiter.limit("20/minute")
async def summarize_article(
    request: Request,
    body: SummarizeRequest,
    service: AnalysisService = Depends(get_analysis_service),
    cache: ICache = Depends(get_cache),
    _: str = Depends(verify_api_key)
):
    """Generate article summary."""
    cache_key = _cache_key("summarize", body.content, lang=body.language, max=body.max_sentences)

    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    try:
        summary = await service.summarize_article(
            content=body.content,
            max_sentences=body.max_sentences,
            language=body.language
        )
        result = {"summary": summary}
        await cache.set_json(cache_key, result, CACHE_TTL)
        return result
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keywords")
@limiter.limit("30/minute")
async def extract_keywords(
    request: Request,
    body: KeywordsRequest,
    service: AnalysisService = Depends(get_analysis_service),
    cache: ICache = Depends(get_cache),
    _: str = Depends(verify_api_key)
):
    """Extract keywords from content."""
    cache_key = _cache_key("keywords", body.content, lang=body.language, count=body.count)

    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    try:
        keywords = await service.extract_keywords(
            content=body.content,
            count=body.count,
            language=body.language
        )
        result = {"keywords": keywords}
        await cache.set_json(cache_key, result, CACHE_TTL)
        return result
    except Exception as e:
        logger.error(f"Keyword extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seo-description")
@limiter.limit("20/minute")
async def generate_seo_description(
    request: Request,
    body: SeoRequest,
    service: SeoService = Depends(get_seo_service),
    cache: ICache = Depends(get_cache),
    _: str = Depends(verify_api_key)
):
    """Generate SEO meta description."""
    cache_key = _cache_key("seo", body.content, lang=body.language, max=body.max_length)

    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    try:
        description = await service.generate_seo_description(
            content=body.content,
            max_length=body.max_length,
            language=body.language
        )
        result = {"seo_description": description}
        await cache.set_json(cache_key, result, CACHE_TTL)
        return result
    except Exception as e:
        logger.error(f"SEO description failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sentiment")
@limiter.limit("30/minute")
async def analyze_sentiment(
    request: Request,
    body: SentimentRequest,
    service: AnalysisService = Depends(get_analysis_service),
    cache: ICache = Depends(get_cache),
    _: str = Depends(verify_api_key)
):
    """Analyze content sentiment."""
    cache_key = _cache_key("sentiment", body.content, lang=body.language)

    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    try:
        result = await service.analyze_sentiment(
            content=body.content,
            language=body.language
        )
        response = result.model_dump()
        await cache.set_json(cache_key, response, CACHE_TTL)
        return response
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reading-time")
@limiter.limit("60/minute")
def calculate_reading_time(
    request: Request,
    body: ReadingTimeRequest,
    service: AnalysisService = Depends(get_analysis_service),
    _: str = Depends(verify_api_key)
):
    """Calculate estimated reading time."""
    result = service.calculate_reading_time(
        content=body.content,
        words_per_minute=body.words_per_minute
    )
    return result.model_dump()


@router.post("/geo-optimize")
@limiter.limit("15/minute")
async def optimize_for_geo(
    request: Request,
    body: GeoOptimizeRequest,
    service: SeoService = Depends(get_seo_service),
    cache: ICache = Depends(get_cache),
    _: str = Depends(verify_api_key)
):
    """Optimize content for specific region (GEO targeting)."""
    cache_key = _cache_key("geo", body.content, lang=body.language, region=body.target_region)

    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    try:
        result = await service.optimize_for_geo(
            content=body.content,
            target_region=body.target_region,
            language=body.language
        )
        response = result.model_dump()
        await cache.set_json(cache_key, response, CACHE_TTL)
        return response
    except Exception as e:
        logger.error(f"GEO optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
