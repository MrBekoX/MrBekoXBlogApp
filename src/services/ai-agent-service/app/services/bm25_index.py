import logging
import threading

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


class BM25Index:
    """
    In-memory BM25 index for sparse retrieval.
    Warning: This stores indices in memory. For very large datasets, use Elasticsearch or Qdrant.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BM25Index, cls).__new__(cls)
            cls._instance._indices: dict[str, BM25Okapi] = {}
            cls._instance._lookups: dict[str, list[dict]] = {}
            cls._instance._initialized = True
        return cls._instance

    def initialize(self):
        """Re-initialize only if no data exists (guard against wiping indexed data)."""
        with self._lock:
            if self._initialized and self._indices:
                logger.debug("BM25Index already initialized with data, skipping re-init")
                return
            self._indices = {}
            self._lookups = {}
            self._initialized = True

    def index_document(self, post_id: str, chunks: list[dict]) -> None:
        """Create index for a document's chunks."""
        tokenized_corpus = [c['content'].lower().split() for c in chunks]

        with self._lock:
            self._indices[post_id] = BM25Okapi(tokenized_corpus)
            self._lookups[post_id] = chunks
        logger.info(f"Indexed {len(chunks)} chunks for post {post_id} in BM25")

    def search(self, query: str, post_id: str, k: int = 10) -> list[dict]:
        """Search specific post using BM25."""
        with self._lock:
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
                result = chunks[idx].copy()
                result['score'] = float(scores[idx])
                result['type'] = 'sparse'
                results.append(result)

        return results

    def remove_document(self, post_id: str) -> None:
        """Remove document from index."""
        with self._lock:
            self._indices.pop(post_id, None)
            self._lookups.pop(post_id, None)
