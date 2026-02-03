"""Ollama LLM adapter - Concrete implementation of ILLMProvider."""

import logging
from typing import Any

from langchain_ollama import ChatOllama

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class OllamaAdapter(ILLMProvider):
    """
    Ollama implementation of LLM provider.

    Uses LangChain's ChatOllama for consistent API.
    Can be swapped with OpenAI, Anthropic, etc. by implementing ILLMProvider.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
        num_ctx: int | None = None,
    ):
        self._model = model or settings.ollama_model
        self._base_url = base_url or settings.ollama_base_url
        self._temperature = temperature if temperature is not None else settings.ollama_temperature
        self._timeout = timeout or settings.ollama_timeout
        self._num_ctx = num_ctx or settings.ollama_num_ctx
        self._llm: ChatOllama | None = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Initialize LLM if not already done."""
        if self._initialized:
            return

        logger.info(f"Initializing OllamaAdapter with model: {self._model}")

        self._llm = ChatOllama(
            model=self._model,
            base_url=self._base_url,
            temperature=self._temperature,
            timeout=self._timeout,
            num_ctx=self._num_ctx,
        )

        self._initialized = True
        logger.info("OllamaAdapter initialized successfully")

    async def generate_text(self, prompt: str, **kwargs) -> str:
        """
        Generate text from a prompt.

        Args:
            prompt: The input prompt (already formatted, should NOT contain {variables})
            **kwargs: Additional options (temperature override, etc.)

        Returns:
            Generated text response
        """
        self._ensure_initialized()

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        # Allow temperature override per request
        llm = self._llm
        if 'temperature' in kwargs:
            llm = ChatOllama(
                model=self._model,
                base_url=self._base_url,
                temperature=kwargs['temperature'],
                timeout=self._timeout,
                num_ctx=self._num_ctx,
            )

        # Direct invocation - prompt is already formatted
        from langchain_core.messages import HumanMessage
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        return result.content.strip()

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Generate structured JSON from a prompt.

        Args:
            prompt: The input prompt requesting JSON output
            schema: Optional JSON schema for validation (not enforced by Ollama)

        Returns:
            Parsed JSON response as dictionary
        """
        self._ensure_initialized()

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        from langchain_core.messages import HumanMessage
        result = await self._llm.ainvoke([HumanMessage(content=prompt)])

        # Parse JSON response
        import json
        return json.loads(result.content)

    async def warmup(self) -> None:
        """
        Warm up the model by making a simple call.
        This loads the model into memory for faster subsequent requests.
        """
        self._ensure_initialized()

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        logger.info("Starting model warmup...")

        from langchain_core.messages import HumanMessage
        result = await self._llm.ainvoke([HumanMessage(content="Say 'ready' in one word.")])
        logger.info(f"Warmup complete, model response: {result.content.strip()}")

    def is_initialized(self) -> bool:
        """Check if the provider is initialized and ready."""
        return self._initialized and self._llm is not None
