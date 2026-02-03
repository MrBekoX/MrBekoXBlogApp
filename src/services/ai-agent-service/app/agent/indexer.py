"""Article indexer for RAG - chunks, embeds, and stores articles."""

import logging
from typing import Optional

from app.rag.embeddings import EmbeddingService, embedding_service
from app.rag.chunker import TextChunker, text_chunker
from app.rag.vector_store import VectorStore, vector_store
from app.agent.simple_blog_agent import strip_html_and_images

logger = logging.getLogger(__name__)


def clean_content_for_rag(content: str) -> str:
    """
    Milder content cleaning specifically for RAG indexing.
    
    This function preserves more content structure compared to strip_html_and_images
    which is designed for LLM prompts. For RAG, we want to keep meaningful text.
    """
    import re
    
    if not content:
        return ""
    
    # Remove base64 images (data:image/xxx;base64,...)
    content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '', content)
    
    # Remove markdown images ![alt](url) but keep alt text
    content = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', content)
    
    # Remove HTML image tags but keep alt text
    content = re.sub(r'<img[^>]*alt=["\']([^"\']*)["\'][^>]*>', r'\1', content, flags=re.IGNORECASE)
    content = re.sub(r'<img[^>]*>', '', content, flags=re.IGNORECASE)
    
    # Remove HTML tags but keep text content (be more conservative)
    # Keep basic formatting like <b>, <i>, <em>, <strong>
    content = re.sub(r'</?(b|i|em|strong)>', ' ', content, flags=re.IGNORECASE)
    # Remove other HTML tags
    content = re.sub(r'<[^>]+>', ' ', content)
    
    # Remove URLs (http/https) but keep surrounding text
    content = re.sub(r'https?://\S+', '', content)
    
    # Apply sanitization for prompt injection protection (milder)
    content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', content)
    content = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f]', '', content)
    
    # Normalize whitespace but preserve paragraph structure
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = re.sub(r' {2,}', ' ', content)
    
    return content.strip()


class ArticleIndexer:
    """
    Indexes articles for RAG retrieval.

    When an article is published/updated:
    1. Clean the content (remove HTML, images)
    2. Chunk the content into semantic units
    3. Generate embeddings for each chunk
    4. Store in vector database with metadata
    """

    def __init__(
        self,
        embedding_svc: Optional[EmbeddingService] = None,
        chunker: Optional[TextChunker] = None,
        store: Optional[VectorStore] = None
    ):
        self._embedding_service = embedding_svc or embedding_service
        self._chunker = chunker or text_chunker
        self._vector_store = store or vector_store
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize underlying services."""
        if self._initialized:
            return

        await self._embedding_service.initialize()
        self._vector_store.initialize()
        self._initialized = True
        logger.info("ArticleIndexer initialized")

    async def index_article(
        self,
        post_id: str,
        title: str,
        content: str,
        delete_existing: bool = True
    ) -> dict:
        """
        Index an article for RAG retrieval.

        Args:
            post_id: Unique article identifier
            title: Article title
            content: Article content (markdown)
            delete_existing: Whether to delete existing chunks first

        Returns:
            Dict with indexing statistics
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"Indexing article {post_id}: {title[:50]}...")

        # Delete existing chunks if requested
        deleted_count = 0
        if delete_existing:
            deleted_count = self._vector_store.delete_post_chunks(post_id)
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} existing chunks for post {post_id}")

        # Prepare content: add title as first section
        full_content = f"# {title}\n\n{content}"

        # Clean the content using RAG-specific cleaner
        cleaned_content = clean_content_for_rag(full_content)

        logger.info(f"Content after cleaning for article {post_id}: {cleaned_content[:200]}...")
        logger.info(f"Cleaned content length: {len(cleaned_content)} characters")

        if not cleaned_content.strip():
            logger.warning(f"Article {post_id} has no content after cleaning")
            logger.warning(f"Original content length: {len(full_content)} characters")
            logger.warning(f"Original content preview: {full_content[:200]}...")
            return {
                "post_id": post_id,
                "chunks_created": 0,
                "chunks_deleted": deleted_count,
                "status": "empty_content"
            }

        # Chunk the content
        chunks = self._chunker.chunk(cleaned_content)

        logger.info(f"Chunking result for article {post_id}: {len(chunks)} chunks created")

        if not chunks:
            logger.warning(f"Article {post_id} produced no chunks")
            logger.warning(f"Content being chunked: {cleaned_content[:500]}...")
            return {
                "post_id": post_id,
                "chunks_created": 0,
                "chunks_deleted": deleted_count,
                "status": "no_chunks"
            }

        logger.info(f"Created {len(chunks)} chunks for article {post_id}")

        # Generate embeddings for all chunks
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = await self._embedding_service.embed_batch(chunk_texts)

        # Store in vector database
        stored_count = self._vector_store.add_chunks(
            post_id=post_id,
            chunks=chunks,
            embeddings=embeddings
        )

        logger.info(f"Indexed article {post_id}: {stored_count} chunks stored")

        return {
            "post_id": post_id,
            "title": title,
            "chunks_created": stored_count,
            "chunks_deleted": deleted_count,
            "content_length": len(cleaned_content),
            "status": "indexed"
        }

    async def delete_article(self, post_id: str) -> dict:
        """
        Delete all indexed chunks for an article.

        Args:
            post_id: Article identifier

        Returns:
            Dict with deletion statistics
        """
        if not self._initialized:
            await self.initialize()

        deleted_count = self._vector_store.delete_post_chunks(post_id)
        logger.info(f"Deleted {deleted_count} chunks for article {post_id}")

        return {
            "post_id": post_id,
            "chunks_deleted": deleted_count,
            "status": "deleted"
        }

    async def is_article_indexed(self, post_id: str) -> bool:
        """Check if an article has been indexed."""
        if not self._initialized:
            await self.initialize()

        chunks = self._vector_store.get_post_chunks(post_id)
        return len(chunks) > 0

    async def get_index_stats(self) -> dict:
        """Get indexing statistics."""
        if not self._initialized:
            await self.initialize()

        total_chunks = self._vector_store.get_total_count()

        return {
            "total_chunks": total_chunks,
            "status": "healthy"
        }


# Global singleton instance
article_indexer = ArticleIndexer()
