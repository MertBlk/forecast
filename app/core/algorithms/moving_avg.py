"""
Moving Average forecast — Simple (SMA) and Weighted (WMA).

SMA: MA_t = (x_{t-N+1} + ... + x_t) / N
WMA: WMA_t = (1*x_{t-N+1} + ... + N*x_t) / Σw,  Σw = N*(N+1)/2

Each predicted value is appended to the series before computing the next
step — so multi-step forecasts use their own outputs as inputs.

Window guide:
  N=3  → fast adaptation, noisy customers
  N=6  → balanced (default)
  N=12 → stable, large/mature customers
"""


def moving_average_forecast(
    values: list[float],
    horizon: int = 3,
    window: int = 6,
    weighted: bool = False,
) -> dict:
    """
    Args:
        values:   chronological monthly costs, oldest first.
        horizon:  months to forecast.
        window:   N — look-back window size.
        weighted: False → SMA, True → WMA (recent months count more).

    Returns dict with keys:
        predictions  list[float]
        window       int
        weighted     bool
    """
    if window > len(values):
        raise ValueError(
            f"window ({window}) > number of data points ({len(values)}). "
            "Provide more history or reduce window size."
        )

    # Gauss sum — denominator for WMA
    weight_sum = window * (window + 1) / 2  # only used when weighted=True

    series = list(values)  # we'll append predictions as we go

    predictions: list[float] = []
    for _ in range(horizon):
        # Take the last `window` values as the current window
        window_vals = series[-window:]

        if weighted:
            # Weight 1 for oldest, 2 for next, …, N for most recent
            wma = sum((i + 1) * v for i, v in enumerate(window_vals)) / weight_sum
            next_val = max(0.0, wma)
        else:
            next_val = max(0.0, sum(window_vals) / window)

        predictions.append(next_val)
        series.append(next_val)  # use our own prediction as next window input

    return {
        "predictions": predictions,
        "window":      window,
        "weighted":    weighted,
    }
