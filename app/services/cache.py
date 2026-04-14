"""
Redis cache service — cache-aside pattern with stampede prevention.

Cache key format: forecast:{project_id}:{horizon}:{algorithm}

Stampede prevention:
  When the cache is cold, many concurrent requests for the same key would
  all call the compute function simultaneously (thundering herd).
  We use a per-key asyncio.Lock so only ONE coroutine computes;
  the others wait and then read the freshly-written cache entry.

TTL jitter:
  Adding random ±10% to TTL prevents all keys from expiring at the same
  instant (mass stampede at scheduled refresh time).

Rule 3: all Redis calls use `await` — no sync redis-py inside async.
Rule 5: call invalidate_project() after every ETL run.
Rule 8: never swallow exceptions — log and re-raise.
"""
import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# One lock object per cache key — created on first access, reused after.
# Stored in a plain dict (process-local). This is sufficient because
# Uvicorn runs one process per container in our setup.
_key_locks: dict[str, asyncio.Lock] = {}
_locks_meta = asyncio.Lock()  # guards _key_locks dict itself


async def _get_lock(key: str) -> asyncio.Lock:
    """Return (creating if needed) a per-key asyncio.Lock."""
    async with _locks_meta:
        if key not in _key_locks:
            _key_locks[key] = asyncio.Lock()
        return _key_locks[key]


class ForecastCache:
    """
    Thin wrapper around an async Redis connection pool.
    One shared instance lives on `app.state` (set up in lifespan).
    """

    def __init__(self, redis_url: str) -> None:
        # decode_responses=True → all values come back as str, not bytes
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    # ── Key helpers ──────────────────────────────────────────────────

    @staticmethod
    def _key(project_id: str, horizon: int, algorithm: str) -> str:
        return f"forecast:{project_id}:{horizon}:{algorithm}"

    @staticmethod
    def _project_pattern(project_id: str) -> str:
        """Wildcard pattern that matches all keys for a project."""
        return f"forecast:{project_id}:*"

    # ── Core operations ──────────────────────────────────────────────

    async def get(self, project_id: str, horizon: int, algorithm: str) -> Any | None:
        """Return cached forecast dict, or None if miss/expired."""
        key = self._key(project_id, horizon, algorithm)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)   # stored as JSON string

    async def set(
        self,
        project_id: str,
        horizon: int,
        algorithm: str,
        value: Any,
    ) -> None:
        """Serialise and store with TTL jitter to spread expiry times."""
        key = self._key(project_id, horizon, algorithm)
        # ±10% jitter so not all keys expire simultaneously
        jitter   = random.uniform(0.9, 1.1)
        ttl      = int(settings.cache_ttl_seconds * jitter)
        payload  = json.dumps(value)
        await self._redis.setex(key, ttl, payload)

    async def invalidate_project(self, project_id: str) -> int:
        """
        Delete all cached forecasts for a project.
        Call this after every ETL run (Rule 5).
        Returns number of keys deleted.
        """
        pattern = self._project_pattern(project_id)
        # SCAN instead of KEYS — KEYS blocks Redis on large datasets
        deleted = 0
        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)
            deleted += 1
        logger.info("cache: invalidated %d keys for project %s", deleted, project_id)
        return deleted

    # ── Stampede-safe compute-or-read ────────────────────────────────

    async def get_or_compute(
        self,
        project_id: str,
        horizon: int,
        algorithm: str,
        compute_fn: Callable[[], Awaitable[Any]],
    ) -> tuple[Any, bool]:
        """
        Return (value, cached: bool).

        1. Check cache — if hit, return immediately.
        2. Acquire per-key lock so only one coroutine computes.
        3. Double-check cache after acquiring lock (another coroutine
           may have just computed and stored it while we waited).
        4. Compute, store, release lock.

        Args:
            compute_fn: async callable with no args that returns the value to cache.
        """
        key = self._key(project_id, horizon, algorithm)

        # Fast path — no lock needed
        cached = await self.get(project_id, horizon, algorithm)
        if cached is not None:
            return cached, True

        lock = await _get_lock(key)
        async with lock:
            # Double-check: another waiter may have filled the cache
            cached = await self.get(project_id, horizon, algorithm)
            if cached is not None:
                return cached, True

            # We're the designated computer — call the actual forecast logic
            logger.debug("cache miss: computing forecast for key %s", key)
            value = await compute_fn()
            await self.set(project_id, horizon, algorithm, value)
            return value, False

    async def close(self) -> None:
        """Cleanly close the Redis connection pool (called in lifespan shutdown)."""
        await self._redis.aclose()
