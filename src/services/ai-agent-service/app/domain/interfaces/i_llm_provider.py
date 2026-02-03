"""LLM Provider interface - Contract for text generation services."""

from abc import ABC, abstractmethod
from typing import Any


class ILLMProvider(ABC):
    """
    Abstract interface for LLM providers.

    Implementations can be Ollama, OpenAI, Anthropic, etc.
    This follows Interface Segregation Principle (ISP) - only essential methods.
    """

    @abstractmethod
    async def generate_text(self, prompt: str, **kwargs) -> str:
        """
        Generate text from a prompt.

        Args:
            prompt: The input prompt
            **kwargs: Provider-specific options (temperature, max_tokens, etc.)

        Returns:
            Generated text response
        """
        pass

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Generate structured JSON from a prompt.

        Args:
            prompt: The input prompt requesting JSON output
            schema: Optional JSON schema for validation

        Returns:
            Parsed JSON response as dictionary
        """
        pass

    @abstractmethod
    async def warmup(self) -> None:
        """
        Warm up the model by making a simple call.
        This loads the model into memory for faster subsequent requests.
        """
        pass

    @abstractmethod
    def is_initialized(self) -> bool:
        """Check if the provider is initialized and ready."""
        pass
