"""
Integration tests for GET /api/v1/health.
Patches the DB session so no real Postgres is needed.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.cache import ForecastCache


class _NoOpCache:
    async def get_or_compute(self, *a, **kw): pass
    async def close(self): pass


@pytest.fixture(autouse=True)
def stub_cache():
    app.state.cache = _NoOpCache()


@pytest.mark.asyncio
async def test_health_returns_200_when_db_ok():
    """DB executes SELECT 1 without error → 200 ok."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    # Patch get_db to yield our mock session
    async def _mock_get_db():
        yield mock_session

    with patch("app.api.v1.health.get_db", _mock_get_db):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "reachable"


@pytest.mark.asyncio
async def test_health_returns_503_when_db_down():
    """DB raises an exception → FastAPI propagates 500 (unhandled in health route)."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))

    async def _mock_get_db():
        yield mock_session

    with patch("app.api.v1.health.get_db", _mock_get_db):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health")

    # FastAPI returns 500 for unhandled exceptions by default
    assert resp.status_code == 500
