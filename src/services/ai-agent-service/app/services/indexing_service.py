"""Indexing service - Article indexing for RAG."""

import logging
import re
from dataclasses import dataclass

from app.domain.interfaces.i_vector_store import IVectorStore, TextChunk
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.services.content_cleaner import ContentCleanerService
from app.services.bm25_index import BM25Index
from app.services.semantic_chunker import SemanticChunker

logger = logging.getLogger(__name__)

# Chunking parameters
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


@dataclass
class IndexingResult:
    """Result of article indexing."""

    post_id: str
    title: str | None
    chunks_created: int
    chunks_deleted: int
    content_length: int
    status: str


class AdaptiveChunker:
    """
    Adaptive chunking strategy based on content type.
    
    Strategies:
    1. Code Blocks: Detected by ```...``` are kept as single chunks (priority).
    2. Headers: H1-H6 headers define section boundaries.
    3. Paragraphs: Split by double newlines.
    4. Lists: List items are kept together if possible.
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    ):
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> list[TextChunk]:
        """
        Split text into semantic chunks.
        """
        if not text.strip():
            return []

        chunks: list[TextChunk] = []
        
        # 1. Split by Code Blocks first (preserve them)
        # Regex captures delimiters to keep them in the parts
        # Non-greedy matching for content inside backticks
        parts = re.split(r'(```[\s\S]*?```)', text)
        
        current_chunk_index = 0
        
        for part in parts:
            if not part.strip():
                continue
                
            if part.startswith('```'):
                # It's a code block - keep it whole
                # Extract language for metadata if needed (not used in current TextChunk)
                chunks.append(TextChunk(
                    content=part.strip(),
                    chunk_index=current_chunk_index,
                    section_title="Code Block" # Generic title for now
                ))
                current_chunk_index += 1
            else:
                # Regular text content - apply semantic splitting
                text_chunks = self._chunk_text_content(part, current_chunk_index)
                chunks.extend(text_chunks)
                current_chunk_index += len(text_chunks)
                
        return chunks

    def _chunk_text_content(self, text: str, start_index: int) -> list[TextChunk]:
        """Chunk regular text based on headers and paragraphs."""
        chunks: list[TextChunk] = []
        current_index = start_index
        
        # Split by headers (H1-H6)
        # Capture the header itself to use as section title
        sections = re.split(r'(^#+\s+.+$)', text, flags=re.MULTILINE)
        
        current_section_title = None
        current_buffer = ""
        
        for section in sections:
            if not section.strip():
                continue
                
            # Check if it's a header
            if re.match(r'^#+\s+', section):
                current_section_title = section.strip().lstrip('#').strip()
                # If we have a buffer, flush it before changing section context
                # (Optional: decide if headers should break chunks hard or soft)
                # For now, we continue accumulating unless size limit hit, 
                # but update the section title for *subsequent* chunks.
                continue
            
            # Process paragraphs within the section
            paragraphs = section.split('\n\n')
            
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                
                # Check soft limit
                if len(current_buffer) + len(para) > self._chunk_size and current_buffer:
                    chunks.append(TextChunk(
                        content=current_buffer.strip(),
                        chunk_index=current_index,
                        section_title=current_section_title
                    ))
                    current_index += 1
                    
                    # Handle overlap
                    words = current_buffer.split()
                    overlap_words = words[-self._chunk_overlap:] if len(words) > self._chunk_overlap else words
                    current_buffer = " ".join(overlap_words) + " " if overlap_words else ""
                
                current_buffer += para + "\n\n"
        
        # Flush remaining buffer
        if current_buffer.strip():
            chunks.append(TextChunk(
                content=current_buffer.strip(),
                chunk_index=current_index,
                section_title=current_section_title
            ))
            
        return chunks


class IndexingService:
    """
    Service for indexing articles into vector store.

    Single Responsibility: Article chunking and indexing.
    """

    def __init__(
        self,
        embedding_provider: IEmbeddingProvider,
        vector_store: IVectorStore,
        chunker: SemanticChunker | AdaptiveChunker | None = None,
        bm25_index: BM25Index | None = None
    ):
        self._embedding = embedding_provider
        self._vector_store = vector_store
        # Default to SemanticChunker if not provided, fallback to Adaptive if Semantic fails to init
        # For now, default to SemanticChunker
        self._chunker = chunker or SemanticChunker()
        self._cleaner = ContentCleanerService()
        self._bm25 = bm25_index or BM25Index()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the indexing service."""
        if self._initialized:
            return

        await self._embedding.initialize()
        self._vector_store.initialize()
        self._bm25.initialize()
        self._initialized = True
        logger.info("IndexingService initialized")

    async def index_article(
        self,
        post_id: str,
        title: str,
        content: str,
        delete_existing: bool = True
    ) -> IndexingResult:
        """
        Index an article for RAG retrieval.

        Args:
            post_id: Unique article identifier
            title: Article title
            content: Article content
            delete_existing: Whether to delete existing chunks first
        
        Returns:
            IndexingResult with statistics
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"Indexing article {post_id}: {title[:50]}...")

        # Delete existing chunks if requested
        deleted_count = 0
        if delete_existing:
            deleted_count = self._vector_store.delete_post_chunks(post_id)
            self._bm25.remove_document(post_id)
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} existing chunks")

        # Prepare content
        full_content = f"# {title}\n\n{content}"
        cleaned = self._cleaner.clean_for_rag(full_content)

        if not cleaned.strip():
            logger.warning(f"Article {post_id} has no content after cleaning")
            return IndexingResult(
                post_id=post_id,
                title=title,
                chunks_created=0,
                chunks_deleted=deleted_count,
                content_length=0,
                status="empty_content"
            )

        # Chunk the content
        chunks = self._chunker.chunk(cleaned)

        if not chunks:
            logger.warning(f"Article {post_id} produced no chunks")
            return IndexingResult(
                post_id=post_id,
                title=title,
                chunks_created=0,
                chunks_deleted=deleted_count,
                content_length=len(cleaned),
                status="no_chunks"
            )

        logger.info(f"Created {len(chunks)} chunks for article {post_id}")

        # Update BM25 Index (Sparse)
        # Convert TextChunk objects to dicts for BM25
        bm25_chunks = [
            {
                'content': c.content,
                'chunk_index': c.chunk_index,
                'section_title': c.section_title
            } 
            for c in chunks
        ]
        self._bm25.index_document(post_id, bm25_chunks)

        # Generate embeddings
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = await self._embedding.embed_batch(chunk_texts)

        # Store in vector database (Dense)
        stored_count = self._vector_store.add_chunks(
            post_id=post_id,
            chunks=chunks,
            embeddings=embeddings
        )

        logger.info(f"Indexed article {post_id}: {stored_count} chunks stored")

        return IndexingResult(
            post_id=post_id,
            title=title,
            chunks_created=stored_count,
            chunks_deleted=deleted_count,
            content_length=len(cleaned),
            status="indexed"
        )

    async def delete_article(self, post_id: str) -> IndexingResult:
        """Delete all indexed chunks for an article."""
        if not self._initialized:
            await self.initialize()

        deleted_count = self._vector_store.delete_post_chunks(post_id)
        self._bm25.remove_document(post_id)

        logger.info(f"Deleted {deleted_count} chunks for article {post_id}")

        return IndexingResult(
            post_id=post_id,
            title=None,
            chunks_created=0,
            chunks_deleted=deleted_count,
            content_length=0,
            status="deleted"
        )

    async def is_article_indexed(self, post_id: str) -> bool:
        """Check if an article has been indexed."""
        if not self._initialized:
            await self.initialize()

        chunks = self._vector_store.get_post_chunks(post_id)
        return len(chunks) > 0

    def get_index_stats(self) -> dict:
        """Get indexing statistics."""
        return {
            "total_chunks": self._vector_store.get_total_count(),
            "status": "healthy"
        }
