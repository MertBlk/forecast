"""
Linear Projection — Ordinary Least Squares.

y = m*x + b
m = [n*Σ(xy) - Σx*Σy] / [n*Σx² - (Σx)²]
b = ȳ - m*x̄
x = 0, 1, 2, ..., n-1  (month index, not calendar dates)
"""


def linear_forecast(values: list[float], horizon: int = 3) -> dict:
    """
    Fit a straight line through historical costs and project forward.

    Args:
        values:  chronological monthly costs, oldest first. Min 2 required.
        horizon: number of future months to predict (1–12).

    Returns dict with keys:
        predictions  list[float]  — future costs, length = horizon
        slope        float
        intercept    float
        r_squared    float        — 1.0=perfect fit, ≥0.8 good, <0.5 weak
    """
    n = len(values)
    if n < 2:
        raise ValueError(f"linear forecast requires ≥ 2 data points, got {n}")

    # x-axis: 0, 1, 2, …, n-1
    xs = list(range(n))

    sum_x  = sum(xs)
    sum_y  = sum(values)
    sum_xy = sum(x * y for x, y in zip(xs, values))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        # All x values identical → can't fit a line (shouldn't happen with 0..n-1)
        raise ValueError("degenerate x values — cannot fit linear model")

    slope     = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n  # ȳ - m*x̄

    # R² = 1 - SS_res / SS_tot
    y_mean  = sum_y / n
    ss_tot  = sum((y - y_mean) ** 2 for y in values)
    ss_res  = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
    # Guard against flat series (ss_tot == 0 → perfect fit by definition)
    r_squared = 1.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)

    # Predict months n, n+1, ..., n+horizon-1
    predictions = [
        max(0.0, slope * (n + h) + intercept)  # cost cannot be negative
        for h in range(horizon)
    ]

    return {
        "predictions": predictions,
        "slope":       slope,
        "intercept":   intercept,
        "r_squared":   round(r_squared, 4),
    }
