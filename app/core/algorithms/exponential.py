"""
Simple Exponential Smoothing.

S_t = alpha * x_t + (1-alpha) * S_{t-1}
Init: S_0 = x_0
Forecast: all future steps = last smoothed value (flat — no trend).

Alpha guide:
  0.1–0.3 → slow adaptation, stable billing
  0.4–0.6 → balanced
  0.7–0.9 → fast adaptation, volatile customers
"""


def exponential_forecast(
    values: list[float],
    horizon: int = 3,
    alpha: float = 0.3,
) -> dict:
    """
    Args:
        values:  chronological monthly costs, oldest first. Min 2 required.
        horizon: months to forecast.
        alpha:   smoothing factor, must be in (0, 1) exclusive.

    Returns dict with keys:
        predictions      list[float]
        final_smoothed   float  — S_t at the last historical observation
        alpha            float
    """
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    n = len(values)
    if n < 2:
        raise ValueError(f"exponential smoothing requires ≥ 2 data points, got {n}")

    smoothed = values[0]  # S_0 = x_0  (warm-start with first observation)

    for x in values[1:]:
        # Recurrence relation: blend current observation with previous smoothed level
        smoothed = alpha * x + (1 - alpha) * smoothed

    # Flat forecast — simple exponential smoothing carries no trend term.
    # Every future step is the same last smoothed value.
    predictions = [max(0.0, smoothed)] * horizon

    return {
        "predictions":    predictions,
        "final_smoothed": smoothed,
        "alpha":          alpha,
    }
