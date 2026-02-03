"""Ollama embedding adapter - Concrete implementation of IEmbeddingProvider."""

import logging

import httpx

from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

# Embedding model configuration
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIMENSIONS = 768


class OllamaEmbeddingAdapter(IEmbeddingProvider):
    """
    Ollama implementation of embedding provider using nomic-embed-text model.

    Features:
    - 768 dimensions
    - Multilingual support (TR/EN)
    - Optimized for semantic search
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None
    ):
        self._base_url = base_url or settings.ollama_base_url
        self._model = model or settings.ollama_embedding_model or EMBEDDING_MODEL
        self._initialized = False
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize the embedding service and verify model availability."""
        if self._initialized:
            return

        self._client = httpx.AsyncClient(timeout=60.0)

        # Verify model is available
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]

                if not any(self._model in name for name in model_names):
                    logger.warning(
                        f"Model {self._model} not found. Available: {model_names}. "
                        f"Run: ollama pull {self._model}"
                    )
                else:
                    logger.info(f"Embedding model {self._model} is available")
        except Exception as e:
            logger.warning(f"Could not verify embedding model availability: {e}")

        self._initialized = True
        logger.info(f"OllamaEmbeddingAdapter initialized with {self._model}")

    async def shutdown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    async def embed(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats (768 dimensions)
        """
        if not self._initialized:
            await self.initialize()

        if not self._client:
            raise RuntimeError("EmbeddingAdapter not properly initialized")

        try:
            response = await self._client.post(
                f"{self._base_url}/api/embeddings",
                json={
                    "model": self._model,
                    "prompt": text
                }
            )
            response.raise_for_status()

            data = response.json()
            embedding = data.get("embedding", [])

            if not embedding:
                raise ValueError("Empty embedding returned from Ollama")

            return embedding

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error generating embedding: {e}")
            raise
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Note: Ollama doesn't have native batch embedding, so we process sequentially.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        embeddings = []
        for text in texts:
            embedding = await self.embed(text)
            embeddings.append(embedding)
        return embeddings

    @property
    def dimensions(self) -> int:
        """Return the embedding dimensions."""
        return EMBEDDING_DIMENSIONS
