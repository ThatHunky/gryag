import pytest

from app.services.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_limit(test_db):
    limiter = RateLimiter(test_db, per_user_per_hour=3)
    await limiter.init()

    # First three requests should pass
    for expected_remaining in (2, 1, 0):
        allowed, remaining, retry = await limiter.check_and_increment(user_id=42)
        assert allowed
        assert remaining == expected_remaining
        assert retry >= 0

    # Fourth request should be blocked
    allowed, remaining, retry = await limiter.check_and_increment(user_id=42)
    assert not allowed
    assert remaining == 0
    assert retry > 0


@pytest.mark.asyncio
async def test_rate_limiter_resets_next_window(test_db):
    limiter = RateLimiter(test_db, per_user_per_hour=2)
    await limiter.init()

    base_ts = 1_700_000_000

    allowed, remaining, _ = await limiter.check_and_increment(99, now=base_ts)
    assert allowed and remaining == 1

    allowed, remaining, _ = await limiter.check_and_increment(99, now=base_ts + 10)
    assert allowed and remaining == 0

    # Move to next hour window
    allowed, remaining, _ = await limiter.check_and_increment(
        99, now=base_ts + RateLimiter.WINDOW_SECONDS + 5
    )
    assert allowed and remaining == 1
