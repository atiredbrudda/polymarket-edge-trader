"""
Tests for validation framework.

TDD tests for temporal train/test splits, walk-forward validation,
and scoring weight evaluation.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from dataclasses import dataclass

from src.evaluation.validation import (
    temporal_train_test_split,
    walk_forward_validate,
    evaluate_scoring_weights,
    run_validation,
    FoldResult,
    ValidationResult,
)


# Mock objects for duck-typing
@dataclass
class MockPosition:
    """Mock position for testing."""
    trader_address: str
    market_id: str
    last_trade_timestamp: datetime
    resolved: bool
    outcome: str | None
    pnl: Decimal | None
    size: Decimal
    direction: str
    avg_entry_price: Decimal | None


class TestTemporalTrainTestSplit:
    """Test temporal_train_test_split for correct time-based partitioning."""

    def test_split_with_positions_before_and_after_split_date(self):
        """Positions before split go to train, positions after go to test."""
        split_date = datetime(2026, 2, 1)
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xa", "m2", datetime(2026, 1, 28), True, "loss", Decimal("-5"), Decimal("50"), "LONG", Decimal("0.6")),
            MockPosition("0xa", "m3", datetime(2026, 2, 5), False, None, None, Decimal("80"), "LONG", Decimal("0.55")),
            MockPosition("0xa", "m4", datetime(2026, 2, 10), False, None, None, Decimal("60"), "LONG", Decimal("0.45")),
        ]

        train, test = temporal_train_test_split(positions, split_date)

        assert len(train) == 2
        assert len(test) == 2
        assert all(p.last_trade_timestamp < split_date for p in train)
        assert all(p.last_trade_timestamp >= split_date for p in test)

    def test_split_all_positions_before_split_date(self):
        """When all positions are before split, test set is empty."""
        split_date = datetime(2026, 3, 1)
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xa", "m2", datetime(2026, 2, 10), True, "loss", Decimal("-5"), Decimal("50"), "LONG", Decimal("0.6")),
        ]

        train, test = temporal_train_test_split(positions, split_date)

        assert len(train) == 2
        assert len(test) == 0

    def test_split_all_positions_after_split_date(self):
        """When all positions are after split, train set is empty."""
        split_date = datetime(2026, 1, 1)
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 2, 15), False, None, None, Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xa", "m2", datetime(2026, 2, 20), False, None, None, Decimal("50"), "LONG", Decimal("0.6")),
        ]

        train, test = temporal_train_test_split(positions, split_date)

        assert len(train) == 0
        assert len(test) == 2

    def test_split_position_on_exact_split_date_goes_to_test(self):
        """Position with timestamp equal to split_date goes to test set."""
        split_date = datetime(2026, 2, 1, 12, 0, 0)
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 31, 23, 59, 59), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xa", "m2", split_date, True, "win", Decimal("5"), Decimal("50"), "LONG", Decimal("0.6")),
            MockPosition("0xa", "m3", datetime(2026, 2, 1, 12, 0, 1), False, None, None, Decimal("80"), "LONG", Decimal("0.55")),
        ]

        train, test = temporal_train_test_split(positions, split_date)

        assert len(train) == 1
        assert len(test) == 2
        assert train[0].market_id == "m1"
        assert test[0].market_id == "m2"
        assert test[1].market_id == "m3"

    def test_split_empty_positions_list(self):
        """Empty positions list returns two empty lists."""
        split_date = datetime(2026, 2, 1)
        train, test = temporal_train_test_split([], split_date)

        assert train == []
        assert test == []

    def test_split_preserves_original_order(self):
        """Train and test sets preserve original list order."""
        split_date = datetime(2026, 2, 1)
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 20), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xa", "m2", datetime(2026, 2, 5), False, None, None, Decimal("80"), "LONG", Decimal("0.55")),
            MockPosition("0xa", "m3", datetime(2026, 1, 25), True, "loss", Decimal("-5"), Decimal("50"), "LONG", Decimal("0.6")),
            MockPosition("0xa", "m4", datetime(2026, 2, 10), False, None, None, Decimal("60"), "LONG", Decimal("0.45")),
        ]

        train, test = temporal_train_test_split(positions, split_date)

        # Train should have m1, m3 in that order
        assert len(train) == 2
        assert train[0].market_id == "m1"
        assert train[1].market_id == "m3"

        # Test should have m2, m4 in that order
        assert len(test) == 2
        assert test[0].market_id == "m2"
        assert test[1].market_id == "m4"


class TestWalkForwardValidate:
    """Test walk_forward_validate for correct fold generation."""

    def test_generates_correct_number_of_folds_with_sufficient_data(self):
        """With sufficient data, generates requested number of folds."""
        # 450 days of data, 90-day test windows, should fit 5 folds
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        assert len(folds) == 5

    def test_fold_boundaries_are_non_overlapping(self):
        """Test windows don't overlap with each other."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        for i in range(len(folds) - 1):
            train_start_i, train_end_i, test_start_i, test_end_i = folds[i]
            train_start_j, train_end_j, test_start_j, test_end_j = folds[i + 1]

            # Test end of fold i should equal test start of fold i+1 (or earlier)
            assert test_end_i <= test_start_j or test_start_i >= test_end_j

    def test_train_windows_expand_over_time(self):
        """Training windows should expand (include more data) as time progresses."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        # Check that training windows expand (train_end - train_start increases)
        train_durations = [(fold[1] - fold[0]).days for fold in folds]

        # Later folds should have longer or equal training windows
        for i in range(len(train_durations) - 1):
            assert train_durations[i + 1] >= train_durations[i]

    def test_test_windows_are_consistent_size(self):
        """All test windows should be approximately the same size."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        test_durations = [(fold[3] - fold[2]).days for fold in folds]

        # All test windows should be approximately 90 days
        for duration in test_durations:
            assert 85 <= duration <= 95  # Allow small variance

    def test_stops_when_insufficient_training_data(self):
        """Stops generating folds when training window < min_train_days."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=200)  # Only 200 days total

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*5), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(40)
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        # Should generate fewer than 5 folds due to insufficient data
        assert len(folds) < 5
        assert len(folds) >= 1  # But at least one fold

    def test_returns_empty_for_insufficient_data(self):
        """Returns empty list when data range < test_window + min_train."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=100)  # Only 100 days (need 180)

        positions = [
            MockPosition("0xa", "m1", earliest, True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xa", "m2", latest, True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        assert len(folds) == 0

    def test_returns_empty_for_empty_positions(self):
        """Returns empty list for empty positions."""
        folds = walk_forward_validate([], n_folds=5, test_window_days=90, min_train_days=90)

        assert folds == []

    def test_train_end_equals_test_start(self):
        """Train end should equal test start (no gaps)."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        folds = walk_forward_validate(positions, n_folds=5, test_window_days=90, min_train_days=90)

        for train_start, train_end, test_start, test_end in folds:
            assert train_end == test_start


class TestEvaluateScoringWeights:
    """Test evaluate_scoring_weights for metric computation."""

    def test_raises_error_if_weights_dont_sum_to_one(self):
        """Raises ValueError if weights don't sum to 1.0."""
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.3"),
            "win_rate": Decimal("0.3"),
            "recency": Decimal("0.2"),
            "sample_size": Decimal("0.1"),
        }  # Sum = 0.9

        with pytest.raises(ValueError, match="sum to 1.0"):
            evaluate_scoring_weights(positions, positions, weights)

    def test_accepts_weights_summing_to_one(self):
        """Accepts weights that sum to 1.0."""
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        # Should not raise
        result = evaluate_scoring_weights(positions, positions, weights)
        assert "correlation" in result

    def test_returns_zero_metrics_for_empty_test_set(self):
        """Returns zero metrics when test set is empty."""
        train_positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = evaluate_scoring_weights(train_positions, [], weights)

        assert result["correlation"] == Decimal("0")
        assert result["rank_accuracy"] == Decimal("0")
        assert result["top_k_precision"] == Decimal("0")

    def test_computes_correlation_between_train_and_test_performance(self):
        """Computes correlation metric between train scores and test performance."""
        # Create positions where train performance predicts test performance
        train_positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("20"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xb", "m2", datetime(2026, 1, 15), True, "loss", Decimal("-10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        test_positions = [
            MockPosition("0xa", "m3", datetime(2026, 2, 15), True, "win", Decimal("15"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xb", "m4", datetime(2026, 2, 15), True, "loss", Decimal("-5"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = evaluate_scoring_weights(train_positions, test_positions, weights)

        # With perfect prediction, correlation should be positive
        assert "correlation" in result
        assert isinstance(result["correlation"], Decimal)

    def test_computes_rank_accuracy(self):
        """Computes rank accuracy metric."""
        train_positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("20"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xb", "m2", datetime(2026, 1, 15), True, "loss", Decimal("-10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        test_positions = [
            MockPosition("0xa", "m3", datetime(2026, 2, 15), True, "win", Decimal("15"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xb", "m4", datetime(2026, 2, 15), True, "loss", Decimal("-5"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = evaluate_scoring_weights(train_positions, test_positions, weights)

        assert "rank_accuracy" in result
        assert isinstance(result["rank_accuracy"], Decimal)

    def test_computes_top_k_precision(self):
        """Computes top-K precision metric."""
        train_positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("20"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xb", "m2", datetime(2026, 1, 15), True, "loss", Decimal("-10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        test_positions = [
            MockPosition("0xa", "m3", datetime(2026, 2, 15), True, "win", Decimal("15"), Decimal("100"), "LONG", Decimal("0.5")),
            MockPosition("0xb", "m4", datetime(2026, 2, 15), True, "loss", Decimal("-5"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = evaluate_scoring_weights(train_positions, test_positions, weights)

        assert "top_k_precision" in result
        assert isinstance(result["top_k_precision"], Decimal)

    def test_uses_custom_metric_fn_if_provided(self):
        """Uses custom metric_fn for evaluation if provided."""
        train_positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 15), True, "win", Decimal("20"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        test_positions = [
            MockPosition("0xa", "m3", datetime(2026, 2, 15), True, "win", Decimal("15"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        def custom_metric(train_pos, test_pos, weights):
            return {"custom_score": Decimal("0.999")}

        result = evaluate_scoring_weights(train_positions, test_positions, weights, metric_fn=custom_metric)

        assert "custom_score" in result
        assert result["custom_score"] == Decimal("0.999")


class TestRunValidation:
    """Test run_validation orchestrator function."""

    def test_returns_validation_result_with_fold_results(self):
        """Returns ValidationResult with populated FoldResults."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = run_validation(positions, weights, n_folds=3, test_window_days=90, min_train_days=90)

        assert isinstance(result, ValidationResult)
        assert len(result.folds) > 0
        assert all(isinstance(fold, FoldResult) for fold in result.folds)

    def test_aggregates_metrics_across_folds(self):
        """Aggregates metrics by averaging across folds."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = run_validation(positions, weights, n_folds=3, test_window_days=90, min_train_days=90)

        assert "correlation" in result.aggregate_scores
        assert "rank_accuracy" in result.aggregate_scores
        assert "top_k_precision" in result.aggregate_scores

    def test_returns_empty_folds_for_insufficient_data(self):
        """Returns ValidationResult with empty folds if data insufficient."""
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 1), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = run_validation(positions, weights, n_folds=5, test_window_days=90, min_train_days=90)

        assert isinstance(result, ValidationResult)
        assert len(result.folds) == 0

    def test_deterministic_output_for_same_inputs(self):
        """Same inputs produce same outputs (re-runnable)."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(45)
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result1 = run_validation(positions, weights, n_folds=3, test_window_days=90, min_train_days=90)
        result2 = run_validation(positions, weights, n_folds=3, test_window_days=90, min_train_days=90)

        # Should produce same fold boundaries and metrics (deterministic)
        assert len(result1.folds) == len(result2.folds)
        for fold1, fold2 in zip(result1.folds, result2.folds):
            assert fold1.train_start == fold2.train_start
            assert fold1.train_end == fold2.train_end
            assert fold1.test_start == fold2.test_start
            assert fold1.test_end == fold2.test_end

    def test_populates_weights_tested_in_result(self):
        """ValidationResult includes the weights that were tested."""
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 1), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.3"),
            "win_rate": Decimal("0.3"),
            "recency": Decimal("0.2"),
            "sample_size": Decimal("0.2"),
        }

        result = run_validation(positions, weights, n_folds=1, test_window_days=90, min_train_days=90)

        assert result.weights_tested == weights

    def test_counts_total_traders_evaluated(self):
        """ValidationResult includes total unique traders evaluated."""
        latest = datetime(2026, 2, 6)
        earliest = latest - timedelta(days=450)

        positions = [
            MockPosition("0xa", f"m{i}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(20)
        ] + [
            MockPosition("0xb", f"m{i+20}", earliest + timedelta(days=i*10), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5"))
            for i in range(20)
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = run_validation(positions, weights, n_folds=2, test_window_days=90, min_train_days=90)

        assert result.total_traders_evaluated >= 1  # At least one trader

    def test_records_run_timestamp(self):
        """ValidationResult includes run timestamp."""
        positions = [
            MockPosition("0xa", "m1", datetime(2026, 1, 1), True, "win", Decimal("10"), Decimal("100"), "LONG", Decimal("0.5")),
        ]

        weights = {
            "concentration": Decimal("0.25"),
            "win_rate": Decimal("0.25"),
            "recency": Decimal("0.25"),
            "sample_size": Decimal("0.25"),
        }

        result = run_validation(positions, weights, n_folds=1, test_window_days=90, min_train_days=90)

        assert isinstance(result.run_timestamp, datetime)
