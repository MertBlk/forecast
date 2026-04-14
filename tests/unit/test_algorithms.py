"""
Unit tests for all forecast algorithms + metrics + confidence.
Zero DB connections — pure Python functions only.
"""
import math
import pytest

from app.core.algorithms.confidence import compute_confidence_intervals
from app.core.algorithms.exponential import exponential_forecast
from app.core.algorithms.holt import holt_forecast
from app.core.algorithms.linear import linear_forecast
from app.core.algorithms.metrics import mae, mape, rmse
from app.core.algorithms.moving_avg import moving_average_forecast
from app.core.algorithms.seasonal import seasonal_forecast


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def flat_series():
    """Perfectly flat billing: $1000 every month for 12 months."""
    return [1000.0] * 12


@pytest.fixture
def trending_up():
    """Linear growth: $1000, $1100, $1200, …"""
    return [1000.0 + i * 100 for i in range(12)]


@pytest.fixture
def long_series():
    """24 months of data — required for seasonal."""
    return [1000.0 + i * 50 for i in range(24)]


# ── Metrics ──────────────────────────────────────────────────────────

class TestMetrics:
    def test_mae_perfect(self):
        assert mae([100, 200], [100, 200]) == 0.0

    def test_mae_basic(self):
        assert mae([100, 200, 300], [110, 190, 310]) == pytest.approx(10.0)

    def test_rmse_penalises_large_errors(self):
        # RMSE > MAE when errors are unequal (penalises outliers more)
        assert rmse([0, 0], [10, 0]) > mae([0, 0], [10, 0])

    def test_mape_zero_actual_skipped(self):
        # actual=0 must be skipped to avoid ZeroDivisionError
        result = mape([0, 100], [50, 110])
        assert result == pytest.approx(10.0)   # only the (100,110) pair counts

    def test_mape_all_zero_raises(self):
        with pytest.raises(ValueError, match="no non-zero actuals"):
            mape([0, 0], [1, 1])

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            mae([1, 2], [1])


# ── Linear ───────────────────────────────────────────────────────────

class TestLinear:
    def test_flat_series_predicts_flat(self, flat_series):
        result = linear_forecast(flat_series, horizon=3)
        for p in result["predictions"]:
            assert p == pytest.approx(1000.0, abs=1.0)

    def test_trending_up_slope_positive(self, trending_up):
        result = linear_forecast(trending_up, horizon=3)
        assert result["slope"] > 0
        # Predictions should continue the upward trend
        assert result["predictions"][0] > trending_up[-1]

    def test_negative_clipped_to_zero(self):
        # Sharply declining series could predict negative — must be clipped
        result = linear_forecast([1000, 500, 100, 50], horizon=3)
        assert all(p >= 0.0 for p in result["predictions"])

    def test_min_data_enforced(self):
        with pytest.raises(ValueError):
            linear_forecast([500.0], horizon=1)   # only 1 point

    def test_r_squared_perfect_line(self, trending_up):
        result = linear_forecast(trending_up, horizon=1)
        assert result["r_squared"] == pytest.approx(1.0, abs=0.001)


# ── Moving Average ───────────────────────────────────────────────────

class TestMovingAverage:
    def test_sma_flat_stays_flat(self, flat_series):
        result = moving_average_forecast(flat_series, horizon=3, window=3)
        assert all(p == pytest.approx(1000.0) for p in result["predictions"])

    def test_wma_weights_recent_more(self):
        # Spike at the end — WMA should predict higher than SMA
        values = [100, 100, 100, 500]
        sma = moving_average_forecast(values, horizon=1, window=4, weighted=False)
        wma = moving_average_forecast(values, horizon=1, window=4, weighted=True)
        assert wma["predictions"][0] > sma["predictions"][0]

    def test_window_larger_than_data_raises(self):
        with pytest.raises(ValueError, match="window"):
            moving_average_forecast([100, 200], horizon=1, window=5)


# ── Exponential ──────────────────────────────────────────────────────

class TestExponential:
    def test_flat_stays_flat(self, flat_series):
        result = exponential_forecast(flat_series, alpha=0.3)
        assert all(p == pytest.approx(1000.0, abs=1.0) for p in result["predictions"])

    def test_high_alpha_tracks_recent(self):
        # High alpha → heavily weighted toward recent values
        values = [100] * 10 + [500]   # big spike at end
        low  = exponential_forecast(values, alpha=0.1)["predictions"][0]
        high = exponential_forecast(values, alpha=0.9)["predictions"][0]
        assert high > low   # high alpha tracks the spike more

    def test_invalid_alpha_raises(self):
        with pytest.raises(ValueError):
            exponential_forecast([100, 200], alpha=0.0)
        with pytest.raises(ValueError):
            exponential_forecast([100, 200], alpha=1.0)


# ── Holt ─────────────────────────────────────────────────────────────

class TestHolt:
    def test_trending_predictions_grow(self, trending_up):
        result = holt_forecast(trending_up, horizon=3)
        preds = result["predictions"]
        # Each future step should be larger than the last (upward trend)
        assert preds[0] < preds[1] < preds[2]

    def test_flat_trend_stays_flat(self, flat_series):
        result = holt_forecast(flat_series, horizon=3)
        # Trend ≈ 0 on flat data — predictions should be near 1000
        assert all(abs(p - 1000.0) < 50 for p in result["predictions"])

    def test_invalid_params_raise(self):
        with pytest.raises(ValueError):
            holt_forecast([100, 200], alpha=1.5)
        with pytest.raises(ValueError):
            holt_forecast([100, 200], beta=0.0)

    def test_min_data_enforced(self):
        with pytest.raises(ValueError):
            holt_forecast([500.0])


# ── Seasonal ─────────────────────────────────────────────────────────

class TestSeasonal:
    def test_requires_24_months(self):
        with pytest.raises(ValueError, match="24"):
            seasonal_forecast([100.0] * 23)

    def test_returns_correct_horizon(self, long_series):
        result = seasonal_forecast(long_series, horizon=3)
        assert len(result["predictions"]) == 3

    def test_predictions_non_negative(self, long_series):
        result = seasonal_forecast(long_series, horizon=3)
        assert all(p >= 0 for p in result["predictions"])


# ── Confidence Intervals ─────────────────────────────────────────────

class TestConfidence:
    def test_lower_ci_never_negative(self):
        # Even with high MAPE, lower_ci must be ≥ 0
        points = compute_confidence_intervals([10.0, 10.0, 10.0], mape_score=200.0)
        assert all(pt["lower_ci"] >= 0.0 for pt in points)

    def test_upper_grows_with_horizon(self):
        points = compute_confidence_intervals([100.0, 100.0, 100.0], mape_score=10.0)
        # sqrt(h) grows → upper CI should widen at each step
        assert points[0]["upper_ci"] < points[1]["upper_ci"] < points[2]["upper_ci"]

    def test_perfect_mape_zero_margin(self):
        points = compute_confidence_intervals([500.0], mape_score=0.0)
        assert points[0]["lower_ci"] == points[0]["upper_ci"] == points[0]["predicted"]
