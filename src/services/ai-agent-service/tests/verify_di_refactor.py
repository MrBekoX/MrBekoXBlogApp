import sys
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Mock external dependencies
sys.modules["httpx"] = MagicMock()
sys.modules["aio_pika"] = MagicMock()
sys.modules["aio_pika.abc"] = MagicMock()
sys.modules["aio_pika.pool"] = MagicMock()
sys.modules["aio_pika.exceptions"] = MagicMock()
sys.modules["redis"] = MagicMock()
sys.modules["redis.asyncio"] = MagicMock()
sys.modules["rank_bm25"] = MagicMock()
sys.modules["sentence_transformers"] = MagicMock()
sys.modules["sklearn"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["chromadb"] = MagicMock()
sys.modules["chromadb.config"] = MagicMock()
sys.modules["chromadb.api"] = MagicMock()
sys.modules["chromadb.api.models"] = MagicMock()
sys.modules["chromadb.api.models.Collection"] = MagicMock()
sys.modules["chromadb.utils"] = MagicMock()
sys.modules["langchain_ollama"] = MagicMock()
sys.modules["slowapi"] = MagicMock()
sys.modules["slowapi.errors"] = MagicMock()
sys.modules["slowapi.extension"] = MagicMock()
sys.modules["slowapi.util"] = MagicMock()
sys.modules["ddgs"] = MagicMock()
sys.modules["duckduckgo_search"] = MagicMock()

# Mock settings
with patch("app.core.config.settings") as mock_settings:
    mock_settings.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
    mock_settings.ollama_model = "gemma3"
    mock_settings.ollama_base_url = "http://localhost:11434"
    
    # Import app modules after mocking
    from app.api.deps import (
        get_simple_blog_agent,
        get_rag_retriever,
        get_incident_tracker,
        get_rag_chat_handler,
        get_text_chunker,
        get_embedding_service,
        get_vector_store,
        get_article_indexer,
        get_web_search_tool
    )
    from app.messaging.processor import MessageProcessor

@pytest.mark.asyncio
async def test_dependency_factories():
    print("Testing Dependency Factories...")
    
    # Test simple factories
    chunker = get_text_chunker()
    assert chunker is not None
    print("✓ TextChunker factory")
    
    embeddings = get_embedding_service()
    assert embeddings is not None
    print("✓ EmbeddingService factory")
    
    vector_store = get_vector_store()
    assert vector_store is not None
    print("✓ VectorStore factory")
    
    agent = get_simple_blog_agent()
    assert agent is not None
    print("✓ SimpleBlogAgent factory")
    
    incident_tracker = get_incident_tracker()
    assert incident_tracker is not None
    print("✓ IncidentTracker factory")
    
    web_search = get_web_search_tool()
    assert web_search is not None
    print("✓ WebSearchTool factory")
    
    # Test complex factories (with dependencies)
    indexer = get_article_indexer(
        embedding_service=embeddings,
        chunker=chunker,
        vector_store=vector_store
    )
    assert indexer is not None
    print("✓ ArticleIndexer factory")
    
    retriever = get_rag_retriever(
        embedding_service=embeddings,
        vector_store=vector_store
    )
    assert retriever is not None
    print("✓ Retriever factory")
    
    headers = get_rag_chat_handler(
        retriever=retriever,
        web_search=web_search,
        agent=agent
    )
    assert headers is not None
    print("✓ RagChatHandler factory")
    
    print("All factories passed.")

@pytest.mark.asyncio
async def test_message_processor_initialization():
    print("\nTesting MessageProcessor Initialization...")
    
    # Mock internal calls that happen during initialize
    with patch("logging.getLogger"), \
         patch("app.core.cache.cache.acquire_lock", new_callable=AsyncMock), \
         patch("app.core.cache.cache.release_lock", new_callable=AsyncMock), \
         patch("aio_pika.connect_robust", new_callable=AsyncMock) as mock_connect:
             
        processor = MessageProcessor()
        
        # Mock dependencies' initialize methods
        # Because factories return singletons (mocked above or real instances with mocked internals)
        # But wait, above tests instantiated real classes (with mocked external libs).
        # So we need to ensure their initialize methods don't crash.
        
        # Mock SimpleBlogAgent.initialize
        with patch.object(processor, '_agent', new_callable=MagicMock) as mock_agent, \
             patch.object(processor, '_indexer', new_callable=MagicMock) as mock_indexer, \
             patch.object(processor, '_retriever', new_callable=MagicMock) as mock_retriever, \
             patch.object(processor, '_rag_chat_handler', new_callable=MagicMock) as mock_chat_handler, \
             patch("app.messaging.processor.get_simple_blog_agent", return_value=mock_agent), \
             patch("app.messaging.processor.get_article_indexer", return_value=mock_indexer), \
             patch("app.messaging.processor.get_rag_retriever", return_value=mock_retriever), \
             patch("app.messaging.processor.get_rag_chat_handler", return_value=mock_chat_handler), \
             patch("app.messaging.processor.get_web_search_tool"):

            # Fix: mock_agent.initialize is sync, others are async
            mock_indexer.initialize = AsyncMock()
            mock_retriever.initialize = AsyncMock()
            mock_chat_handler.initialize = AsyncMock()
            
            await processor.initialize()
            
            # Verify calls
            mock_connect.assert_called_once()
            mock_agent.initialize.assert_called_once()
            mock_indexer.initialize.assert_called_once()
            mock_retriever.initialize.assert_called_once()
            mock_chat_handler.initialize.assert_called_once()
            
            print("✓ MessageProcessor initialized and called mock dependencies")

if __name__ == "__main__":
    # Manually run async tests if executed directly
    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(test_dependency_factories())
    loop.run_until_complete(test_message_processor_initialization())
    loop.close()
