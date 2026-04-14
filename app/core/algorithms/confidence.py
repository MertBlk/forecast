"""
Confidence interval calculator.

margin   = predicted × (mape/100) × base_multiplier × sqrt(h)
lower_ci = max(0.0, predicted - margin)   # cost cannot go negative
upper_ci = predicted + margin

sqrt(h): uncertainty grows sub-linearly with horizon (random-walk model).
base_multiplier 1.5 → ~90% CI (default)
base_multiplier 2.0 → conservative, use for budget alerting
"""
import math


def compute_confidence_intervals(
    predictions: list[float],
    mape_score: float,
    base_multiplier: float = 1.5,
) -> list[dict]:
    """
    Returns one dict per horizon step with keys: predicted, lower_ci, upper_ci.

    Args:
        predictions:     list of predicted USD values, length = horizon
        mape_score:      MAPE % from walk-forward validation
        base_multiplier: 1.5 (default ~90 CI) or 2.0 (conservative)
    """
    if mape_score < 0:
        raise ValueError("mape_score must be >= 0")

    results = []
    for h, predicted in enumerate(predictions, start=1):  # h = 1, 2, 3, ...
        # Margin grows with sqrt(h) — each extra month adds less uncertainty
        margin = predicted * (mape_score / 100) * base_multiplier * math.sqrt(h)
        results.append({
            "predicted":  round(predicted, 4),
            "lower_ci":   round(max(0.0, predicted - margin), 4),  # floor at 0
            "upper_ci":   round(predicted + margin, 4),
        })
    return results
