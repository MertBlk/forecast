"""
Unit tests for ForecastCache.

Uses unittest.mock to patch redis.asyncio — no real Redis needed.
Tests cover: get/set/invalidate, TTL jitter, stampede lock, close.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.cache import ForecastCache


# ── Helpers ───────────────────────────────────────────────────────────

def _make_cache(mock_redis) -> ForecastCache:
    """Return a ForecastCache with its internal Redis client replaced by a mock."""
    cache = ForecastCache.__new__(ForecastCache)   # skip __init__
    cache._redis = mock_redis
    return cache


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get    = AsyncMock(return_value=None)   # default: cache miss
    r.setex  = AsyncMock()
    r.delete = AsyncMock()
    r.aclose = AsyncMock()
    # scan_iter must be an async generator
    async def _scan_iter(pattern):
        yield f"forecast:proj-x:3:auto"
    r.scan_iter = _scan_iter
    return r


@pytest.fixture
def cache(mock_redis):
    return _make_cache(mock_redis)


# ── get ───────────────────────────────────────────────────────────────

class TestCacheGet:
    @pytest.mark.asyncio
    async def test_returns_none_on_miss(self, cache, mock_redis):
        mock_redis.get.return_value = None
        result = await cache.get("proj-x", 3, "auto")
        assert result is None

    @pytest.mark.asyncio
    async def test_deserialises_json_on_hit(self, cache, mock_redis):
        payload = {"forecast_id": "abc", "points": []}
        mock_redis.get.return_value = json.dumps(payload)
        result = await cache.get("proj-x", 3, "auto")
        assert result == payload


# ── set ───────────────────────────────────────────────────────────────

class TestCacheSet:
    @pytest.mark.asyncio
    async def test_calls_setex_with_json(self, cache, mock_redis):
        value = {"foo": "bar"}
        await cache.set("proj-x", 3, "auto", value)
        # setex(key, ttl, json_payload) must have been called once
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        key, ttl, raw = args
        assert key == "forecast:proj-x:3:auto"
        assert json.loads(raw) == value

    @pytest.mark.asyncio
    async def test_ttl_has_jitter(self, cache, mock_redis):
        """TTL should vary ±10% around settings.cache_ttl_seconds."""
        from app.config import settings
        ttls = set()
        for _ in range(20):
            await cache.set("p", 1, "auto", {})
            args = mock_redis.setex.call_args[0]
            ttls.add(args[1])   # TTL is second positional arg
        base = settings.cache_ttl_seconds
        assert all(int(base * 0.9) <= t <= int(base * 1.1) for t in ttls)
        # With 20 calls the TTL should vary (not always the same value)
        assert len(ttls) > 1


# ── invalidate_project ────────────────────────────────────────────────

class TestInvalidateProject:
    @pytest.mark.asyncio
    async def test_deletes_matching_keys(self, cache, mock_redis):
        deleted = await cache.invalidate_project("proj-x")
        # scan_iter yields one key → delete called once
        mock_redis.delete.assert_called_once_with("forecast:proj-x:3:auto")
        assert deleted == 1


# ── get_or_compute (stampede prevention) ─────────────────────────────

class TestGetOrCompute:
    @pytest.mark.asyncio
    async def test_returns_cached_without_calling_compute(self, cache, mock_redis):
        payload = {"data": 42}
        mock_redis.get.return_value = json.dumps(payload)

        compute_called = False
        async def compute():
            nonlocal compute_called
            compute_called = True
            return {}

        result, was_cached = await cache.get_or_compute("p", 3, "auto", compute)
        assert was_cached is True
        assert result == payload
        assert not compute_called   # compute must NOT be called on hit

    @pytest.mark.asyncio
    async def test_calls_compute_and_stores_on_miss(self, cache, mock_redis):
        mock_redis.get.return_value = None   # always miss

        async def compute():
            return {"fresh": True}

        result, was_cached = await cache.get_or_compute("p", 3, "auto", compute)
        assert was_cached is False
        assert result == {"fresh": True}
        # set() should have been called to store the result
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_check_after_lock(self, cache, mock_redis):
        """
        Simulate: first get() misses, but by the time we acquire the lock
        another coroutine has filled the cache (second get() hits).
        compute must NOT be called.
        """
        call_count = 0

        async def _get_side_effect(key):
            nonlocal call_count
            call_count += 1
            # First call (fast-path check) → miss; second call (post-lock) → hit
            if call_count == 1:
                return None
            return json.dumps({"from": "lock-winner"})

        mock_redis.get.side_effect = _get_side_effect

        compute_called = False
        async def compute():
            nonlocal compute_called
            compute_called = True
            return {}

        result, was_cached = await cache.get_or_compute("p", 3, "auto", compute)
        assert was_cached is True
        assert result == {"from": "lock-winner"}
        assert not compute_called
