"""Resilient LLM provider wrapper with Circuit Breaker."""

from typing import AsyncGenerator
import logging
import time

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.core.circuit_breaker import CircuitBreaker, CircuitOpenException
from app.security.output_handler import SecureResponseHandler
from app.monitoring.metrics import record_tool_invocation

logger = logging.getLogger(__name__)

class ResilientLLMProvider(ILLMProvider):
    """
    Wrapper for LLM Provider that adds Circuit Breaker protection and value sanitization.
    """

    def __init__(
        self,
        provider: ILLMProvider,
        failure_threshold: int = 3,
        recovery_timeout: int = 60,
        response_handler: SecureResponseHandler | None = None,
    ):
        self.provider = provider
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )
        self.handler = response_handler or SecureResponseHandler()

    async def generate_json(self, prompt: str, schema: dict | None = None) -> dict:
        """Generate JSON with circuit breaker protection and sanitization."""
        started_at = time.perf_counter()
        try:
            result = await self.circuit_breaker.call(
                self.provider.generate_json, prompt, schema
            )
            record_tool_invocation(
                tool="llm",
                operation="generate_json",
                duration_seconds=time.perf_counter() - started_at,
            )
            # Sanitize the structured response
            return self.handler.sanitize_dict(result)
        except CircuitOpenException as e:
            record_tool_invocation(
                tool="llm",
                operation="generate_json",
                duration_seconds=time.perf_counter() - started_at,
                error=e,
            )
            logger.warning("LLM Circuit Open: Returning fallback JSON")
            return {"error": "Service temporarily unavailable", "content": "Fallback response"}
        except Exception as e:
            record_tool_invocation(
                tool="llm",
                operation="generate_json",
                duration_seconds=time.perf_counter() - started_at,
                error=e,
            )
            raise

    async def warmup(self) -> None:
        await self.provider.warmup()

    def is_initialized(self) -> bool:
        return self.provider.is_initialized()

    async def generate_text(self, prompt: str, **kwargs) -> str:
        """Generate text with circuit breaker protection and sanitization."""
        started_at = time.perf_counter()
        try:
            result = await self.circuit_breaker.call(
                self.provider.generate_text, prompt, **kwargs
            )
            record_tool_invocation(
                tool="llm",
                operation="generate_text",
                duration_seconds=time.perf_counter() - started_at,
            )
            # Sanitize the text response
            return self.handler.sanitize_response(result)
        except CircuitOpenException as e:
            record_tool_invocation(
                tool="llm",
                operation="generate_text",
                duration_seconds=time.perf_counter() - started_at,
                error=e,
            )
            logger.warning("LLM Circuit Open: Returning fallback response")
            # Fallback response when circuit is open
            return "I am currently experiencing heavy load or maintenance. Please try again in a minute."
        except Exception as e:
            record_tool_invocation(
                tool="llm",
                operation="generate_text",
                duration_seconds=time.perf_counter() - started_at,
                error=e,
            )
            raise
            
    async def generate_stream(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream text with circuit breaker protection."""
        started_at = time.perf_counter()
        # Streaming is trickier with circuit breaker wrapper pattern
        # Simple check before starting stream
        if not self.circuit_breaker.allow_request():
            record_tool_invocation(
                tool="llm",
                operation="generate_stream",
                duration_seconds=time.perf_counter() - started_at,
                error="circuit_open",
            )
            logger.warning("LLM Circuit Open: Blocking stream request")
            yield "Service temporarily unavailable."
            return

        try:
            buffer = ""
            async for chunk in self.provider.generate_stream(prompt, **kwargs):
                buffer += chunk
                if len(buffer) >= 100:  # Sanitize in chunks
                    yield self.handler.sanitize_response(buffer)
                    buffer = ""
            if buffer:
                yield self.handler.sanitize_response(buffer)
            self.circuit_breaker.record_success()
            record_tool_invocation(
                tool="llm",
                operation="generate_stream",
                duration_seconds=time.perf_counter() - started_at,
            )
        except Exception as e:
            self.circuit_breaker.record_failure()
            logger.error(f"Stream failure recorded: {e}")
            record_tool_invocation(
                tool="llm",
                operation="generate_stream",
                duration_seconds=time.perf_counter() - started_at,
                error=e,
            )
            raise e
