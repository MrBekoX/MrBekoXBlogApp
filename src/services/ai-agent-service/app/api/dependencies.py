"""Dependency Injection container - Wires all components together."""

from functools import lru_cache
from fastapi import Depends

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.interfaces.i_cache import ICache
from app.domain.interfaces.i_vector_store import IVectorStore
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.domain.interfaces.i_message_broker import IMessageBroker
from app.domain.interfaces.i_web_search import IWebSearchProvider

from app.infrastructure.llm.ollama_adapter import OllamaAdapter
from app.infrastructure.cache.redis_adapter import RedisAdapter
from app.infrastructure.vector_store.chroma_adapter import ChromaAdapter
from app.infrastructure.embedding.ollama_embedding_adapter import OllamaEmbeddingAdapter
from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter
from app.infrastructure.search.duckduckgo_adapter import DuckDuckGoAdapter

from app.services.analysis_service import AnalysisService
from app.services.seo_service import SeoService
from app.services.rag_service import RagService
from app.services.indexing_service import IndexingService
from app.services.chat_service import ChatService
from app.services.message_processor_service import MessageProcessorService


# ==================== Infrastructure Singletons ====================
# These are created once and reused (Singleton pattern with lru_cache)


from app.services.resilient_llm_provider import ResilientLLMProvider

@lru_cache()
def get_llm_provider() -> ILLMProvider:
    """Get LLM provider singleton (Resilient Ollama)."""
    base_provider = OllamaAdapter()
    return ResilientLLMProvider(base_provider)


from app.core.multi_level_cache import MultiLevelCache

@lru_cache()
def get_redis_adapter() -> RedisAdapter:
    """Get Redis adapter singleton."""
    return RedisAdapter()


@lru_cache()
def get_cache() -> ICache:
    """Get cache singleton (Multi-Level: Memory + Redis + Semantic)."""
    return MultiLevelCache(get_redis_adapter(), vector_store=get_vector_store())


@lru_cache()
def get_vector_store() -> IVectorStore:
    """Get vector store singleton (Chroma)."""
    return ChromaAdapter()


from app.services.optimized_embedding_provider import OptimizedEmbeddingProvider

@lru_cache()
def get_embedding_provider() -> IEmbeddingProvider:
    """Get embedding provider singleton (Optimized Ollama)."""
    base_provider = OllamaEmbeddingAdapter()
    cache = get_redis_adapter() # Use shared connected instance
    return OptimizedEmbeddingProvider(base_provider, cache)


@lru_cache()
def get_message_broker() -> IMessageBroker:
    """Get message broker singleton (RabbitMQ)."""
    return RabbitMQAdapter()


@lru_cache()
def get_web_search_provider() -> IWebSearchProvider:
    """Get web search provider singleton (DuckDuckGo)."""
    return DuckDuckGoAdapter()


# ==================== Service Factories ====================
# Services are created with their dependencies injected


def get_seo_service(
    llm: ILLMProvider = Depends(get_llm_provider)
) -> SeoService:
    """Get SEO service with injected dependencies."""
    return SeoService(llm_provider=llm)


def get_analysis_service(
    llm: ILLMProvider = Depends(get_llm_provider),
    seo: SeoService = Depends(get_seo_service)
) -> AnalysisService:
    """Get analysis service with injected dependencies."""
    return AnalysisService(llm_provider=llm, seo_service=seo)


def get_rag_service(
    embedding: IEmbeddingProvider = Depends(get_embedding_provider),
    vector_store: IVectorStore = Depends(get_vector_store)
) -> RagService:
    """Get RAG service with injected dependencies."""
    return RagService(embedding_provider=embedding, vector_store=vector_store)


def get_indexing_service(
    embedding: IEmbeddingProvider = Depends(get_embedding_provider),
    vector_store: IVectorStore = Depends(get_vector_store)
) -> IndexingService:
    """Get indexing service with injected dependencies."""
    return IndexingService(embedding_provider=embedding, vector_store=vector_store)


def get_chat_service(
    llm: ILLMProvider = Depends(get_llm_provider),
    rag: RagService = Depends(get_rag_service),
    web_search: IWebSearchProvider = Depends(get_web_search_provider),
    analysis: AnalysisService = Depends(get_analysis_service)
) -> ChatService:
    """Get chat service with injected dependencies."""
    return ChatService(
        llm_provider=llm,
        rag_service=rag,
        web_search_provider=web_search,
        analysis_service=analysis
    )


def get_message_processor(
    cache: ICache = Depends(get_cache),
    broker: IMessageBroker = Depends(get_message_broker),
    analysis: AnalysisService = Depends(get_analysis_service),
    indexing: IndexingService = Depends(get_indexing_service),
    chat: ChatService = Depends(get_chat_service)
) -> MessageProcessorService:
    """Get message processor service with injected dependencies."""
    return MessageProcessorService(
        cache=cache,
        message_broker=broker,
        analysis_service=analysis,
        indexing_service=indexing,
        chat_service=chat
    )


# ==================== Container Access ====================
# Direct access to singletons for lifecycle management


class DependencyContainer:
    """
    Container for accessing dependency singletons.

    Used during application startup/shutdown for lifecycle management.
    """

    _llm: ILLMProvider | None = None
    _cache: ICache | None = None
    _vector_store: IVectorStore | None = None
    _embedding: IEmbeddingProvider | None = None
    _broker: IMessageBroker | None = None
    _web_search: IWebSearchProvider | None = None

    @classmethod
    def get_llm(cls) -> ILLMProvider:
        if cls._llm is None:
            cls._llm = get_llm_provider()
        return cls._llm

    @classmethod
    def get_cache(cls) -> ICache:
        if cls._cache is None:
            cls._cache = get_cache()
        return cls._cache

    @classmethod
    def get_vector_store(cls) -> IVectorStore:
        if cls._vector_store is None:
            cls._vector_store = get_vector_store()
        return cls._vector_store

    @classmethod
    def get_embedding(cls) -> IEmbeddingProvider:
        if cls._embedding is None:
            cls._embedding = get_embedding_provider()
        return cls._embedding

    @classmethod
    def get_broker(cls) -> IMessageBroker:
        if cls._broker is None:
            cls._broker = get_message_broker()
        return cls._broker

    @classmethod
    def get_web_search(cls) -> IWebSearchProvider:
        if cls._web_search is None:
            cls._web_search = get_web_search_provider()
        return cls._web_search

    @classmethod
    async def initialize_all(cls) -> None:
        """Initialize all infrastructure components."""
        await cls.get_cache().connect()
        await cls.get_embedding().initialize()
        cls.get_vector_store().initialize()
        await cls.get_broker().connect()

    @classmethod
    async def shutdown_all(cls) -> None:
        """Shutdown all infrastructure components."""
        if cls._broker:
            await cls._broker.disconnect()
        if cls._embedding:
            await cls._embedding.shutdown()
        if cls._cache:
            await cls._cache.disconnect()
