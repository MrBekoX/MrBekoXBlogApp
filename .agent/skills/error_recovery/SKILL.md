---
name: Error Recovery Strategy
description: Circuit breaker pattern and graceful degradation.
---

# Error Recovery Strategy

This skill implements resilience patterns to handle external service failures (Ollama, Redis, RabbitMQ) without crashing the entire application.

## Circuit Breaker Pattern

Prevents cascading failures by stopping requests to a failing service for a cooldown period.

### Dependencies
Suggest using `pybreaker` or implement custom wrapper.

### Implementation Guide

```python
import pybreaker
import logging

logger = logging.getLogger(__name__)

# Configure Breakers
ollama_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=60,
    listeners=[pybreaker.CircuitBreakerListener()] # Add logging listener
)

redis_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=30
)

# Wrapper Service
class ResilientLLMProvider:
    def __init__(self, provider):
        self.provider = provider

    @ollama_breaker
    async def generate_text(self, prompt: str) -> str:
        try:
            return await self.provider.generate_text(prompt)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise e

# Fallback Logic
async def safe_chat(self, ...):
    try:
        response = await self.llm.generate_text(...)
    except pybreaker.CircuitBreakerError:
        logger.error("Ollama circuit open - using fallback")
        return "I am currently experiencing high load. Please try again later."
    except Exception:
        return "An error occurred."
```
