from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.analytics import router as analytics_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.health import router as health_router
from app.config import settings
from app.db.adapters.clickhouse import ClickHouseAdapter
from app.db.session import engine
from app.services.cache import ForecastCache

logger = logging.getLogger(__name__)


class MockForecastCache:
    """Fallback mock cache when Redis is unavailable."""
    async def get_or_compute(self, project_id, horizon, algorithm, compute_fn):
        result = await compute_fn()
        return result, False  # always cache miss

    async def close(self):
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise Redis cache + ClickHouse adapter.
    Shutdown: close all connection pools cleanly.
    """
    try:
        app.state.cache = ForecastCache(settings.redis_url)
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}), using mock cache")
        app.state.cache = MockForecastCache()

    app.state.clickhouse = ClickHouseAdapter()   # lazy — connects on first query
    yield

    if hasattr(app.state.cache, 'close'):
        await app.state.cache.close()
    if hasattr(app.state, 'clickhouse'):
        await app.state.clickhouse.close()
    await engine.dispose()


app = FastAPI(
    title="Forecast Service",
    description="VM cost forecasting microservice",
    version="0.1.0",
    lifespan=lifespan,
)

_ui_dir = Path(__file__).resolve().parent / "ui"
_static_dir = _ui_dir / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def ui_index():
    return FileResponse(_ui_dir / "index.html")

# ── Routers ──────────────────────────────────────────────────────────
app.include_router(health_router,   prefix="/api/v1")
app.include_router(forecast_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
