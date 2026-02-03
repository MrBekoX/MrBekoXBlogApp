"""Domain interfaces (Ports) - Abstract contracts for infrastructure adapters."""

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.interfaces.i_cache import ICache
from app.domain.interfaces.i_vector_store import IVectorStore
from app.domain.interfaces.i_message_broker import IMessageBroker
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.domain.interfaces.i_web_search import IWebSearchProvider

__all__ = [
    "ILLMProvider",
    "ICache",
    "IVectorStore",
    "IMessageBroker",
    "IEmbeddingProvider",
    "IWebSearchProvider",
]
