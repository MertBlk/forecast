from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.analytics import router as analytics_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.health import router as health_router
from app.config import settings
from app.db.adapters.clickhouse import ClickHouseAdapter
from app.db.session import engine
from app.services.cache import ForecastCache


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise Redis cache + ClickHouse adapter.
    Shutdown: close all connection pools cleanly.
    """
    app.state.cache      = ForecastCache(settings.redis_url)
    app.state.clickhouse = ClickHouseAdapter()   # lazy — connects on first query
    yield
    await app.state.cache.close()
    await app.state.clickhouse.close()
    await engine.dispose()


app = FastAPI(
    title="Forecast Service",
    description="VM cost forecasting microservice",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Routers ──────────────────────────────────────────────────────────
app.include_router(health_router,   prefix="/api/v1")
app.include_router(forecast_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
