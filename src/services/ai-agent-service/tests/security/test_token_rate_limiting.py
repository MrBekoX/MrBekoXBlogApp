# tests/security/test_token_rate_limiting.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.security.token_rate_limiter import UnifiedRateLimiter

@pytest.mark.asyncio
async def test_unified_rate_limiter_allow():
    # Mock Redis
    mock_redis = AsyncMock()
    mock_pipeline = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.__aenter__.return_value = mock_pipeline
    mock_pipeline.__aexit__.return_value = None
    
    # Simulate Redis logic: zrem, zcard, zadd, expire
    # execute() returns results of pipelined commands.
    # We care about the result of zcard (2nd command)
    # [zrem_count, zcard_count, ...]
    mock_pipeline.execute.return_value = [0, 9] # Current count 9, limit 10
    
    limiter = UnifiedRateLimiter(mock_redis)
    allowed = await limiter.check_limit("user:1", limit=10, period=60)
    
    assert allowed is True
    # Verify we added the request
    mock_pipeline.zadd.assert_called_once()
    mock_pipeline.expire.assert_called_once()

@pytest.mark.asyncio
async def test_unified_rate_limiter_deny():
    # Mock Redis
    mock_redis = AsyncMock()
    mock_pipeline = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.__aenter__.return_value = mock_pipeline
    mock_pipeline.__aexit__.return_value = None
    
    # Current count 10, limit 10 -> Should deny (since 10 < 10 is False)
    mock_pipeline.execute.return_value = [0, 10]
    
    limiter = UnifiedRateLimiter(mock_redis)
    allowed = await limiter.check_limit("user:1", limit=10, period=60)
    
    assert allowed is False
    # Verify we did NOT add the request (or at least didn't count it as success)
    # Our logic: if count < limit: add. Else: return False.
    # So zadd should NOT be called.
    mock_pipeline.zadd.assert_not_called()

@pytest.mark.asyncio
async def test_unified_rate_limiter_redis_fail():
    # Mock Redis failure
    mock_redis = AsyncMock()
    mock_redis.pipeline.side_effect = Exception("Redis down")
    
    limiter = UnifiedRateLimiter(mock_redis)
    # Should fail open (allow)
    allowed = await limiter.check_limit("user:1", limit=10, period=60)
    
    assert allowed is True
