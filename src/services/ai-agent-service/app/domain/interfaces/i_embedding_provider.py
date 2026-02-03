"""Embedding Provider interface - Contract for text embedding services."""

from abc import ABC, abstractmethod


class IEmbeddingProvider(ABC):
    """
    Abstract interface for embedding providers.

    Implementations can be Ollama, OpenAI Embeddings, HuggingFace, etc.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the embedding service."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the embedding service."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimensions."""
        pass
