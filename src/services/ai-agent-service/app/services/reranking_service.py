import asyncio
import logging
import time
from sentence_transformers import CrossEncoder
from app.domain.interfaces.i_vector_store import VectorChunk

logger = logging.getLogger(__name__)


class RerankingService:
    """
    Reranks a list of retrieved chunks using a Cross-Encoder model.
    Passes full Query-Document pairs to the model for high-precision scoring.

    Supports both sync and async operation:
    - rerank(): synchronous (for backwards compatibility)
    - rerank_async(): async with to_thread for non-blocking
    """
    _model = None

    def __init__(self, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self._model_name = model_name
        self._initialized = False

    def initialize(self):
        if not RerankingService._model:
            logger.info(f"Loading Cross-Encoder model: {self._model_name}...")
            # Use CPU by default or CUDA if available (library handles it)
            RerankingService._model = CrossEncoder(self._model_name)
            
            # Warmup: trigger JIT compile with a dummy pair so first real request
            # doesn't hit the 15s tool timeout during cold start
            try:
                logger.info("[Rerank] Running warmup predict...")
                RerankingService._model.predict([["warmup query", "warmup document"]])
                logger.info("[Rerank] Warmup complete")
            except Exception as e:
                logger.warning(f"[Rerank] Warmup failed (non-fatal): {e}")
        self._initialized = True

    def rerank(self, query: str, chunks: list[VectorChunk], top_k: int = 5) -> list[VectorChunk]:
        """
        Rerank the given chunks based on relevance to the query (synchronous).

        Args:
            query: The search query
            chunks: List of chunks to rerank
            top_k: Number of top chunks to return

        Returns:
            Reranked list of chunks (top_k)
        """
        if not chunks:
            return []

        if not self._initialized:
            self.initialize()

        started_at = time.perf_counter()
        # Prepare pairs for the model: [[query, content], [query, content], ...]
        pairs = [[query, chunk.content] for chunk in chunks]

        try:
            # Predict scores (returns numpy array of scores)
            scores = RerankingService._model.predict(pairs)

            # Assign scores back to chunks (store in distance or a new field)
            # Cross-encoder scores are logits (unbounded), not 0-1.
            # Higher is better.

            reranked_chunks = []
            for i, chunk in enumerate(chunks):
                # Make a copy to avoid mutating original list structure externally
                reranked_chunks.append((chunk, float(scores[i])))

            # Sort by score descending
            reranked_chunks.sort(key=lambda x: x[1], reverse=True)

            # Select top K
            top_chunks = [chunk for chunk, _ in reranked_chunks[:top_k]]

            duration = time.perf_counter() - started_at
            logger.info(
                f"[Rerank] Reranked {len(chunks)} chunks in {duration:.3f}s, "
                f"returning top {len(top_chunks)}"
            )
            return top_chunks

        except Exception as e:
            logger.error(f"[Rerank] Error during re-ranking: {type(e).__name__}: {e}")
            # Fallback: return original chunks (truncated)
            return chunks[:top_k]

    async def rerank_async(
        self, query: str, chunks: list[VectorChunk], top_k: int = 5
    ) -> list[VectorChunk]:
        """
        Rerank the given chunks asynchronously using asyncio.to_thread.

        This is the preferred method for async code paths to avoid blocking
        the event loop during the compute-intensive reranking operation.

        Args:
            query: The search query
            chunks: List of chunks to rerank
            top_k: Number of top chunks to return

        Returns:
            Reranked list of chunks (top_k)
        """
        if not chunks:
            return []

        # Run the synchronous rerank in a thread pool
        return await asyncio.to_thread(self.rerank, query, chunks, top_k)
