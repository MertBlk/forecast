"""
Auto-select engine: walk-forward validation across candidate algorithms,
pick the one with the lowest MAPE.

Data-volume selection logic (spec):
  < 4 months  → ValueError (422 — never forecast)       Rule 1
  4–6 months  → linear, exponential only
  6–12 months → linear, exponential, moving_avg, holt
  12–24 months→ linear, exponential, moving_avg, holt
  ≥ 24 months → all including seasonal

Walk-forward validation:
  Train on months 0..t-1, predict month t, repeat for last N folds.
  NEVER shuffle — Rule 2.
"""
from app.core.algorithms.confidence import compute_confidence_intervals
from app.core.algorithms.exponential import exponential_forecast
from app.core.algorithms.holt import holt_forecast
from app.core.algorithms.linear import linear_forecast
from app.core.algorithms.metrics import mape as calc_mape
from app.core.algorithms.moving_avg import moving_average_forecast
from app.core.algorithms.seasonal import seasonal_forecast

# Number of walk-forward folds used for MAPE estimation
_VALIDATION_FOLDS = 3


def _walk_forward_mape(
    values: list[float],
    predict_fn,          # callable(values, horizon=1) → dict with "predictions"
) -> float:
    """
    Hold out the last _VALIDATION_FOLDS months one at a time.
    Train on everything before the held-out month, predict 1 step.
    Return average MAPE across folds.

    Example with 3 folds and 10 months [0..9]:
      fold 1: train=[0..6], predict=7
      fold 2: train=[0..7], predict=8
      fold 3: train=[0..8], predict=9
    """
    n = len(values)
    actuals, predictions = [], []

    for fold in range(_VALIDATION_FOLDS, 0, -1):
        split = n - fold             # train up to this index (exclusive)
        train = values[:split]
        actual = values[split]       # the month we're predicting

        try:
            result = predict_fn(train, horizon=1)
            pred = result["predictions"][0]
        except (ValueError, ZeroDivisionError):
            # If algorithm can't run on this fold, skip it
            continue

        actuals.append(actual)
        predictions.append(pred)

    if not actuals:
        raise ValueError("walk-forward validation produced no valid folds")

    return calc_mape(actuals, predictions)


def _candidates_for(n_months: int) -> list[tuple[str, callable]]:
    """Return (name, callable) pairs allowed for this data volume."""
    # Rule 1 enforced at the API layer, but we guard here too
    if n_months < 4:
        raise ValueError(
            f"insufficient data: {n_months} months. Need ≥ 4 to forecast."
        )

    base = [
        ("linear",      lambda v, horizon: linear_forecast(v, horizon)),
        ("exponential", lambda v, horizon: exponential_forecast(v, horizon)),
    ]
    extended = base + [
        ("moving_avg",  lambda v, horizon: moving_average_forecast(v, horizon)),
        ("holt",        lambda v, horizon: holt_forecast(v, horizon)),
    ]
    full = extended + [
        ("seasonal",    lambda v, horizon: seasonal_forecast(v, horizon)),
    ]

    if n_months < 6:
        return base
    if n_months < 24:
        return extended
    return full


def auto_select_forecast(
    values: list[float],
    horizon: int = 3,
) -> dict:
    """
    Run walk-forward validation on all eligible algorithms and return
    the winner (lowest MAPE) together with its predictions and CI.

    Args:
        values:  chronological monthly costs, oldest first.
        horizon: months to forecast (1–12).

    Returns dict with keys:
        algorithm    str          — winning algorithm name
        predictions  list[float]
        mape         float        — winner's walk-forward MAPE %
        all_scores   dict         — {algorithm: mape} for every candidate
        points       list[dict]   — predictions + CI per horizon step
    """
    n = len(values)
    candidates = _candidates_for(n)   # raises ValueError if n < 4

    scores: dict[str, float] = {}
    errors: dict[str, str]   = {}

    for name, fn in candidates:
        try:
            scores[name] = _walk_forward_mape(values, fn)
        except Exception as exc:
            # One algorithm failing shouldn't abort the whole request
            errors[name] = str(exc)

    if not scores:
        raise ValueError(
            f"all algorithms failed. Errors: {errors}"
        )

    # Winner = lowest MAPE (most accurate on held-out data)
    best_name = min(scores, key=scores.__getitem__)
    best_mape = scores[best_name]

    # Re-run winner on full history to get the actual forecast
    best_fn   = dict(candidates)[best_name]
    best_result = best_fn(values, horizon)

    # Attach confidence intervals to each prediction point
    points = compute_confidence_intervals(
        predictions=best_result["predictions"],
        mape_score=best_mape,
    )

    return {
        "algorithm":  best_name,
        "predictions": best_result["predictions"],
        "mape":        round(best_mape, 4),
        "all_scores":  {k: round(v, 4) for k, v in scores.items()},
        "points":      points,
    }
