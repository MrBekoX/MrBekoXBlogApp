---
name: Rate Limiting Strategy
description: Endpoint-based dynamic rate limiting configuration.
---

# Rate Limiting Strategy

This skill configures fine-grained rate limits for different API endpoints based on resource consumption.

## Configuration

Define a central configuration map:

```python
# app/core/config.py or app/core/rate_limits.py

RATE_LIMITS = {
    "default": "20/minute",
    "/api/chat": "10/minute",      # High Cost (LLM + RAG + Search)
    "/api/analyze": "5/minute",    # Very High Cost (Deep Analysis)
    "/api/summarize": "20/minute", # Medium Cost
    "/health": "100/minute"        # Low Cost
}
```

## Implementation Guide

Update `app/api/endpoints.py`.

```python
from app.core.rate_limits import RATE_LIMITS

@router.post("/api/chat")
@limiter.limit(RATE_LIMITS["/api/chat"])
async def chat_endpoint(request: Request, ...):
    ...

@router.post("/api/analyze")
@limiter.limit(RATE_LIMITS["/api/analyze"])
async def analyze_endpoint(request: Request, ...):
    ...
```

### Dynamic Limits

For more advanced logic (e.g., limits based on user tier):

```python
def get_rate_limit(request: Request):
    user_tier = request.state.user.tier # Hypothetical
    if user_tier == "premium":
        return "100/minute"
    return "10/minute"

@router.post("/api/chat")
@limiter.limit(get_rate_limit)
async def chat_dynamic(...):
    ...
```
