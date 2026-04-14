"""
Request and response Pydantic models for POST /api/v1/forecast/.
Pydantic v2 syntax throughout.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────

class AlgorithmChoice(str, Enum):
    auto        = "auto"
    linear      = "linear"
    moving_avg  = "moving_avg"
    exponential = "exponential"
    holt        = "holt"
    seasonal    = "seasonal"


# ── Request ──────────────────────────────────────────────────────────

class ForecastRequest(BaseModel):
    project_id: str = Field(
        ...,                          # required — no default
        min_length=3,
        description="Project identifier (min 3 chars)",
    )
    horizon: int = Field(
        default=3,
        ge=1,                         # ge = greater-or-equal
        le=12,
        description="Months to forecast (1–12)",
    )
    history_months: int = Field(
        default=12,
        ge=3,
        le=36,
        description="Months of history to load (3–36)",
    )
    algorithm: AlgorithmChoice = Field(
        default=AlgorithmChoice.auto,
        description="Forecast algorithm. 'auto' picks the best by MAPE.",
    )
    include_breakdown: bool = Field(
        default=False,
        description="Include per-VM-type cost breakdown in each point",
    )
    currency: str = Field(
        default="USD",
        description="Display currency (currently informational only)",
    )


# ── Response sub-models ──────────────────────────────────────────────

class ForecastPoint(BaseModel):
    """One predicted month."""
    month:        str           # "YYYY-MM"
    predicted:    float         # USD
    lower_ci:     float         # 90% lower bound
    upper_ci:     float         # 90% upper bound
    vm_breakdown: Optional[list[dict]] = None  # only when include_breakdown=True


class ForecastMeta(BaseModel):
    algorithm_used:  str
    mape_score:      Optional[float] = None   # null when forced algorithm has no MAPE
    history_used:    int                      # actual months of data used
    vm_count_latest: int                      # VMs in the most recent month
    cached:          bool = False             # True if served from Redis


# ── Response ─────────────────────────────────────────────────────────

class ForecastResponse(BaseModel):
    forecast_id:  UUID
    project_id:   str
    generated_at: datetime
    meta:         ForecastMeta
    points:       list[ForecastPoint]


# ── Error body (used by exception handlers) ──────────────────────────

class ErrorResponse(BaseModel):
    error_code: str    # e.g. "INSUFFICIENT_DATA"
    message:    str
    detail:     Optional[str] = None
