"""
Holt's Double Exponential Smoothing (trend-aware).

Level: L_t = alpha * x_t + (1-alpha) * (L_{t-1} + T_{t-1})
Trend: T_t = beta  * (L_t - L_{t-1}) + (1-beta) * T_{t-1}
Forecast h steps ahead: F_{t+h} = L_t + h * T_t

Init: L_0 = x_0,  T_0 = x_1 - x_0

Parameter guide:
  alpha=0.3, beta=0.1 → stable trend (recommended default)
  alpha=0.4, beta=0.2 → more reactive
  Small beta preferred — cloud billing trends change slowly.
"""


def holt_forecast(
    values: list[float],
    horizon: int = 3,
    alpha: float = 0.3,
    beta: float = 0.1,
) -> dict:
    """
    Args:
        values:  chronological monthly costs, oldest first. Min 2 required.
        horizon: months to forecast (1–12).
        alpha:   level smoothing, must be in (0, 1).
        beta:    trend smoothing, must be in (0, 1).

    Returns dict with keys:
        predictions   list[float]
        final_level   float
        final_trend   float
    """
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if not (0 < beta < 1):
        raise ValueError(f"beta must be in (0, 1), got {beta}")
    n = len(values)
    if n < 2:
        raise ValueError(f"Holt requires ≥ 2 data points, got {n}")

    # Initialise level and trend from the first two observations
    level = values[0]
    trend = values[1] - values[0]

    for x in values[1:]:
        prev_level = level
        # Update level: blend observation with extrapolated previous level+trend
        level = alpha * x + (1 - alpha) * (prev_level + trend)
        # Update trend: blend new slope with previous trend
        trend = beta * (level - prev_level) + (1 - beta) * trend

    # Project forward: F_{t+h} = L_t + h * T_t
    predictions = [
        max(0.0, level + h * trend)  # cost cannot be negative
        for h in range(1, horizon + 1)
    ]

    return {
        "predictions": predictions,
        "final_level": level,
        "final_trend": trend,
    }
