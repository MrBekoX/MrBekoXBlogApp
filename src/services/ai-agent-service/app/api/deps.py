from fastapi import Depends
import redis.asyncio as redis
from app.core.cache import cache
from app.security.token_rate_limiter import UnifiedRateLimiter

async def get_redis_client() -> redis.Redis:
    """Dependency that provides the Redis client from the global cache instance."""
    # Ensure connection exists
    if cache._client is None:
        await cache.connect()
    return cache.client

async def get_rate_limiter(
    redis_client: redis.Redis = Depends(get_redis_client)
) -> UnifiedRateLimiter:
    """Dependency that provides the UnifiedRateLimiter instance."""
    return UnifiedRateLimiter(redis_client)

from functools import lru_cache
from app.agent.simple_blog_agent import SimpleBlogAgent
from app.rag.retriever import Retriever
from app.security.incident_tracker import IncidentTracker
from app.agent.rag_chat_handler import RagChatHandler
from app.rag.chunker import TextChunker
from app.rag.embeddings import EmbeddingService
from app.infrastructure.vector_store.chroma_adapter import ChromaAdapter
from app.agent.indexer import ArticleIndexer
from app.domain.interfaces.i_vector_store import IVectorStore

@lru_cache()
def get_text_chunker() -> TextChunker:
    return TextChunker()

@lru_cache()
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()

@lru_cache()
def get_vector_store() -> IVectorStore:
    return ChromaAdapter()

@lru_cache()
def get_incident_tracker() -> IncidentTracker:
    return IncidentTracker()

@lru_cache()
def get_rag_retriever(
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: IVectorStore = Depends(get_vector_store)
) -> Retriever:
    return Retriever(embedding_svc=embedding_service, store=vector_store)

@lru_cache()
def get_simple_blog_agent() -> SimpleBlogAgent:
    return SimpleBlogAgent()

@lru_cache()
def get_article_indexer(
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    chunker: TextChunker = Depends(get_text_chunker),
    vector_store: IVectorStore = Depends(get_vector_store)
) -> ArticleIndexer:
    return ArticleIndexer(
        embedding_svc=embedding_service,
        chunker=chunker,
        store=vector_store
    )

from app.tools.web_search import WebSearchTool

@lru_cache()
def get_web_search_tool() -> WebSearchTool:
    return WebSearchTool()

@lru_cache()
def get_rag_chat_handler(
    retriever: Retriever = Depends(get_rag_retriever),
    web_search: WebSearchTool = Depends(get_web_search_tool),
    agent: SimpleBlogAgent = Depends(get_simple_blog_agent)
) -> RagChatHandler:
    return RagChatHandler(
        retriever_instance=retriever,
        web_search=web_search,
        agent=agent
    )
