"""Chroma vector store for article embeddings."""

import logging
from dataclasses import dataclass
from typing import Optional, Any
import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.rag.chunker import TextChunk

logger = logging.getLogger(__name__)

# Collection name for blog articles
COLLECTION_NAME = "blog_articles"
QUERY_COLLECTION_NAME = "cached_queries"


@dataclass
class StoredChunk:
    """A chunk retrieved from the vector store."""

    id: str
    content: str
    post_id: str
    chunk_index: int
    section_title: Optional[str] = None
    distance: float = 0.0  # Similarity distance (lower is better)

    @property
    def similarity_score(self) -> float:
        """Convert distance to similarity score (0-1, higher is better)."""
        # Chroma uses L2 distance by default, convert to similarity
        return 1.0 / (1.0 + self.distance)


class VectorStore:
    """
    Chroma-based vector store for article chunks.

    Features:
    - Persistent storage (survives restarts)
    - Metadata filtering by post_id
    - Similarity search with top-k retrieval
    """

    def __init__(self, persist_directory: Optional[str] = None):
        self._persist_dir = persist_directory or settings.chroma_persist_dir
        self._client: Optional[chromadb.ClientAPI] = None
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection: Optional[chromadb.Collection] = None
        self._query_collection: Optional[chromadb.Collection] = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize Chroma client and collection."""
        if self._initialized:
            return

        logger.info(f"Initializing VectorStore with persist_dir: {self._persist_dir}")

        # Create persistent client
        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )

        self._query_collection = self._client.get_or_create_collection(
            name=QUERY_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        self._initialized = True
        count = self._collection.count()
        logger.info(f"VectorStore initialized. Collection '{COLLECTION_NAME}' has {count} documents")

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
            Number of chunks deleted (approximate)
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
        post_id: Optional[str] = None,
        k: int = 5
    ) -> list[StoredChunk]:
        """
        Search for similar chunks.

        Args:
            query_embedding: Query embedding vector
            post_id: Optional post_id to filter results
            k: Number of results to return

        Returns:
            List of StoredChunk objects ordered by similarity
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
        chunks: list[StoredChunk] = []

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}
            chunks.append(StoredChunk(
                id=doc_id,
                content=documents[i] if i < len(documents) else "",
                post_id=metadata.get("post_id", ""),
                chunk_index=metadata.get("chunk_index", 0),
                section_title=metadata.get("section_title") or None,
                distance=distances[i] if i < len(distances) else 0.0
            ))

        return chunks

    def get_post_chunks(self, post_id: str) -> list[StoredChunk]:
        """
        Get all chunks for a specific post.

        Args:
            post_id: The post ID

        Returns:
            List of StoredChunk objects
        """
        self._ensure_initialized()

        if not self._collection:
            raise RuntimeError("Collection not initialized")

        results = self._collection.get(
            where={"post_id": post_id},
            include=["documents", "metadatas"]
        )

        chunks: list[StoredChunk] = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}
            chunks.append(StoredChunk(
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
        """Get total number of chunks in the collection."""
        self._ensure_initialized()

        if not self._collection:
            return 0

        return self._collection.count()

    def reset(self) -> None:
        """Reset the collection (delete all data). Use with caution!"""
        self._ensure_initialized()

        if self._client:
            self._client.delete_collection(COLLECTION_NAME)
            self._client.delete_collection(QUERY_COLLECTION_NAME)
            
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            self._query_collection = self._client.get_or_create_collection(
                name=QUERY_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            logger.warning("VectorStore reset - all data deleted")

    def search_queries(
        self,
        query_embedding: list[float],
        k: int = 1,
        threshold: float = 0.95
    ) -> list[dict]:
        """Search for similar cached queries."""
        self._ensure_initialized()
        
        if not self._query_collection:
            return []
            
        # ChromaDB query
        results = self._query_collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"]
        )
        
        matches = []
        if not results['ids'] or not results['ids'][0]:
            return matches
            
        distances = results['distances'][0]
        metadatas = results['metadatas'][0]
        documents = results['documents'][0]
        
        for i, dist in enumerate(distances):
            # Convert l2/cosine distance to similarity
            # If using cosine distance in Chroma: range 0 (exact) to 2 (opposite)
            # Similarity = 1 - distance (approx) or 1 / (1 + distance)
            # Code base uses 1.0 / (1.0 + self.distance) in StoredChunk
            similarity = 1.0 / (1.0 + dist)
            
            if similarity >= threshold:
                import json
                try:
                    meta = metadatas[i]
                    response_json = meta.get("response_json", "{}")
                    response = json.loads(response_json)
                    
                    matches.append({
                        "query": documents[i],
                        "response": response,
                        "similarity": similarity,
                        "metadata": meta
                    })
                except Exception as e:
                    logger.error(f"Failed to parse cached query response: {e}")
                    
        return matches

    def cache_query(
        self,
        query_text: str,
        query_embedding: list[float],
        response: Any,
        metadata: dict | None = None
    ) -> None:
        """Cache a query response."""
        self._ensure_initialized()
        
        if not self._query_collection:
            return
            
        import hashlib
        import json
        import time
        
        # Create ID based on query hash
        query_hash = hashlib.md5(query_text.encode()).hexdigest()
        
        # Prepare metadata
        meta = metadata or {}
        meta["timestamp"] = time.time()
        try:
            # Serialize response to store in metadata
            meta["response_json"] = json.dumps(response)
        except Exception as e:
            logger.error(f"Failed to serialize response for caching: {e}")
            return
            
        self._query_collection.upsert(
            ids=[query_hash],
            documents=[query_text],
            embeddings=[query_embedding],
            metadatas=[meta]
        )
        logger.debug(f"Cached query: {query_text[:50]}...")


# Global singleton instance
vector_store = VectorStore()
