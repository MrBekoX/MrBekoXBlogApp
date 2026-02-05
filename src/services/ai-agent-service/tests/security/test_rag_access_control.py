import pytest
from app.rag.secure_retriever import SecureRAGRetriever
from unittest.mock import Mock, AsyncMock

class TestRAGAccessControl:
    """RAG access control test suite."""

    @pytest.fixture
    def retriever(self):
        """Create test retriever with mocked base."""
        mock_base = Mock()
        # Mock retrieve to be async (awaitable)
        mock_base.retrieve = AsyncMock(return_value=Mock(chunks=[]))
        return SecureRAGRetriever(mock_base)

    @pytest.mark.asyncio
    async def test_unauthorized_access_blocked(self, retriever):
        """Test unauthorized access is blocked."""
        # Mock the access check to return False
        # We patch the internal method or usage 
        # Since _check_post_access is on the instance, we can mock it
        retriever._check_post_access = AsyncMock(return_value=False)

        with pytest.raises(PermissionError, match="Access denied"):
            await retriever.retrieve(
                query="test",
                post_id="private-post",
                user_id="user-a",
                k=5
            )

    @pytest.mark.asyncio
    async def test_pii_filtering(self, retriever):
        """Test PII filtering in retrieved chunks."""
        # Mock successful retrieval
        mock_chunk = Mock()
        mock_chunk.content = "Contact: 0555 123 45 67"
        
        mock_result = Mock()
        mock_result.chunks = [mock_chunk]
        
        retriever.retriever.retrieve = AsyncMock(return_value=mock_result)
        retriever._check_post_access = AsyncMock(return_value=True)

        result = await retriever.retrieve("query", "post", "user")

        assert "[PHONE_REDACTED]" in result.chunks[0].content
