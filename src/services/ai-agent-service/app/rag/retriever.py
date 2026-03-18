"""RAG retriever for semantic search over article chunks."""

import logging
from dataclasses import dataclass
from typing import Optional

from app.rag.embeddings import EmbeddingService
from app.infrastructure.vector_store.chroma_adapter import ChromaAdapter
from app.domain.interfaces.i_vector_store import VectorChunk, IVectorStore

# Backward-compatible aliases
VectorStore = IVectorStore
StoredChunk = VectorChunk


logger = logging.getLogger(__name__)

# Default retrieval parameters
DEFAULT_TOP_K = 5
MIN_SIMILARITY_THRESHOLD = 0.3  # Filter out chunks with low relevance


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""

    chunks: list[StoredChunk]
    query: str
    post_id: Optional[str]

    @property
    def context(self) -> str:
        """Get concatenated context from all chunks."""
        return "\n\n---\n\n".join(
            chunk.content for chunk in self.chunks
        )

    @property
    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.chunks) > 0


class Retriever:
    """
    Semantic retriever for RAG.

    Combines embedding service and vector store to provide
    semantic search over article chunks.
    """

    def __init__(
        self,
        embedding_svc: EmbeddingService,
        store: VectorStore
    ):
        self._embedding_service = embedding_svc
        self._vector_store = store
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize underlying services."""
        if self._initialized:
            return

        await self._embedding_service.initialize()
        self._vector_store.initialize()
        self._initialized = True
        logger.info("Retriever initialized")

    async def retrieve(
        self,
        query: str,
        post_id: Optional[str] = None,
        k: int = DEFAULT_TOP_K,
        min_similarity: float = MIN_SIMILARITY_THRESHOLD
    ) -> RetrievalResult:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: The search query
            post_id: Optional post_id to limit search scope
            k: Number of chunks to retrieve
            min_similarity: Minimum similarity threshold (0-1)

        Returns:
            RetrievalResult containing relevant chunks
        """
        if not self._initialized:
            await self.initialize()

        # Generate query embedding
        query_embedding = await self._embedding_service.embed(query)

        # Search vector store
        chunks = self._vector_store.search(
            query_embedding=query_embedding,
            post_id=post_id,
            k=k
        )

        # Filter by similarity threshold
        filtered_chunks = [
            chunk for chunk in chunks
            if chunk.similarity_score >= min_similarity
        ]

        # PII filtering hook — redact sensitive data from retrieved content
        try:
            from app.security.data_classifier import DataClassifier
            _classifier = DataClassifier()
            safe_chunks = []
            for chunk in filtered_chunks:
                result = _classifier.classify_and_redact(chunk.content)
                if result.pii_entities:
                    safe_chunks.append(StoredChunk(
                        content=result.anonymized_text,
                        post_id=chunk.post_id,
                        chunk_index=chunk.chunk_index,
                        similarity_score=chunk.similarity_score,
                        metadata=chunk.metadata,
                    ))
                else:
                    safe_chunks.append(chunk)
            filtered_chunks = safe_chunks
        except Exception:
            pass  # Fail-open: don't break retrieval if classifier has an issue

        logger.debug(
            f"Retrieved {len(filtered_chunks)}/{len(chunks)} chunks for query: "
            f"{query[:50]}... (post_id={post_id})"
        )

        return RetrievalResult(
            chunks=filtered_chunks,
            query=query,
            post_id=post_id
        )

    async def retrieve_with_context(
        self,
        query: str,
        post_id: str,
        k: int = DEFAULT_TOP_K,
        include_neighbors: bool = True
    ) -> RetrievalResult:
        """
        Retrieve chunks with additional context from neighboring chunks.

        This provides more coherent context by including chunks
        adjacent to the most relevant ones.

        Args:
            query: The search query
            post_id: Post ID to search within
            k: Number of primary chunks to retrieve
            include_neighbors: Whether to include neighboring chunks

        Returns:
            RetrievalResult with expanded context
        """
        # Get primary results
        result = await self.retrieve(query, post_id, k)

        if not result.has_results or not include_neighbors:
            return result

        # Get all chunks for the post to find neighbors
        all_chunks = self._vector_store.get_post_chunks(post_id)
        chunk_map = {chunk.chunk_index: chunk for chunk in all_chunks}

        # Expand results with neighbors
        expanded_indices: set[int] = set()
        for chunk in result.chunks:
            expanded_indices.add(chunk.chunk_index)
            # Add previous and next chunk indices
            if chunk.chunk_index - 1 in chunk_map:
                expanded_indices.add(chunk.chunk_index - 1)
            if chunk.chunk_index + 1 in chunk_map:
                expanded_indices.add(chunk.chunk_index + 1)

        # Build expanded chunk list, maintaining order
        expanded_chunks = [
            chunk_map[idx]
            for idx in sorted(expanded_indices)
            if idx in chunk_map
        ]

        return RetrievalResult(
            chunks=expanded_chunks,
            query=query,
            post_id=post_id
        )



