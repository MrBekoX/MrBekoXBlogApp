import re
import logging
import numpy as np
from sentence_transformers import SentenceTransformer
from app.domain.interfaces.i_vector_store import TextChunk

logger = logging.getLogger(__name__)

class SemanticChunker:
    """
    Splits text into chunks based on semantic similarity of sentences.
    Uses generic 'all-MiniLM-L6-v2' model for sentence embeddings (fast & efficient).
    """
    _model = None

    def __init__(self, model_name="all-MiniLM-L6-v2", threshold_percentile=90, min_chunk_size=100):
        self._model_name = model_name
        self._threshold_percentile = threshold_percentile
        self._min_chunk_size = min_chunk_size # Avoid creating tiny chunks
        self._initialized = False

    def initialize(self):
        if not SemanticChunker._model:
            logger.info(f"Loading Semantic Chunking model: {self._model_name}...")
            SemanticChunker._model = SentenceTransformer(self._model_name)
        self._initialized = True

    def chunk(self, text: str) -> list[TextChunk]:
        """
        Split text into semantic chunks.
        """
        if not self._initialized:
            self.initialize()

        if not text.strip():
            return []

        # 1. Split into sentences (simple regex for MVP)
        # Look for punctuation followed by space
        sentences = re.split(r'(?<=[.?!])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return []
            
        if len(sentences) == 1:
             return [TextChunk(content=sentences[0], chunk_index=0, section_title=None)]

        # 2. Compute embeddings for sentences
        embeddings = SemanticChunker._model.encode(sentences)
        
        # 3. Calculate cosine distances between adjacent sentences
        distances = []
        for i in range(len(embeddings) - 1):
            # Cosine Sim = dot(A, B) / (norm(A) * norm(B))
            # Distance = 1 - Similarity
            sim = np.dot(embeddings[i], embeddings[i+1]) / (
                np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[i+1])
            )
            distances.append(1 - sim)
            
        # 4. Determine Threshold
        # We look for "peaks" in distance (valleys in similarity)
        # Higher distance = Topic change
        threshold = np.percentile(distances, self._threshold_percentile)
        logger.debug(f"Semantic split threshold: {threshold:.4f}")
        
        # 5. Group sentences into chunks
        chunks: list[TextChunk] = []
        current_sentences = [sentences[0]]
        chunk_index = 0
        
        for i, dist in enumerate(distances):
            # If distance is high (topic changed) AND we have enough content
            current_len = sum(len(s) for s in current_sentences)
            
            if dist > threshold and current_len >= self._min_chunk_size:
                # Create chunk
                content = " ".join(current_sentences)
                chunks.append(TextChunk(
                    content=content,
                    chunk_index=chunk_index,
                    section_title=None # TODO: Extract topic/title?
                ))
                chunk_index += 1
                current_sentences = [sentences[i+1]]
            else:
                current_sentences.append(sentences[i+1])
                
        # Append last chunk
        if current_sentences:
            content = " ".join(current_sentences)
            chunks.append(TextChunk(
                content=content,
                chunk_index=chunk_index,
                section_title=None
            ))
            
        return chunks
