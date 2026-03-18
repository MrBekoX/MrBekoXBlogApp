"""Vector Store interface - Contract for vector database operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class VectorChunk:
    """A chunk stored in or retrieved from the vector store."""

    id: str
    content: str
    post_id: str
    chunk_index: int
    section_title: str | None = None
    distance: float = 0.0
    metadata: dict[str, Any] | None = None

    @property
    def similarity_score(self) -> float:
        """Convert distance to similarity score (0-1, higher is better).
        Assumes Cosine Distance (0=identical, 1=orthogonal, 2=opposite).
        """
        return max(0.0, 1.0 - self.distance)


@dataclass
class TextChunk:
    """A chunk of text to be stored."""

    content: str
    chunk_index: int
    section_title: str | None = None
    metadata: dict[str, Any] | None = None


class IVectorStore(ABC):
    """
    Abstract interface for vector store operations.

    Implementations can be Chroma, Pinecone, Weaviate, etc.
    """

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the vector store connection."""
        pass

    @abstractmethod
    def add_chunks(
        self,
        post_id: str,
        chunks: list[TextChunk],
        embeddings: list[list[float]]
    ) -> int:
        """
        Add chunks with embeddings to the vector store.

        Args:
            post_id: The post ID these chunks belong to
            chunks: List of TextChunk objects
            embeddings: Corresponding embedding vectors

        Returns:
            Number of chunks added
        """
        pass

    @abstractmethod
    def delete_post_chunks(self, post_id: str) -> int:
        """
        Delete all chunks for a specific post.

        Args:
            post_id: The post ID to delete chunks for

        Returns:
            Number of chunks deleted
        """
        pass

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        post_id: str | None = None,
        k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorChunk]:
        """
        Search for similar chunks.

        Args:
            query_embedding: Query embedding vector
            post_id: Optional post_id to filter results
            k: Number of results to return
            metadata_filter: Optional metadata filter to enforce ACL/visibility

        Returns:
            List of VectorChunk objects ordered by similarity
        """
        pass

    @abstractmethod
    def get_post_chunks(
        self,
        post_id: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorChunk]:
        """Get all chunks for a specific post."""
        pass

    @abstractmethod
    def get_total_count(self) -> int:
        """Get total number of chunks in the store."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the store (delete all data). Use with caution!"""
        pass

    @abstractmethod
    def search_queries(
        self,
        query_embedding: list[float],
        k: int = 1,
        threshold: float = 0.95
    ) -> list[dict]:
        """
        Search for similar cached queries.

        Args:
            query_embedding: Embedding of the new query
            k: Number of results
            threshold: Similarity threshold (0-1) to consider a match

        Returns:
            List of cached query results (dict with 'response', 'similarity', etc.)
        """
        pass

    @abstractmethod
    def cache_query(
        self,
        query_text: str,
        query_embedding: list[float],
        response: Any,
        metadata: dict | None = None
    ) -> None:
        """
        Cache a query and its response.

        Args:
            query_text: Original query text
            query_embedding: Embedding vector
            response: Response to cache
            metadata: Additional metadata
        """
        pass

    @abstractmethod
    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        embeddings: list[list[float]],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """
        Add documents to a named collection for LTM/Episodic memory.

        Args:
            collection_name: Name of the collection to add to
            documents: List of document texts
            embeddings: Corresponding embedding vectors
            ids: Unique IDs for each document
            metadatas: Optional metadata for each document

        Returns:
            Number of documents added
        """
        pass

    @abstractmethod
    def query(
        self,
        collection_name: str,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Query a named collection for similar documents.

        Args:
            collection_name: Name of the collection to query
            query_embeddings: Query embedding vectors
            n_results: Number of results to return
            where: Optional metadata filter

        Returns:
            Query results dict or None if collection doesn't exist
        """
        pass
