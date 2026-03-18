"""Ollama LLM adapter - Concrete implementation of ILLMProvider."""

import logging
import re
from typing import Any, AsyncGenerator

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.core.config import settings

# Regex to strip <think>...</think> blocks from reasoning model output
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)

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
            **kwargs: Additional options:
                - temperature: float override
                - think: bool - enable/disable reasoning mode (default True).
                  Set to False for simple tasks (summarization, keyword extraction)
                  to dramatically reduce latency on reasoning models like qwen3.5.

        Returns:
            Generated text response
        """
        self._ensure_initialized()

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        think = kwargs.pop("think", True)

        # Build LLM instance with optional overrides
        needs_custom = "temperature" in kwargs or not think
        if needs_custom:
            extra_kwargs: dict[str, Any] = {}
            if not think:
                extra_kwargs["extra_body"] = {"think": False}
            llm = ChatOllama(
                model=self._model,
                base_url=self._base_url,
                temperature=kwargs.get("temperature", self._temperature),
                timeout=self._timeout,
                num_ctx=self._num_ctx,
                **extra_kwargs,
            )
        else:
            llm = self._llm

        result = await llm.ainvoke([HumanMessage(content=prompt)])
        text = result.content.strip() if result.content else ""

        # Strip <think>...</think> blocks if present (safety net)
        text = _THINK_BLOCK_RE.sub("", text).strip()
        return text

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

        import json
        import re
        from langchain_core.messages import HumanMessage

        # Use think=False for structured JSON output to reduce latency
        llm = ChatOllama(
            model=self._model,
            base_url=self._base_url,
            temperature=0.1,
            timeout=self._timeout,
            num_ctx=self._num_ctx,
            extra_body={"think": False},
        )
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        raw_content = result.content.strip() if result.content else ""

        # Strip thinking blocks if present
        raw_content = _THINK_BLOCK_RE.sub("", raw_content).strip()

        if not raw_content:
            logger.warning("LLM returned empty response for JSON request")
            return {}

        # Try to extract JSON from response (handles markdown code blocks, etc.)
        json_str = raw_content

        # Check for markdown code block: ```json ... ```
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_content)
        if json_match:
            json_str = json_match.group(1).strip()

        # Try to find JSON object or array in the response
        if not json_str.startswith(('{', '[')):
            obj_match = re.search(r'\{[\s\S]*\}', raw_content)
            if obj_match:
                json_str = obj_match.group(0)

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Raw response was: {raw_content[:500]}...")
            return {}

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
        logger.info(f"Warmup complete, model response: {result.content.strip() if result.content else ''}")

    def is_initialized(self) -> bool:
        """Check if the provider is initialized and ready."""
        return self._initialized and self._llm is not None

    async def generate_stream(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Generate text streaming token by token.

        Args:
            prompt: The input prompt (already formatted)
            **kwargs: Additional options (temperature override, etc.)

        Yields:
            Text chunks as they are generated
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

        # Stream the response
        from langchain_core.messages import HumanMessage

        async for chunk in llm.astream([HumanMessage(content=prompt)]):
            if isinstance(chunk, (AIMessage, AIMessageChunk)):
                yield chunk.content
            elif hasattr(chunk, 'content'):
                yield str(chunk.content)
