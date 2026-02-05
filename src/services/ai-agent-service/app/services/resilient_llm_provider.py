"""Resilient LLM provider wrapper with Circuit Breaker."""

from typing import List, AsyncGenerator
import logging

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.core.circuit_breaker import CircuitBreaker, CircuitOpenException
from app.security.output_handler import SecureResponseHandler

logger = logging.getLogger(__name__)

class ResilientLLMProvider(ILLMProvider):
    """
    Wrapper for LLM Provider that adds Circuit Breaker protection and value sanitization.
    """

    def __init__(self, provider: ILLMProvider, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.provider = provider
        # Create a circuit breaker specifically for LLM operations
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )
        self.handler = SecureResponseHandler()

    async def generate_json(self, prompt: str, schema: dict | None = None) -> dict:
        """Generate JSON with circuit breaker protection and sanitization."""
        try:
            result = await self.circuit_breaker.call(
                self.provider.generate_json, prompt, schema
            )
            # Sanitize the structured response
            return self.handler.sanitize_dict(result)
        except CircuitOpenException:
            logger.warning("LLM Circuit Open: Returning fallback JSON")
            return {"error": "Service temporarily unavailable", "content": "Fallback response"}

    async def warmup(self) -> None:
        await self.provider.warmup()

    def is_initialized(self) -> bool:
        return self.provider.is_initialized()

    async def generate_text(self, prompt: str, **kwargs) -> str:
        """Generate text with circuit breaker protection and sanitization."""
        try:
            result = await self.circuit_breaker.call(
                self.provider.generate_text, prompt, **kwargs
            )
            # Sanitize the text response
            return self.handler.sanitize_response(result)
        except CircuitOpenException:
            logger.warning("LLM Circuit Open: Returning fallback response")
            # Fallback response when circuit is open
            return "I am currently experiencing heavy load or maintenance. Please try again in a minute."
            
    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream text with circuit breaker protection."""
        # Streaming is trickier with circuit breaker wrapper pattern
        # Simple check before starting stream
        if not self.circuit_breaker.allow_request():
             logger.warning("LLM Circuit Open: Blocking stream request")
             yield "Service temporarily unavailable."
             return

        try:
            # Note: Streaming sanitization is difficult without buffering.
            # For now, we are bypassing full sanitization for streams to maintain low latency.
            # Ideally, valid output should be checked post-generation or via chunks if possible.
            async for chunk in self.provider.generate_stream(prompt, **kwargs):
                yield chunk
            self.circuit_breaker.record_success()
        except Exception as e:
            self.circuit_breaker.record_failure()
            logger.error(f"Stream failure recorded: {e}")
            raise e
