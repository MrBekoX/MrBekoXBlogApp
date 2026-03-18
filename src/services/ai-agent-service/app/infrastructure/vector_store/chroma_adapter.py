"""Chroma vector store adapter - Concrete implementation of IVectorStore."""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.domain.interfaces.i_vector_store import (
    IVectorStore,
    VectorChunk,
    TextChunk,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# Collection names
COLLECTION_NAME = "blog_articles"
CACHED_QUERIES_COLLECTION_NAME = "cached_queries"


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

    def validate_dimensions(self, expected_dim: int) -> None:
        """Check stored embedding dimensions and recreate collection on mismatch.

        Must be called AFTER initialize().  If the collection already contains
        embeddings whose dimension differs from *expected_dim*, the collection
        is deleted and recreated so that new embeddings (from the current
        embedding model) can be stored without errors.

        This method also validates the cached_queries collection used for L3 semantic caching.
        """
        self._ensure_initialized()
        if not self._collection or not self._client:
            return

        # Validate main collection (blog_articles)
        self._validate_collection_dimensions(COLLECTION_NAME, expected_dim, is_main=True)

        # Validate cached queries collection (L3 semantic cache)
        self._validate_collection_dimensions(CACHED_QUERIES_COLLECTION_NAME, expected_dim, is_main=False)

    def _validate_collection_dimensions(self, collection_name: str, expected_dim: int, is_main: bool = False) -> None:
        """Validate dimensions for a specific collection and recreate if mismatch."""
        if not self._client:
            return

        try:
            collection = self._client.get_collection(name=collection_name)
        except Exception:
            # Collection doesn't exist, nothing to validate
            logger.debug(f"Collection '{collection_name}' does not exist, skipping dimension check")
            return

        count = collection.count()
        if count == 0:
            logger.info(f"ChromaDB collection '{collection_name}' is empty, no dimension check needed")
            return

        # Peek at one stored embedding to learn its dimension
        try:
            sample = collection.peek(limit=1)
            stored_embeddings = sample.get("embeddings")
            if stored_embeddings is None or len(stored_embeddings) == 0:
                return
            first_embedding = stored_embeddings[0]
            if first_embedding is None or len(first_embedding) == 0:
                return
            stored_dim = len(first_embedding)
        except Exception as e:
            logger.warning(f"Could not peek collection '{collection_name}' for dimension check: {e}")
            return

        if stored_dim == expected_dim:
            logger.info(f"ChromaDB dimension OK for '{collection_name}': stored={stored_dim}, expected={expected_dim}")
            return

        # Dimension mismatch → delete and recreate
        logger.warning(
            f"ChromaDB dimension MISMATCH for '{collection_name}': stored={stored_dim}, expected={expected_dim}. "
            f"Dropping collection ({count} docs) and recreating."
        )
        self._client.delete_collection(collection_name)

        if is_main:
            # Recreate main collection and update reference
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
        else:
            # Just recreate, will be lazy-loaded when needed
            self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )

        logger.info(f"ChromaDB collection '{collection_name}' recreated with clean state")

    def force_reset_all_collections(self, expected_dim: int) -> None:
        """Force reset all ChromaDB collections and optionally wipe data directory.

        This is a nuclear option for fixing persistent dimension mismatch issues.
        Called when CHROMA_FORCE_RESET=true is set.
        """
        self._ensure_initialized()
        if not self._client:
            return

        logger.warning(f"Force resetting all ChromaDB collections for {expected_dim}-dim embeddings")

        # List of all known collections
        collections_to_reset = [COLLECTION_NAME, CACHED_QUERIES_COLLECTION_NAME]

        for collection_name in collections_to_reset:
            try:
                self._client.delete_collection(collection_name)
                logger.info(f"Deleted collection '{collection_name}'")
            except Exception:
                pass  # Collection might not exist

        # Recreate main collection
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        logger.info(f"All ChromaDB collections reset. Ready for {expected_dim}-dim embeddings")

    def _ensure_initialized(self) -> None:
        """Ensure store is initialized before use."""
        if not self._initialized:
            self.initialize()

    @staticmethod
    def _normalize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if not metadata:
            return normalized

        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                normalized[key] = value
            else:
                normalized[key] = str(value)
        return normalized

    def _build_where_clause(
        self,
        post_id: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
        default_published_only: bool = False,
    ) -> dict[str, Any] | None:
        filters: list[dict[str, Any]] = []
        if post_id:
            filters.append({"post_id": post_id})

        normalized_filter = self._normalize_metadata(metadata_filter)
        if default_published_only and "visibility" not in normalized_filter:
            normalized_filter["visibility"] = "published"

        for key, value in normalized_filter.items():
            filters.append({key: value})

        if not filters:
            return None
        if len(filters) == 1:
            return filters[0]
        return {"$and": filters}

    def ensure_post_metadata(self, post_id: str, visibility: str, author_id: str | None) -> int:
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        results = self._collection.get(
            where={"post_id": post_id},
            include=["metadatas"]
        )
        ids = results.get("ids", [])
        metadatas = results.get("metadatas", [])
        if not ids:
            return 0

        desired_visibility = visibility or "published"
        desired_author_id = author_id or ""
        updated_metadatas: list[dict[str, Any]] = []
        has_changes = False

        for index, _ in enumerate(ids):
            current_metadata = dict(metadatas[index] if index < len(metadatas) and metadatas[index] else {})
            updated_metadata = dict(current_metadata)
            if updated_metadata.get("visibility") != desired_visibility:
                updated_metadata["visibility"] = desired_visibility
                has_changes = True
            if updated_metadata.get("author_id", "") != desired_author_id:
                updated_metadata["author_id"] = desired_author_id
                has_changes = True
            updated_metadatas.append(updated_metadata)

        if not has_changes:
            return 0

        update_method = getattr(self._collection, "update", None)
        if not callable(update_method):
            logger.warning("Chroma collection does not support metadata updates; post metadata backfill skipped")
            return 0

        update_method(ids=ids, metadatas=updated_metadatas)
        logger.info("Backfilled metadata for %s chunks of post %s", len(ids), post_id)
        return len(ids)

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

        ids = [f"{post_id}_{chunk.chunk_index}" for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = []
        for chunk in chunks:
            metadata = {
                "post_id": post_id,
                "chunk_index": chunk.chunk_index,
                "section_title": chunk.section_title or "",
            }
            metadata.update(self._normalize_metadata(chunk.metadata))
            metadatas.append(metadata)

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
        k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
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

        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"]
        }

        where_clause = self._build_where_clause(
            post_id=post_id,
            metadata_filter=metadata_filter,
            default_published_only=post_id is None,
        )
        if where_clause:
            query_params["where"] = where_clause

        query_dim = len(query_embedding)

        try:
            results = self._collection.query(**query_params)
        except Exception as e:
            error_msg = str(e)
            if "dimension" in error_msg.lower() or "InvalidArgumentError" in error_msg:
                logger.error(
                    f"ChromaDB dimension mismatch error: {e}. "
                    f"Query embedding has {query_dim} dimensions. "
                    f"Set CHROMA_FORCE_RESET=true to reset collections on startup."
                )
                raise RuntimeError(
                    f"ChromaDB embedding dimension mismatch. "
                    f"Query has {query_dim} dimensions but collection expects different. "
                    f"Set CHROMA_FORCE_RESET=true in environment to reset collections."
                ) from e
            raise

        chunks: list[VectorChunk] = []

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
            chunks.append(VectorChunk(
                id=doc_id,
                content=documents[i] if i < len(documents) else "",
                post_id=metadata.get("post_id", ""),
                chunk_index=metadata.get("chunk_index", 0),
                section_title=metadata.get("section_title") or None,
                distance=distances[i] if i < len(distances) else 0.0,
                metadata=dict(metadata),
            ))

        return chunks

    def get_post_chunks(
        self,
        post_id: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorChunk]:
        """Get all chunks for a specific post."""
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        where_clause = self._build_where_clause(post_id=post_id, metadata_filter=metadata_filter)
        results = self._collection.get(
            where=where_clause,
            include=["documents", "metadatas"]
        )

        chunks: list[VectorChunk] = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
            chunks.append(VectorChunk(
                id=doc_id,
                content=documents[i] if i < len(documents) else "",
                post_id=metadata.get("post_id", ""),
                chunk_index=metadata.get("chunk_index", 0),
                section_title=metadata.get("section_title") or None,
                distance=0.0,
                metadata=dict(metadata),
            ))

        chunks.sort(key=lambda c: c.chunk_index)
        return chunks

    def get_total_count(self) -> int:
        """Get total number of chunks in the store."""
        self._ensure_initialized()

        if not self._collection:
            return 0

        return self._collection.count()

    def get_all_post_ids(self) -> list[str]:
        """Get all unique post IDs stored in the vector store."""
        self._ensure_initialized()

        if not self._collection:
            return []

        results = self._collection.get(include=["metadatas"])
        metadatas = results.get("metadatas", [])
        post_ids = set()
        for meta in metadatas:
            if meta and meta.get("post_id"):
                post_ids.add(meta["post_id"])
        return list(post_ids)

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
        k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorChunk]:
        """Async wrapper for search."""
        return await asyncio.to_thread(self.search, query_embedding, post_id, k, metadata_filter)

    async def get_post_chunks_async(
        self,
        post_id: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorChunk]:
        """Async wrapper for get_post_chunks."""
        return await asyncio.to_thread(self.get_post_chunks, post_id, metadata_filter)

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

    # ==================== LTM/Episodic Memory Methods ====================

    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        embeddings: list[list[float]],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """Add documents to a named collection for LTM/Episodic memory."""
        self._ensure_initialized()
        if not self._client:
            raise RuntimeError("Client not initialized")

        collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

        if metadatas is None:
            metadatas = [{} for _ in documents]

        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )
        logger.info(f"Added {len(documents)} documents to collection '{collection_name}'")
        return len(documents)

    def query(
        self,
        collection_name: str,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Query a named collection for similar documents."""
        self._ensure_initialized()
        if not self._client:
            return None

        try:
            collection = self._client.get_collection(name=collection_name)
        except Exception:
            return None

        query_params: dict[str, Any] = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"]
        }
        if where:
            query_params["where"] = where

        return collection.query(**query_params)

