"""Rate limiting configuration."""

from typing import Tuple

RATE_LIMITS = {
    # Default limit if not specified
    "default": "20/minute",
    
    # High cost endpoints (LLM + RAG + Web Search)
    "/api/analyze": "10/minute",
    
    # Medium cost endpoints
    "/api/summarize": "20/minute",
    "/api/seo-description": "20/minute",
    "/api/keywords": "30/minute",
    "/api/sentiment": "30/minute",
    
    # Low cost endpoints
    "/api/reading-time": "60/minute", 
    "/api/geo-optimize": "15/minute", # Slightly higher cost than reading time
    "/api/collect-sources": "20/minute",
    
    # System endpoints
    "/health": "100/minute"
}

def parse_rate_limit(limit_str: str) -> Tuple[int, int]:
    """
    Parse a rate limit string (e.g. '10/minute') into (limit, period_in_seconds).
    
    Args:
        limit_str: String format like "10/minute", "5/second", "100/hour"
        
    Returns:
        Tuple of (limit_count, period_seconds)
    """
    try:
        count_str, period_str = limit_str.split("/")
        limit = int(count_str)
        
        period_str = period_str.lower()
        if period_str.startswith("second"):
            period = 1
        elif period_str.startswith("minute"):
            period = 60
        elif period_str.startswith("hour"):
            period = 3600
        elif period_str.startswith("day"):
            period = 86400
        else:
            period = 60 # Default to minute if unknown
            
        return limit, period
    except Exception:
        # Fallback
        return 10, 60
