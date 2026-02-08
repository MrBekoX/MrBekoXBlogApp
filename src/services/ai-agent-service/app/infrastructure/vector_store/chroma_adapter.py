"""Chroma vector store adapter - Concrete implementation of IVectorStore."""

import asyncio
import logging

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.domain.interfaces.i_vector_store import (
    IVectorStore,
    VectorChunk,
    TextChunk,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# Collection name for blog articles
COLLECTION_NAME = "blog_articles"


class ChromaAdapter(IVectorStore):
    """
    Chroma implementation of vector store.

    Features:
    - Persistent storage (survives restarts)
    - Metadata filtering by post_id
    - Cosine similarity search
    """

    def __init__(self, persist_directory: str | None = None):
        self._persist_dir = persist_directory or settings.chroma_persist_dir
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize Chroma client and collection."""
        if self._initialized:
            return

        logger.info(f"Initializing ChromaAdapter with persist_dir: {self._persist_dir}")

        # Create persistent client
        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=settings.debug
            )
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )

        self._initialized = True
        count = self._collection.count()
        logger.info(f"ChromaAdapter initialized. Collection '{COLLECTION_NAME}' has {count} documents")

    def _ensure_initialized(self) -> None:
        """Ensure store is initialized before use."""
        if not self._initialized:
            self.initialize()

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
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        if len(chunks) != len(embeddings):
            raise ValueError(f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) count mismatch")

        # Prepare data for Chroma
        ids = [f"{post_id}_{chunk.chunk_index}" for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [
            {
                "post_id": post_id,
                "chunk_index": chunk.chunk_index,
                "section_title": chunk.section_title or "",
            }
            for chunk in chunks
        ]

        # Upsert (add or update)
        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )

        logger.info(f"Added/updated {len(chunks)} chunks for post {post_id}")
        return len(chunks)

    def delete_post_chunks(self, post_id: str) -> int:
        """
        Delete all chunks for a specific post.

        Args:
            post_id: The post ID to delete chunks for

        Returns:
            Number of chunks deleted
        """
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        # Get count before deletion
        results = self._collection.get(
            where={"post_id": post_id},
            include=[]
        )
        count = len(results.get("ids", []))

        if count > 0:
            # Delete by metadata filter
            self._collection.delete(
                where={"post_id": post_id}
            )
            logger.info(f"Deleted {count} chunks for post {post_id}")

        return count

    def search(
        self,
        query_embedding: list[float],
        post_id: str | None = None,
        k: int = 5
    ) -> list[VectorChunk]:
        """
        Search for similar chunks.

        Args:
            query_embedding: Query embedding vector
            post_id: Optional post_id to filter results
            k: Number of results to return

        Returns:
            List of VectorChunk objects ordered by similarity
        """
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        # Build query parameters
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"]
        }

        # Add filter if post_id specified
        if post_id:
            query_params["where"] = {"post_id": post_id}

        results = self._collection.query(**query_params)

        # Parse results
        chunks: list[VectorChunk] = []

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}
            chunks.append(VectorChunk(
                id=doc_id,
                content=documents[i] if i < len(documents) else "",
                post_id=metadata.get("post_id", ""),
                chunk_index=metadata.get("chunk_index", 0),
                section_title=metadata.get("section_title") or None,
                distance=distances[i] if i < len(distances) else 0.0
            ))

        return chunks

    def get_post_chunks(self, post_id: str) -> list[VectorChunk]:
        """Get all chunks for a specific post."""
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        results = self._collection.get(
            where={"post_id": post_id},
            include=["documents", "metadatas"]
        )

        chunks: list[VectorChunk] = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}
            chunks.append(VectorChunk(
                id=doc_id,
                content=documents[i] if i < len(documents) else "",
                post_id=metadata.get("post_id", ""),
                chunk_index=metadata.get("chunk_index", 0),
                section_title=metadata.get("section_title") or None,
                distance=0.0
            ))

        # Sort by chunk_index
        chunks.sort(key=lambda c: c.chunk_index)
        return chunks

    def get_total_count(self) -> int:
        """Get total number of chunks in the store."""
        self._ensure_initialized()

        if not self._collection:
            return 0

        return self._collection.count()

    def reset(self) -> None:
        """Reset the collection (delete all data). Use with caution!"""
        self._ensure_initialized()

        if self._client and self._collection:
            self._client.delete_collection(COLLECTION_NAME)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            logger.warning("ChromaAdapter reset - all data deleted")

    # ==================== L3 Semantic Cache Methods ====================

    def search_queries(
        self,
        query_embedding: list[float],
        k: int = 1,
        threshold: float = 0.95
    ) -> list[dict]:
        """
        Search for similar cached queries (L3 Semantic Cache).

        Uses a separate collection for query caching.
        """
        self._ensure_initialized()

        if not self._client:
            return []

        try:
            # Get or create cached queries collection
            cached_queries_collection = self._client.get_or_create_collection(
                name="cached_queries",
                metadata={"hnsw:space": "cosine"}
            )

            # Search for similar queries
            results = cached_queries_collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"]
            )

            cached_results = []
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for i, doc_id in enumerate(ids):
                similarity = 1.0 - distances[i]  # Convert distance to similarity

                # Filter by threshold
                if similarity >= threshold:
                    metadata = metadatas[i] if i < len(metadatas) else {}
                    cached_results.append({
                        "query_id": doc_id,
                        "query_text": documents[i] if i < len(documents) else "",
                        "response": metadata.get("response"),
                        "similarity": similarity,
                        "cached_at": metadata.get("cached_at")
                    })

            if cached_results:
                logger.info(f"Found {len(cached_results)} cached queries (threshold={threshold})")

            return cached_results

        except Exception as e:
            logger.error(f"Error searching cached queries: {e}")
            return []

    def cache_query(
        self,
        query_text: str,
        query_embedding: list[float],
        response: any,
        metadata: dict | None = None
    ) -> None:
        """
        Cache a query and its response (L3 Semantic Cache).

        Stores in a separate 'cached_queries' collection.
        """
        self._ensure_initialized()

        if not self._client:
            logger.warning("Cannot cache query: client not initialized")
            return

        try:
            import time

            # Get or create cached queries collection
            cached_queries_collection = self._client.get_or_create_collection(
                name="cached_queries",
                metadata={"hnsw:space": "cosine"}
            )

            # Create unique ID for this query
            import hashlib
            query_hash = hashlib.sha256(query_text.encode()).hexdigest()
            query_id = f"cached_query_{query_hash}"

            # Prepare metadata with response and timestamp
            cache_metadata = {
                "response": response,
                "cached_at": int(time.time()),  # Unix timestamp
            }

            # Merge with additional metadata if provided
            if metadata:
                cache_metadata.update(metadata)

            # Store in cache collection
            cached_queries_collection.upsert(
                ids=[query_id],
                documents=[query_text],
                embeddings=[query_embedding],
                metadatas=[cache_metadata]
            )

            logger.debug(f"Cached query: {query_text[:50]}...")

        except Exception as e:
            logger.error(f"Error caching query: {e}")

    # ==================== Async Wrappers ====================

    async def add_chunks_async(
        self,
        post_id: str,
        chunks: list[TextChunk],
        embeddings: list[list[float]]
    ) -> int:
        """Async wrapper for add_chunks — runs in a thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self.add_chunks, post_id, chunks, embeddings)

    async def delete_post_chunks_async(self, post_id: str) -> int:
        """Async wrapper for delete_post_chunks."""
        return await asyncio.to_thread(self.delete_post_chunks, post_id)

    async def search_async(
        self,
        query_embedding: list[float],
        post_id: str | None = None,
        k: int = 5
    ) -> list[VectorChunk]:
        """Async wrapper for search."""
        return await asyncio.to_thread(self.search, query_embedding, post_id, k)

    async def get_post_chunks_async(self, post_id: str) -> list[VectorChunk]:
        """Async wrapper for get_post_chunks."""
        return await asyncio.to_thread(self.get_post_chunks, post_id)

    async def get_total_count_async(self) -> int:
        """Async wrapper for get_total_count."""
        return await asyncio.to_thread(self.get_total_count)

    async def search_queries_async(
        self,
        query_embedding: list[float],
        k: int = 1,
        threshold: float = 0.95
    ) -> list[dict]:
        """Async wrapper for search_queries."""
        return await asyncio.to_thread(self.search_queries, query_embedding, k, threshold)

    async def cache_query_async(
        self,
        query_text: str,
        query_embedding: list[float],
        response: any,
        metadata: dict | None = None
    ) -> None:
        """Async wrapper for cache_query."""
        await asyncio.to_thread(self.cache_query, query_text, query_embedding, response, metadata)
