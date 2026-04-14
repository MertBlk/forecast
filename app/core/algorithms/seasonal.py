"""
Seasonal Naive forecast (monthly seasonality, period=12).

Logic:
  Predicted value for month t+h = value from exactly 12 months ago + trend adjustment.

  trend_per_month = (mean of last 12 months) - (mean of months 13–24)
  F_{t+h} = x_{t+h-12} + h * trend_per_month

Why "naive seasonal":
  No ML, no statsmodels. We capture the 12-month cycle directly from
  the raw data — good enough for cloud billing which has real seasonal
  patterns (year-end budget spikes, Q1 dips, etc.).

Rule: requires ≥ 24 months of data (spec: seasonal only when >= 24 months).
"""


def seasonal_forecast(
    values: list[float],
    horizon: int = 3,
) -> dict:
    """
    Args:
        values:  chronological monthly costs, oldest first. Min 24 required.
        horizon: months to forecast (1–12).

    Returns dict with keys:
        predictions     list[float]
        trend_per_month float       — average monthly drift
    """
    n = len(values)
    if n < 24:
        raise ValueError(
            f"seasonal forecast requires ≥ 24 data points, got {n}. "
            "Use a different algorithm for shorter histories."
        )

    # Compute a simple trend: average of the last 12 months vs the 12 before that
    last_12  = values[-12:]
    prev_12  = values[-24:-12]
    trend_per_month = (sum(last_12) / 12 - sum(prev_12) / 12) / 12
    # Dividing by 12 again spreads the annual drift across individual months

    predictions: list[float] = []
    for h in range(1, horizon + 1):
        # Same month last year (index from the end of the series)
        base = values[-(12 - (h - 1)) if h <= 12 else 0]
        # Apply accumulated trend drift
        predicted = max(0.0, base + h * trend_per_month)
        predictions.append(predicted)

    return {
        "predictions":     predictions,
        "trend_per_month": trend_per_month,
    }
