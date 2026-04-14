"""
Error metrics: MAE, RMSE, MAPE.
Pure functions — no side effects, no I/O. Independently testable.
"""


def mae(actuals: list[float], predicted: list[float]) -> float:
    """Mean Absolute Error — same unit as input (USD). Equal penalty for all errors."""
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must be the same length")
    n = len(actuals)
    if n == 0:
        raise ValueError("need at least one data point")
    return sum(abs(a - p) for a, p in zip(actuals, predicted)) / n


def rmse(actuals: list[float], predicted: list[float]) -> float:
    """Root Mean Square Error — penalises large errors more than MAE."""
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must be the same length")
    n = len(actuals)
    if n == 0:
        raise ValueError("need at least one data point")
    return (sum((a - p) ** 2 for a, p in zip(actuals, predicted)) / n) ** 0.5


def mape(actuals: list[float], predicted: list[float]) -> float:
    """
    Mean Absolute Percentage Error — unit-free %, most interpretable.
    Pairs where actual == 0 are skipped (division by zero).

    Interpretation:
      < 5%  → Excellent   10–20% → Acceptable
      5–10% → Good        > 20%  → Weak
    """
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must be the same length")

    # Only include pairs where actual is non-zero
    valid = [(a, p) for a, p in zip(actuals, predicted) if a != 0]
    if not valid:
        raise ValueError("no non-zero actuals — MAPE undefined")

    return sum(abs(a - p) / abs(a) for a, p in valid) / len(valid) * 100
