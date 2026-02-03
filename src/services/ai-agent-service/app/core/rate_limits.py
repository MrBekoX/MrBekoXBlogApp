"""Rate limiting configuration."""

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
