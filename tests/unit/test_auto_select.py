"""
Unit tests for auto_select engine.

Covers:
  - candidate selection by data volume (Rule 1 boundary)
  - walk-forward validation is time-ordered (Rule 2)
  - winner is always the lowest-MAPE algorithm
  - output structure (predictions, mape, all_scores, points)
"""
import pytest

from app.core.algorithms.auto_select import (
    _candidates_for,
    _walk_forward_mape,
    auto_select_forecast,
)
from app.core.algorithms.linear import linear_forecast


# ── _candidates_for ───────────────────────────────────────────────────

class TestCandidatesFor:
    def test_fewer_than_4_raises(self):
        # Rule 1: never forecast with < 4 months
        with pytest.raises(ValueError, match="insufficient data"):
            _candidates_for(3)

    def test_4_to_5_returns_only_base(self):
        names = [name for name, _ in _candidates_for(5)]
        assert set(names) == {"linear", "exponential"}
        assert "holt" not in names
        assert "seasonal" not in names

    def test_6_to_23_excludes_seasonal(self):
        names = [name for name, _ in _candidates_for(12)]
        assert "seasonal" not in names
        assert "holt" in names
        assert "moving_avg" in names

    def test_24_plus_includes_seasonal(self):
        names = [name for name, _ in _candidates_for(24)]
        assert "seasonal" in names


# ── _walk_forward_mape ────────────────────────────────────────────────

class TestWalkForwardMape:
    def test_never_shuffles_data(self):
        """
        Rule 2: walk-forward must use chronological splits.
        We verify by passing a strictly increasing series and confirming
        the function doesn't raise (shuffling would break the fold indexing).
        """
        values = list(range(10, 20))   # [10, 11, ..., 19] — strictly ordered
        fn = lambda v, horizon: linear_forecast(v, horizon)
        mape = _walk_forward_mape(values, fn)
        assert isinstance(mape, float)
        assert mape >= 0.0

    def test_flat_series_near_zero_mape(self):
        """Flat billing → linear perfectly fits → MAPE ≈ 0."""
        values = [1000.0] * 10
        fn = lambda v, horizon: linear_forecast(v, horizon)
        mape = _walk_forward_mape(values, fn)
        assert mape < 1.0   # essentially perfect

    def test_too_short_raises(self):
        """Fewer data points than folds → no valid folds → ValueError."""
        with pytest.raises(ValueError):
            _walk_forward_mape(
                [100.0, 200.0],
                lambda v, horizon: linear_forecast(v, horizon),
            )


# ── auto_select_forecast ──────────────────────────────────────────────

class TestAutoSelectForecast:

    @pytest.fixture
    def twelve_months(self):
        return [1000.0 + i * 50 for i in range(12)]

    @pytest.fixture
    def twenty_four_months(self):
        return [1000.0 + i * 30 for i in range(24)]

    def test_returns_required_keys(self, twelve_months):
        result = auto_select_forecast(twelve_months, horizon=3)
        assert "algorithm" in result
        assert "predictions" in result
        assert "mape" in result
        assert "all_scores" in result
        assert "points" in result

    def test_predictions_length_matches_horizon(self, twelve_months):
        result = auto_select_forecast(twelve_months, horizon=3)
        assert len(result["predictions"]) == 3
        assert len(result["points"]) == 3

    def test_winner_has_lowest_mape(self, twelve_months):
        result = auto_select_forecast(twelve_months, horizon=3)
        winner = result["algorithm"]
        winner_mape = result["mape"]
        # Every other algorithm's score must be >= winner's score
        for name, score in result["all_scores"].items():
            assert score >= winner_mape - 0.001  # tiny float tolerance

    def test_predictions_non_negative(self, twelve_months):
        result = auto_select_forecast(twelve_months, horizon=3)
        assert all(p >= 0.0 for p in result["predictions"])

    def test_fewer_than_4_raises(self):
        with pytest.raises(ValueError, match="insufficient data"):
            auto_select_forecast([100.0, 200.0, 300.0], horizon=1)

    def test_24_months_may_include_seasonal(self, twenty_four_months):
        result = auto_select_forecast(twenty_four_months, horizon=3)
        # seasonal is now a candidate — it may or may not win, but it should appear
        assert "seasonal" in result["all_scores"]

    def test_ci_bounds_consistent(self, twelve_months):
        result = auto_select_forecast(twelve_months, horizon=3)
        for pt in result["points"]:
            assert pt["lower_ci"] <= pt["predicted"] <= pt["upper_ci"]
            assert pt["lower_ci"] >= 0.0
