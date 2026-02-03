import logging
import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

class BM25Index:
    """
    In-memory BM25 index for sparse retrieval.
    Warning: This stores indices in memory. For very large datasets, use Elasticsearch or Qdrant.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BM25Index, cls).__new__(cls)
            cls._instance.initialize()
        return cls._instance

    def initialize(self):
        self._indices: dict[str, BM25Okapi] = {}  # post_id -> BM25
        self._lookups: dict[str, list[dict]] = {} # post_id -> list of chunks
        self._initialized = True

    def index_document(self, post_id: str, chunks: list[dict]) -> None:
        """Create index for a document's chunks."""
        # Simple tokenization: lowercase and split by whitespace
        # Production improvement: use a proper tokenizer (like nltk or tiktoken)
        tokenized_corpus = [c['content'].lower().split() for c in chunks]
        
        self._indices[post_id] = BM25Okapi(tokenized_corpus)
        self._lookups[post_id] = chunks
        logger.info(f"Indexed {len(chunks)} chunks for post {post_id} in BM25")

    def search(self, query: str, post_id: str, k: int = 10) -> list[dict]:
        """Search specific post using BM25."""
        if post_id not in self._indices:
            logger.warning(f"No BM25 index found for post {post_id}")
            return []
            
        bm25 = self._indices[post_id]
        chunks = self._lookups[post_id]
        
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)
        
        # Get top-k indices
        top_n = np.argsort(scores)[::-1][:k]
        
        results = []
        for idx in top_n:
            if scores[idx] > 0:
                result = chunks[idx].copy() # Copy to avoid mutating original
                result['score'] = float(scores[idx])
                result['type'] = 'sparse'
                results.append(result)
                
        return results

    def remove_document(self, post_id: str) -> None:
        """Remove document from index."""
        if post_id in self._indices:
            del self._indices[post_id]
        if post_id in self._lookups:
            del self._lookups[post_id]
