"""
Integration tests for /api/v1/analytics/* endpoints.
Patches ClickHouseAdapter so no real ClickHouse needed.
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.adapters.clickhouse import ClickHouseAdapter
from app.main import app


# ── Shared fixtures ───────────────────────────────────────────────────

class _NoOpCache:
    async def get_or_compute(self, *a, **kw): pass
    async def close(self): pass


@pytest.fixture(autouse=True)
def stub_app_state():
    """Install stub cache + a mock ClickHouseAdapter on app.state."""
    app.state.cache = _NoOpCache()
    app.state.clickhouse = AsyncMock(spec=ClickHouseAdapter)
    yield


# ── Cross-project summary ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_project_summary_200():
    app.state.clickhouse.get_cross_project_summary = AsyncMock(return_value=[
        {"project_id": "proj-a", "total_cost": 5000.0, "total_hours": 200.0, "record_count": 10},
    ])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/cross-project-summary",
            params={"start_month": "2026-01-01", "end_month": "2026-03-01"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["projects"][0]["project_id"] == "proj-a"


@pytest.mark.asyncio
async def test_cross_project_summary_422_invalid_range():
    """start_month > end_month → 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/cross-project-summary",
            params={"start_month": "2026-06-01", "end_month": "2026-01-01"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cross_project_summary_503_on_ch_error():
    app.state.clickhouse.get_cross_project_summary = AsyncMock(
        side_effect=Exception("CH down")
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/cross-project-summary",
            params={"start_month": "2026-01-01", "end_month": "2026-03-01"},
        )
    assert resp.status_code == 503


# ── VM type trend ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vm_type_trend_200():
    app.state.clickhouse.get_vm_type_trend = AsyncMock(return_value=[
        {"billing_month": "2026-01-01", "vm_type": "standard", "cost": 1200.0, "hours": 100.0},
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/vm-type-trend/proj-abc")

    assert resp.status_code == 200
    assert resp.json()["project_id"] == "proj-abc"


@pytest.mark.asyncio
async def test_vm_type_trend_404_when_empty():
    app.state.clickhouse.get_vm_type_trend = AsyncMock(return_value=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/vm-type-trend/ghost-project")
    assert resp.status_code == 404


# ── Forecast accuracy ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forecast_accuracy_200():
    app.state.clickhouse.get_forecast_accuracy_history = AsyncMock(return_value=[
        {
            "forecast_id": "abc", "created_at": "2026-04-01",
            "algorithm": "holt", "mape_score": 4.2,
            "forecast_month": "2026-05-01",
            "predicted": 1500.0, "lower_ci": 1400.0, "upper_ci": 1600.0,
        }
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/forecast-accuracy/proj-abc")

    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == "proj-abc"
    assert body["forecasts"][0]["mape_score"] == 4.2


@pytest.mark.asyncio
async def test_forecast_accuracy_503_on_ch_error():
    app.state.clickhouse.get_forecast_accuracy_history = AsyncMock(
        side_effect=Exception("timeout")
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/forecast-accuracy/proj-abc")
    assert resp.status_code == 503
