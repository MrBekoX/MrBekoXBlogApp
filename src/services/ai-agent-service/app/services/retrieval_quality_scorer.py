"""Content quality scorer for RAG retrieval results."""

from dataclasses import dataclass
from typing import List
from app.domain.interfaces.i_vector_store import VectorChunk

@dataclass
class ScoredChunk:
    """A vector chunk with a computed quality score."""
    chunk: VectorChunk
    final_score: float

class RetrievalQualityScorer:
    """Scores RAG chunks based on relevance and content quality."""
    
    def __init__(self, alpha: float = 0.7, beta: float = 0.3):
        self.alpha = alpha # Weight for Similarity
        self.beta = beta   # Weight for Diversity/Other

    def score(self, query: str, chunks: List[VectorChunk]) -> List[ScoredChunk]:
        """
        Score and rank chunks.
        
        Formula: Final Score = (Similarity * Alpha) * Density Penalty
        """
        scored = []
        for chunk in chunks:
            # Base score = Cosine Similarity
            relevance = chunk.similarity_score
            
            # Penalize very short chunks (low information density)
            # Short chunks often lack sufficient context for the LLM
            density_penalty = 1.0
            content_len = len(chunk.content.strip())
            
            if content_len < 50:
                density_penalty = 0.5
            elif content_len < 100:
                density_penalty = 0.8
            
            # You could add more signals here (e.g. keyword match ratio)
            
            final_score = (relevance * self.alpha) * density_penalty
            
            scored.append(ScoredChunk(chunk, final_score))
            
        # Re-sort by final score descending
        return sorted(scored, key=lambda x: x.final_score, reverse=True)
