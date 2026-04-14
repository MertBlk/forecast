"""
Integration tests for POST /api/v1/forecast/.

Uses InMemoryBillingAdapter — zero DB/Docker required.
Patches PostgresVmBillingAdapter at the module level so the endpoint
uses our in-memory double. Cache is replaced with a no-op stub.
"""
from unittest.mock import patch, AsyncMock
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.adapters.in_memory import InMemoryBillingAdapter
from app.main import app


# ── Stubs ─────────────────────────────────────────────────────────────

class _NoOpCache:
    """Cache that always misses — forces compute_fn to run every time."""
    async def get_or_compute(self, project_id, horizon, algorithm, compute_fn):
        result = await compute_fn()
        return result, False
    async def close(self): pass


class _NoOpClickHouse:
    async def close(self): pass


@pytest.fixture(autouse=True)
def stub_app_state():
    """Install no-op cache + clickhouse on app.state before each test."""
    app.state.cache = _NoOpCache()
    app.state.clickhouse = _NoOpClickHouse()


def _make_adapter_patch(adapter: InMemoryBillingAdapter):
    """
    Return a context manager that replaces PostgresVmBillingAdapter
    inside the forecast module with a factory that always returns `adapter`.
    """
    class _PatchedAdapter:
        def __new__(cls, session):   # intercept PostgresVmBillingAdapter(session)
            return adapter

    return patch("app.api.v1.forecast.PostgresVmBillingAdapter", _PatchedAdapter)


@pytest.fixture
def twelve_months() -> list[float]:
    return [1200.0, 1250.0, 1100.0, 1300.0, 1350.0, 1400.0,
            1380.0, 1420.0, 1500.0, 1480.0, 1550.0, 1600.0]


@pytest.fixture
def adapter_ok(twelve_months) -> InMemoryBillingAdapter:
    a = InMemoryBillingAdapter()
    a.seed("proj-abc", twelve_months)
    return a


@pytest.fixture
def adapter_short() -> InMemoryBillingAdapter:
    a = InMemoryBillingAdapter()
    a.seed("proj-short", [1000.0, 1100.0, 1200.0])   # only 3 months
    return a


@pytest.fixture
def adapter_empty() -> InMemoryBillingAdapter:
    return InMemoryBillingAdapter()


# ── Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forecast_auto_returns_201(adapter_ok):
    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={
                "project_id": "proj-abc",
                "horizon":    3,
                "algorithm":  "auto",
            })
    assert resp.status_code == 201
    body = resp.json()
    assert body["project_id"] == "proj-abc"
    assert len(body["points"]) == 3
    assert body["meta"]["algorithm_used"] in ("linear", "moving_avg", "exponential", "holt")


@pytest.mark.asyncio
async def test_forecast_forced_linear(adapter_ok):
    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={
                "project_id": "proj-abc",
                "horizon":    2,
                "algorithm":  "linear",
            })
    assert resp.status_code == 201
    assert resp.json()["meta"]["algorithm_used"] == "linear"


@pytest.mark.asyncio
async def test_forecast_forced_holt(adapter_ok):
    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={
                "project_id": "proj-abc",
                "algorithm":  "holt",
            })
    assert resp.status_code == 201
    assert resp.json()["meta"]["algorithm_used"] == "holt"


@pytest.mark.asyncio
async def test_forecast_404_unknown_project(adapter_empty):
    with _make_adapter_patch(adapter_empty):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={"project_id": "ghost"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_forecast_422_insufficient_data(adapter_short):
    """Rule 1: < 4 months → 422 INSUFFICIENT_DATA."""
    with _make_adapter_patch(adapter_short):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={"project_id": "proj-short"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_forecast_422_project_id_too_short(adapter_ok):
    """Pydantic rejects project_id < 3 chars before any adapter call."""
    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={"project_id": "ab"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_forecast_ci_bounds_valid(adapter_ok):
    """lower_ci ≤ predicted ≤ upper_ci, lower_ci ≥ 0 for all points."""
    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={
                "project_id": "proj-abc",
                "horizon":    3,
            })
    for pt in resp.json()["points"]:
        assert pt["lower_ci"] <= pt["predicted"] <= pt["upper_ci"]
        assert pt["lower_ci"] >= 0.0


@pytest.mark.asyncio
async def test_forecast_horizon_1_to_12(adapter_ok):
    """Horizon boundary values: 1 and 12 both work."""
    for h in (1, 12):
        with _make_adapter_patch(adapter_ok):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/api/v1/forecast", json={
                    "project_id": "proj-abc",
                    "horizon":    h,
                })
        assert resp.status_code == 201
        assert len(resp.json()["points"]) == h


@pytest.mark.asyncio
async def test_forecast_horizon_out_of_range(adapter_ok):
    """horizon=0 and horizon=13 are rejected by Pydantic."""
    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post("/api/v1/forecast", json={"project_id": "proj-abc", "horizon": 0})
            r2 = await c.post("/api/v1/forecast", json={"project_id": "proj-abc", "horizon": 13})
    assert r1.status_code == 422
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_forecast_month_labels_are_future(adapter_ok):
    """Every YYYY-MM label in points must be after today."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc)

    with _make_adapter_patch(adapter_ok):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/v1/forecast", json={
                "project_id": "proj-abc",
                "horizon":    3,
            })

    for pt in resp.json()["points"]:
        year, month = map(int, pt["month"].split("-"))
        assert (year, month) > (today.year, today.month)
