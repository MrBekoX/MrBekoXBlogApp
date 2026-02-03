import logging
from sentence_transformers import CrossEncoder
from app.domain.interfaces.i_vector_store import VectorChunk

logger = logging.getLogger(__name__)

class RerankingService:
    """
    Reranks a list of retrieved chunks using a Cross-Encoder model.
    Passes full Query-Document pairs to the model for high-precision scoring.
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
        self._initialized = True

    def rerank(self, query: str, chunks: list[VectorChunk], top_k: int = 5) -> list[VectorChunk]:
        """
        Rerank the given chunks based on relevance to the query.
        """
        if not chunks:
            return []
            
        if not self._initialized:
            self.initialize()

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
                # We can store the raw score in a temporary attribute if needed,
                # or update the similarity score (if we normalize it).
                # For now, let's just sort them.
                
                # Make a copy to avoid mutating original list structure externally
                # (though objects are references)
                reranked_chunks.append((chunk, float(scores[i])))
                
            # Sort by score descending
            reranked_chunks.sort(key=lambda x: x[1], reverse=True)
            
            # Select top K
            top_chunks = []
            for chunk, score in reranked_chunks[:top_k]:
                # Optionally update the similarity score to reflect the high confidence
                # But be careful as this invalidates the original vector distance.
                # Let's trust the re-rank order.
                top_chunks.append(chunk)
                
            logger.info(f"Reranked {len(chunks)} chunks, returning top {len(top_chunks)}")
            return top_chunks

        except Exception as e:
            logger.error(f"Error during re-ranking: {e}")
            # Fallback: return original chunks (truncated)
            return chunks[:top_k]
