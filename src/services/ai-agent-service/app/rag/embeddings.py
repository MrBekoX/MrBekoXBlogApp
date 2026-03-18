"""Ollama embedding service using configurable embedding model."""

import logging
from typing import Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Known embedding model dimensions
MODEL_DIMENSIONS = {
    "bge-m3": 1024,
    "bge-large": 1024,
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
}


def get_model_dimensions(model_name: str) -> int:
    """Get embedding dimensions for a model, default to 1024."""
    # Extract base model name (without tag)
    base_name = model_name.split(":")[0] if ":" in model_name else model_name
    return MODEL_DIMENSIONS.get(base_name, 1024)


class EmbeddingService:
    """
    Embedding service using Ollama's embedding models.

    Configured via OLLAMA_EMBEDDING_MODEL in .env
    Default: nomic-embed-text (768 dimensions, multilingual)
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self._base_url = base_url or settings.ollama_base_url
        self._model = model or settings.ollama_embedding_model
        self._dimensions = get_model_dimensions(self._model)
        self._initialized = False
        self._client: Optional[httpx.AsyncClient] = None

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
        logger.info(f"EmbeddingService initialized with {self._model} ({self._dimensions} dimensions)")

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
            List of floats representing the embedding vector
        """
        if not self._initialized:
            await self.initialize()

        if not self._client:
            raise RuntimeError("EmbeddingService not properly initialized")

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
        For production, consider using a batching strategy or parallel requests.

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
        return self._dimensions



