# tests/security/test_token_rate_limiting.py
import pytest
import asyncio
from app.security.token_rate_limiter import TokenRateLimiter, UserQuota, RateLimitError

@pytest.mark.asyncio
async def test_token_limit():
    limiter = TokenRateLimiter()
    quota = UserQuota(tokens_per_minute=100)
    user_id = "test-user-tokens"

    # Should pass
    await limiter.check_limit(user_id, quota)

    # Record usage
    await limiter.record_usage(user_id, tokens=100)

    # Should fail
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_limit(user_id, quota)
    assert "tokens" in excinfo.value.limit_type

@pytest.mark.asyncio
async def test_request_limit():
    limiter = TokenRateLimiter()
    quota = UserQuota(requests_per_minute=2)
    user_id = "test-user-requests"

    # Should pass 2 times (checks happen before increment in middleware usually, 
    # but here we manually record usage to simulate middleware finishing)
    await limiter.check_limit(user_id, quota)
    await limiter.record_usage(user_id)
    
    await limiter.check_limit(user_id, quota)
    await limiter.record_usage(user_id)

    # Should fail on 3rd check if we exceeded
    # Wait, 2 requests allowed.
    # usage=0 -> ok, rec -> usage=1
    # usage=1 -> ok, rec -> usage=2
    # usage=2 -> fail
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_limit(user_id, quota)
    assert "requests" in excinfo.value.limit_type

@pytest.mark.asyncio
async def test_concurrent_limit():
    limiter = TokenRateLimiter()
    quota = UserQuota(concurrent_requests=2)
    user_id = "test-user-concurrency"

    # Start 1
    await limiter.start_request(user_id)
    await limiter.check_limit(user_id, quota)
    
    # Start 2
    await limiter.start_request(user_id)
    await limiter.check_limit(user_id, quota)
    
    # Start 3 (Should fail check before start)
    # Actually logic is check THEN start.
    # Active requests = 2. Limit = 2.
    # Check checks if active >= limit. 2>=2 is True.
    # So it should fail.
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_limit(user_id, quota)
    assert "concurrent" in excinfo.value.limit_type
