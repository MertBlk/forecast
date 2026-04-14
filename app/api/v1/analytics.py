"""
Analytic endpoints — all queries run against ClickHouse.

GET /api/v1/analytics/cross-project-summary
GET /api/v1/analytics/vm-type-trend/{project_id}
GET /api/v1/analytics/forecast-accuracy/{project_id}

Why ClickHouse (not Postgres) for these?
  All three are aggregation queries across potentially millions of rows.
  ClickHouse columnar storage + vectorised execution makes them
  5–50× faster than the equivalent Postgres GROUP BY.

Rule 3: ClickHouseAdapter uses run_in_executor internally, so these
        async handlers never block the event loop.
Rule 8: DB errors are caught, logged, and returned as 503.
"""
import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.db.adapters.clickhouse import ClickHouseAdapter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _get_ch(request: Request) -> ClickHouseAdapter:
    """Pull the shared ClickHouseAdapter from app.state."""
    return request.app.state.clickhouse


# ── 1. Cross-project cost summary ────────────────────────────────────

@router.get("/cross-project-summary")
async def cross_project_summary(
    request: Request,
    start_month: date = Query(..., description="Start month (YYYY-MM-DD, use 1st of month)"),
    end_month:   date = Query(..., description="End month (YYYY-MM-DD, use 1st of month)"),
):
    """
    Total cost + hours per project for a date range.
    Useful for finance dashboards and billing reports.

    Example: GET /api/v1/analytics/cross-project-summary
             ?start_month=2026-01-01&end_month=2026-03-01
    """
    if start_month > end_month:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_month must be <= end_month",
        )

    ch = _get_ch(request)
    try:
        rows = await ch.get_cross_project_summary(start_month, end_month)
    except Exception as exc:
        logger.error("cross_project_summary failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClickHouse unavailable",
        )

    return {
        "start_month": start_month.isoformat(),
        "end_month":   end_month.isoformat(),
        "projects":    rows,
    }


# ── 2. VM type cost trend ─────────────────────────────────────────────

@router.get("/vm-type-trend/{project_id}")
async def vm_type_trend(
    project_id: str,
    request: Request,
    months: int = Query(default=12, ge=1, le=36, description="How many months of history"),
):
    """
    Monthly cost broken down by VM type for a specific project.
    Useful for understanding which VM types are driving cost growth.

    Example: GET /api/v1/analytics/vm-type-trend/proj-abc?months=6
    """
    ch = _get_ch(request)
    try:
        rows = await ch.get_vm_type_trend(project_id, months)
    except Exception as exc:
        logger.error("vm_type_trend failed for %s: %s", project_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClickHouse unavailable",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No data for project '{project_id}'",
        )

    return {
        "project_id": project_id,
        "months":     months,
        "trend":      rows,
    }


# ── 3. Forecast accuracy history ──────────────────────────────────────

@router.get("/forecast-accuracy/{project_id}")
async def forecast_accuracy(
    project_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="Max forecasts to return"),
):
    """
    Historical forecast results with MAPE scores for a project.
    Use this to track whether forecast accuracy is improving over time.

    MAPE interpretation:
      < 5%  → Excellent    10–20% → Acceptable
      5–10% → Good         > 20%  → Weak — investigate
    """
    ch = _get_ch(request)
    try:
        rows = await ch.get_forecast_accuracy_history(project_id, limit)
    except Exception as exc:
        logger.error("forecast_accuracy failed for %s: %s", project_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClickHouse unavailable",
        )

    return {
        "project_id": project_id,
        "forecasts":  rows,
    }
