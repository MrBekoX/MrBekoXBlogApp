"""Ollama embedding adapter - Concrete implementation of IEmbeddingProvider."""

import asyncio
import logging

import httpx

from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

# Known embedding model dimensions
MODEL_DIMENSIONS = {
    "nomic-embed-text": 768,
    "bge-m3": 1024,
    "bge-large": 1024,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "multilingual": 768,
}


def get_model_dimensions(model_name: str) -> int:
    """Get embedding dimensions for a model, default to 1024."""
    base_name = model_name.split(":")[0] if ":" in model_name else model_name
    return MODEL_DIMENSIONS.get(base_name, 1024)


class OllamaEmbeddingAdapter(IEmbeddingProvider):
    """
    Ollama implementation of embedding provider.

    Configured via OLLAMA_EMBEDDING_MODEL in .env
    Default: nomic-embed-text (768 dimensions, multilingual)

    Includes retry with exponential backoff and a concurrency semaphore
    to prevent overloading the Ollama instance.
    """

    _MAX_RETRIES = 3
    _RETRY_BACKOFF_BASE = 1.0  # seconds: 1, 2, 4
    _MAX_CONCURRENT_REQUESTS = 3  # shared semaphore across all embed calls

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None
    ):
        self._base_url = base_url or settings.ollama_base_url
        self._model = model or settings.ollama_embedding_model
        self._dimensions = get_model_dimensions(self._model)
        self._initialized = False
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_REQUESTS)

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
        logger.info(f"OllamaEmbeddingAdapter initialized with {self._model} ({self._dimensions} dimensions)")

    async def warmup(self) -> None:
        """
        Warm up the embedding model by generating a test embedding.

        This keeps the model loaded in GPU memory and prevents cold start delays.
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Use a short test prompt to warm up the model
            test_prompt = "warmup"
            logger.info(f"Warming up embedding model {self._model}...")
            embedding = await self.embed(test_prompt)
            logger.info(f"Embedding model warmed up successfully, embedding_dim={len(embedding)}")
        except Exception as e:
            logger.warning(f"Embedding model warmup failed (will load on first request): {e}")

    async def shutdown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    async def embed(self, text: str) -> list[float]:
        """
        Generate embedding for a single text with retry and backpressure.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff on
        transient HTTP errors (5xx, timeouts). A semaphore limits the
        number of concurrent requests to avoid overloading Ollama.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        if not self._initialized:
            await self.initialize()

        if not self._client:
            raise RuntimeError("EmbeddingAdapter not properly initialized")

        last_error: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                async with self._semaphore:
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

            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                is_retryable = isinstance(e, (httpx.TimeoutException, httpx.ConnectError)) or (
                    isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500
                )
                if is_retryable and attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        f"Embedding request failed (attempt {attempt}/{self._MAX_RETRIES}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    f"Embedding request failed after {attempt} attempt(s): {e}"
                )
                raise

            except Exception as e:
                logger.error(f"Error generating embedding: {e}")
                raise

        # Should not reach here, but just in case
        raise last_error or RuntimeError("Embedding failed after retries")

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
        return self._dimensions

    def is_initialized(self) -> bool:
        """Return initialization state for readiness checks."""
        return self._initialized
