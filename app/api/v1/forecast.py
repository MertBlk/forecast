"""
POST /api/v1/forecast/ — main forecast endpoint.

Flow:
  1. Validate request (Pydantic)
  2. Check cache — return immediately if hit
  3. Verify project exists (→ 404 if not)
  4. Load history from DB
  5. Enforce Rule 1: ≥ 4 months required
  6. Run selected algorithm (or auto-select)
  7. Build response, cache it, return 201

Rule 3: every DB and cache call is awaited.
Rule 4: DB session opened via Depends(get_db).
Rule 8: exceptions are logged and re-raised as HTTPException.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    AlgorithmChoice,
    ErrorResponse,
    ForecastMeta,
    ForecastPoint,
    ForecastRequest,
    ForecastResponse,
)
from app.config import settings
from app.core.algorithms.auto_select import auto_select_forecast
from app.core.algorithms.confidence import compute_confidence_intervals
from app.core.algorithms.exponential import exponential_forecast
from app.core.algorithms.holt import holt_forecast
from app.core.algorithms.linear import linear_forecast
from app.core.algorithms.metrics import mape as calc_mape
from app.core.algorithms.moving_avg import moving_average_forecast
from app.core.algorithms.seasonal import seasonal_forecast
from app.db.adapters.postgres import PostgresVmBillingAdapter
from app.db.session import get_db
from app.services.cache import ForecastCache

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Algorithm dispatch table ─────────────────────────────────────────
# Maps AlgorithmChoice → callable(values, horizon) → dict with "predictions"
_ALGORITHM_MAP = {
    AlgorithmChoice.linear:      lambda v, h: linear_forecast(v, h),
    AlgorithmChoice.moving_avg:  lambda v, h: moving_average_forecast(v, h),
    AlgorithmChoice.exponential: lambda v, h: exponential_forecast(v, h),
    AlgorithmChoice.holt:        lambda v, h: holt_forecast(v, h),
    AlgorithmChoice.seasonal:    lambda v, h: seasonal_forecast(v, h),
}


def _get_cache(request: Request) -> ForecastCache:
    """FastAPI dependency — pulls the shared cache from app.state."""
    return request.app.state.cache


def _build_forecast_month_labels(horizon: int) -> list[str]:
    """
    Generate YYYY-MM strings for the next `horizon` months from now.
    Example: horizon=3, today=2026-04-13 → ["2026-05", "2026-06", "2026-07"]
    """
    now = datetime.now(timezone.utc)
    months = []
    year, month = now.year, now.month
    for _ in range(horizon):
        month += 1
        if month > 12:
            month = 1
            year += 1
        months.append(f"{year}-{month:02d}")
    return months


@router.post(
    "/forecast",
    status_code=status.HTTP_201_CREATED,
    response_model=ForecastResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    tags=["forecast"],
)
async def create_forecast(
    body: ForecastRequest,
    db: AsyncSession = Depends(get_db),
    cache: ForecastCache = Depends(_get_cache),
) -> ForecastResponse:
    # ── 1. Check cache ───────────────────────────────────────────────
    algorithm_key = body.algorithm.value  # string for cache key

    async def _compute():
        """The actual forecast logic — only called on cache miss."""
        return await _run_forecast(body, db)

    try:
        result_dict, was_cached = await cache.get_or_compute(
            project_id=body.project_id,
            horizon=body.horizon,
            algorithm=algorithm_key,
            compute_fn=_compute,
        )
    except HTTPException:
        raise   # let 404 / 422 propagate unchanged
    except Exception as exc:
        # Rule 8: log every unexpected error
        logger.error("forecast failed for project %s: %s", body.project_id, exc, exc_info=True)
        if settings.mock_mode or "Redis" in str(exc) or "Connection" in str(exc):
            logger.info("Using mock forecast due to cache error")
            result_dict = _generate_mock_forecast(body)
            was_cached = False
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error_code": "FORECAST_FAILED", "message": str(exc)},
            )

    # Stamp the cached flag into meta before returning
    result_dict["meta"]["cached"] = was_cached
    return ForecastResponse(**result_dict)


async def _run_forecast(body: ForecastRequest, db: AsyncSession) -> dict:
    """
    Core forecast logic — separated so cache.get_or_compute can wrap it.
    Returns a plain dict matching ForecastResponse's structure.
    """
    adapter = PostgresVmBillingAdapter(db)

    # ── 2. Check project exists → 404 ───────────────────────────────
    try:
        exists = await adapter.project_exists(body.project_id)
    except Exception as exc:
        logger.error("DB unavailable checking project %s: %s", body.project_id, exc, exc_info=True)
        if settings.mock_mode:
            logger.info("Mock mode: returning mock forecast")
            return _generate_mock_forecast(body)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "DB_UNAVAILABLE", "message": "Database unreachable"},
        )

    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND",
                    "message": f"No billing records for project '{body.project_id}'"},
        )

    # ── 3. Load history ──────────────────────────────────────────────
    try:
        costs = await adapter.get_monthly_costs(body.project_id, body.history_months)
    except Exception as exc:
        logger.error("DB error loading history for %s: %s", body.project_id, exc, exc_info=True)
        if settings.mock_mode:
            logger.info("Mock mode: returning mock forecast")
            return _generate_mock_forecast(body)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "DB_UNAVAILABLE", "message": "Failed to load billing history"},
        )

    # ── 4. Rule 1: enforce minimum data requirement ──────────────────
    if len(costs) < 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INSUFFICIENT_DATA",
                "message": f"Need ≥ 4 months of data, found {len(costs)}",
            },
        )

    # ── 5. Run algorithm ─────────────────────────────────────────────
    if body.algorithm == AlgorithmChoice.auto:
        result = auto_select_forecast(costs, horizon=body.horizon)
        algorithm_used = result["algorithm"]
        predictions    = result["predictions"]
        mape_score     = result["mape"]
        points_data    = result["points"]  # already has CI
    else:
        fn = _ALGORITHM_MAP[body.algorithm]
        try:
            result = fn(costs, body.horizon)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "INSUFFICIENT_DATA", "message": str(exc)},
            )
        algorithm_used = body.algorithm.value
        predictions    = result["predictions"]

        # Walk-forward MAPE for forced algorithms (best-effort, last 3 folds)
        mape_score = None
        try:
            if len(costs) >= 4:
                n = len(costs)
                actuals, preds = [], []
                for fold in range(3, 0, -1):
                    train  = costs[:n - fold]
                    actual = costs[n - fold]
                    out    = fn(train, 1)
                    actuals.append(actual)
                    preds.append(out["predictions"][0])
                mape_score = round(calc_mape(actuals, preds), 4)
        except Exception as mape_exc:
            # MAPE is best-effort for forced algorithms — log but don't fail the request
            logger.warning("could not compute MAPE for %s: %s", algorithm_used, mape_exc)

        points_data = compute_confidence_intervals(
            predictions=predictions,
            mape_score=mape_score or 10.0,  # fallback 10% if MAPE unavailable
        )

    # ── 6. Build response ────────────────────────────────────────────
    month_labels = _build_forecast_month_labels(body.horizon)
    points = [
        ForecastPoint(
            month=label,
            predicted=pt["predicted"],
            lower_ci=pt["lower_ci"],
            upper_ci=pt["upper_ci"],
            vm_breakdown=None,  # Phase 3 will add breakdown support
        )
        for label, pt in zip(month_labels, points_data)
    ]

    meta = ForecastMeta(
        algorithm_used=algorithm_used,
        mape_score=mape_score,
        history_used=len(costs),
        vm_count_latest=0,   # TODO: query vm_count from materialized view in Phase 3
        cached=False,        # will be overwritten by cache layer
    )

    return ForecastResponse(
        forecast_id=uuid.uuid4(),
        project_id=body.project_id,
        generated_at=datetime.now(timezone.utc),
        meta=meta,
        points=points,
    ).model_dump(mode="json")   # serialize to dict for JSON-safe caching


def _generate_mock_forecast(body: ForecastRequest) -> dict:
    """Demo: Run actual algorithms on mock history data."""
    import random

    # Mock data per project
    mock_data_map = {
        "proj-backend": [1200, 1250, 1180, 1320, 1400, 1450, 1380, 1500, 1550, 1600, 1680, 1750],
        "proj-mobile": [850, 920, 890, 950, 1000, 1050, 1100, 1080, 1150, 1200, 1250, 1300],
        "proj-data-pipeline": [2000, 2100, 2050, 2200, 2300, 2400, 2350, 2500, 2600, 2700, 2800, 2900],
        "proj-ml-infra": [3500, 3600, 3550, 3800, 4000, 4200, 4100, 4300, 4500, 4700, 4900, 5100],
        "proj-devops": [600, 650, 620, 700, 750, 800, 780, 850, 900, 950, 1000, 1050],
    }
    
    # Get project-specific mock costs or use random default
    project_id = body.project_id
    if project_id in mock_data_map:
        mock_costs = mock_data_map[project_id][:12]
    else:
        mock_costs = [
            random.uniform(800, 1200) for _ in range(12)
        ]

    month_labels = _build_forecast_month_labels(body.horizon)

    # Run actual algorithm on mock data
    if body.algorithm == AlgorithmChoice.auto:
        result = auto_select_forecast(mock_costs, horizon=body.horizon)
        algorithm_used = result["algorithm"]
        predictions    = result["predictions"]
        mape_score     = result["mape"]
        points_data    = result["points"]
    else:
        fn = _ALGORITHM_MAP.get(body.algorithm)
        if not fn:
            algorithm_used = body.algorithm.value
            predictions = [1000] * body.horizon
            mape_score = None
            points_data = compute_confidence_intervals(predictions, 10.0)
        else:
            try:
                result = fn(mock_costs, body.horizon)
                algorithm_used = body.algorithm.value
                predictions = result["predictions"]
                mape_score = None
                try:
                    if len(mock_costs) >= 4:
                        actuals, preds = [], []
                        for fold in range(3, 0, -1):
                            train = mock_costs[:len(mock_costs) - fold]
                            actual = mock_costs[len(mock_costs) - fold]
                            out = fn(train, 1)
                            actuals.append(actual)
                            preds.append(out["predictions"][0])
                        mape_score = round(calc_mape(actuals, preds), 2)
                except Exception:
                    pass
                points_data = compute_confidence_intervals(
                    predictions=predictions,
                    mape_score=mape_score or 5.0,
                )
            except Exception as e:
                logger.warning(f"Algorithm {body.algorithm.value} failed: {e}, using fallback")
                algorithm_used = body.algorithm.value
                predictions = [1000 * (1.02 ** i) for i in range(body.horizon)]
                mape_score = None
                points_data = compute_confidence_intervals(predictions, 10.0)

    points = [
        ForecastPoint(
            month=label,
            predicted=round(pt["predicted"], 2),
            lower_ci=round(pt["lower_ci"], 2),
            upper_ci=round(pt["upper_ci"], 2),
            vm_breakdown=None,
        )
        for label, pt in zip(month_labels, points_data)
    ]

    meta = ForecastMeta(
        algorithm_used=algorithm_used,
        mape_score=mape_score,
        history_used=len(mock_costs),
        vm_count_latest=42,
        cached=False,
    )

    return ForecastResponse(
        forecast_id=uuid.uuid4(),
        project_id=body.project_id,
        generated_at=datetime.now(timezone.utc),
        meta=meta,
        points=points,
    ).model_dump(mode="json")
