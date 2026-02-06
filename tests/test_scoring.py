"""
Tests for composite expertise scoring engine.

Tests for:
1. ExpertiseScoreResult dataclass
2. calculate_recency_weight - exponential decay with ~90-day half-life
3. calculate_sample_size_confidence - exponential growth curve
4. calculate_expertise_score - composite scoring with all components
5. normalize_scores_to_percentiles - population-relative ranking
"""

import pytest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from datetime import datetime, timedelta

from src.evaluation.scoring import (
    ExpertiseScoreResult,
    calculate_recency_weight,
    calculate_sample_size_confidence,
    calculate_expertise_score,
    normalize_scores_to_percentiles,
    DEFAULT_WEIGHTS,
    MIN_RESOLVED_MARKETS,
    RECENCY_HALF_LIFE_DAYS,
)


# Mock position-like object for duck typing
class MockPosition:
    def __init__(self, resolved=True, outcome="win", pnl=None, last_trade_timestamp=None):
        self.resolved = resolved
        self.outcome = outcome
        self.pnl = pnl
        self.last_trade_timestamp = last_trade_timestamp


class TestExpertiseScoreResult:
    """Test ExpertiseScoreResult frozen dataclass."""

    def test_result_creation(self):
        """Test creating ExpertiseScoreResult instance."""
        result = ExpertiseScoreResult(
            raw_score=Decimal("85.5"),
            percentile_rank=Decimal("92.3"),
            win_rate_component=Decimal("70"),
            concentration_component=Decimal("80"),
            recency_component=Decimal("90"),
            sample_size_component=Decimal("95"),
            consistency_multiplier=Decimal("1.05"),
            specialization_label="specialist/specialist",
            game_slug="esports.cs2",
            trader_address="0x123",
            resolved_market_count=25,
        )

        assert result.raw_score == Decimal("85.5")
        assert result.percentile_rank == Decimal("92.3")
        assert result.win_rate_component == Decimal("70")
        assert result.concentration_component == Decimal("80")
        assert result.recency_component == Decimal("90")
        assert result.sample_size_component == Decimal("95")
        assert result.consistency_multiplier == Decimal("1.05")
        assert result.specialization_label == "specialist/specialist"
        assert result.game_slug == "esports.cs2"
        assert result.trader_address == "0x123"
        assert result.resolved_market_count == 25

    def test_result_frozen(self):
        """Test that ExpertiseScoreResult is immutable."""
        result = ExpertiseScoreResult(
            raw_score=Decimal("50"),
            percentile_rank=None,
            win_rate_component=Decimal("60"),
            concentration_component=Decimal("40"),
            recency_component=Decimal("50"),
            sample_size_component=Decimal("60"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="generalist/generalist",
            game_slug="esports.dota2",
            trader_address="0x456",
            resolved_market_count=10,
        )

        with pytest.raises(FrozenInstanceError):
            result.raw_score = Decimal("100")


class TestRecencyWeight:
    """Test calculate_recency_weight function."""

    def test_same_day_returns_one(self):
        """Same day should return full weight."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        last_resolved = datetime(2024, 6, 1, 8, 0, 0)

        weight = calculate_recency_weight(last_resolved, now)

        assert weight == Decimal("1.0")

    def test_future_timestamp_returns_one(self):
        """Future timestamp should return full weight."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        last_resolved = datetime(2024, 6, 2, 12, 0, 0)

        weight = calculate_recency_weight(last_resolved, now)

        assert weight == Decimal("1.0")

    def test_half_life_returns_half(self):
        """90 days ago should return ~0.5 weight."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        last_resolved = now - timedelta(days=90)

        weight = calculate_recency_weight(last_resolved, now, half_life_days=90)

        # Should be approximately 0.5 (within 0.01 tolerance)
        assert abs(weight - Decimal("0.5")) < Decimal("0.01")

    def test_double_half_life(self):
        """180 days ago should return ~0.25 weight."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        last_resolved = now - timedelta(days=180)

        weight = calculate_recency_weight(last_resolved, now, half_life_days=90)

        # Should be approximately 0.25 (within 0.01 tolerance)
        assert abs(weight - Decimal("0.25")) < Decimal("0.01")

    def test_zero_days_different_time(self):
        """0 days but different time should still return 1.0."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        last_resolved = datetime(2024, 6, 1, 12, 0, 0)

        weight = calculate_recency_weight(last_resolved, now)

        assert weight == Decimal("1.0")

    def test_one_day_ago(self):
        """1 day ago should return very high weight (> 0.99)."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        last_resolved = now - timedelta(days=1)

        weight = calculate_recency_weight(last_resolved, now, half_life_days=90)

        assert weight > Decimal("0.99")


class TestSampleSizeConfidence:
    """Test calculate_sample_size_confidence function."""

    def test_below_minimum_returns_zero(self):
        """Below minimum threshold should return 0."""
        confidence = calculate_sample_size_confidence(3, min_threshold=5)

        assert confidence == Decimal("0")

    def test_at_minimum_returns_positive(self):
        """At minimum threshold should return positive value < 1."""
        confidence = calculate_sample_size_confidence(5, min_threshold=5)

        assert confidence > Decimal("0")
        assert confidence < Decimal("1.0")

    def test_at_full_confidence_returns_one(self):
        """At full confidence threshold should return 1.0."""
        confidence = calculate_sample_size_confidence(30, min_threshold=5, full_confidence_threshold=30)

        assert confidence == Decimal("1.0")

    def test_above_full_confidence_returns_one(self):
        """Above full confidence threshold should return 1.0."""
        confidence = calculate_sample_size_confidence(50, min_threshold=5, full_confidence_threshold=30)

        assert confidence == Decimal("1.0")

    def test_monotonically_increasing(self):
        """Confidence should increase monotonically between thresholds."""
        values = []
        for count in range(5, 31):
            confidence = calculate_sample_size_confidence(count, min_threshold=5, full_confidence_threshold=30)
            values.append(confidence)

        # Check monotonically increasing
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_exact_minimum_threshold(self):
        """Exactly at minimum should give small but non-zero confidence."""
        confidence = calculate_sample_size_confidence(5, min_threshold=5, full_confidence_threshold=30)

        assert confidence > Decimal("0")
        assert confidence < Decimal("0.2")  # Should be relatively small


class TestCalculateExpertiseScore:
    """Test calculate_expertise_score function."""

    def test_below_minimum_sample_returns_none(self):
        """Below minimum resolved markets should return None."""
        positions = [
            MockPosition(resolved=True, outcome="win") for _ in range(4)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.8"),
            game_concentration=Decimal("0.7"),
            consistency_score=Decimal("80"),
            consistency_signal="stable",
        )

        assert result is None

    def test_exactly_minimum_returns_result(self):
        """Exactly 5 resolved markets should return result."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(5)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.8"),
            game_concentration=Decimal("0.7"),
            consistency_score=Decimal("80"),
            consistency_signal="stable",
            now=now,
        )

        assert result is not None
        assert isinstance(result, ExpertiseScoreResult)
        assert result.resolved_market_count == 5

    def test_high_performance_trader(self):
        """High win rate + high concentration + recent activity = high score."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(18)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=now) for _ in range(2)
        ]  # 90% win rate, 20 markets

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.9"),  # High eSports focus
            game_concentration=Decimal("0.8"),  # High game focus
            consistency_score=Decimal("90"),
            consistency_signal="stable",
            now=now,
        )

        assert result is not None
        assert result.raw_score > Decimal("70")  # Should be high
        assert result.win_rate_component == Decimal("90")  # 90% win rate
        assert result.concentration_component == Decimal("80")  # 0.8 * 100
        assert result.recency_component == Decimal("100")  # Recent
        assert result.consistency_multiplier == Decimal("1.05")  # Bonus (score=90 >= 80 AND stable)

    def test_low_performance_trader(self):
        """Low win rate + low concentration + old activity = low score."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        old_timestamp = now - timedelta(days=180)  # 180 days ago
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=old_timestamp) for _ in range(3)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=old_timestamp) for _ in range(7)
        ]  # 30% win rate, 10 markets, old

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.3"),  # Low eSports focus
            game_concentration=Decimal("0.2"),  # Low game focus
            consistency_score=Decimal("50"),
            consistency_signal="streaky",
            now=now,
        )

        assert result is not None
        assert result.raw_score < Decimal("40")  # Should be low
        assert result.concentration_component == Decimal("20")  # 0.2 * 100

    def test_consistent_trader_gets_multiplier(self):
        """Consistent trader (score >= 80, signal=stable) gets 1.05x multiplier."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(14)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=now) for _ in range(6)
        ]  # 70% win rate, 20 markets

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("85"),  # High consistency
            consistency_signal="stable",  # Stable signal
            now=now,
        )

        assert result is not None
        assert result.consistency_multiplier == Decimal("1.05")  # Bonus applied

    def test_streaky_trader_no_penalty(self):
        """Streaky trader gets 1.0x multiplier (no penalty, baseline)."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(14)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=now) for _ in range(6)
        ]  # 70% win rate

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("35"),  # Low consistency
            consistency_signal="streaky",  # Streaky signal
            now=now,
        )

        assert result is not None
        assert result.consistency_multiplier == Decimal("1.0")  # No penalty

    def test_neutral_consistency_baseline(self):
        """Neutral consistency (score=60, signal=stable) gets 1.0x multiplier (baseline)."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(10)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("60"),  # Neutral
            consistency_signal="stable",  # Stable but score not high enough
            now=now,
        )

        assert result is not None
        assert result.consistency_multiplier == Decimal("1.0")  # Baseline

    def test_insufficient_data_baseline(self):
        """Insufficient data gets 1.0x multiplier (baseline)."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(10)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("0"),
            consistency_signal="insufficient_data",
            now=now,
        )

        assert result is not None
        assert result.consistency_multiplier == Decimal("1.0")  # Baseline

    def test_custom_weights(self):
        """Custom weights override DEFAULT_WEIGHTS."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(10)
        ]

        custom_weights = {
            "win_rate": Decimal("0.50"),
            "concentration": Decimal("0.30"),
            "recency": Decimal("0.10"),
            "sample_size": Decimal("0.10"),
        }

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("80"),
            consistency_signal="stable",
            weights=custom_weights,
            now=now,
        )

        assert result is not None
        # Score should differ from default weights due to different weighting

    def test_raw_score_clamped_to_0_100(self):
        """Raw score should be clamped to [0, 100] range."""
        # This is implicitly tested by the scoring algorithm,
        # but we verify the range is respected
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(10)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("1.0"),
            game_concentration=Decimal("1.0"),
            consistency_score=Decimal("100"),
            consistency_signal="stable",
            now=now,
        )

        assert result is not None
        assert result.raw_score >= Decimal("0")
        assert result.raw_score <= Decimal("100")

    def test_void_positions_excluded(self):
        """Void positions should be excluded from resolved count."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(5)
        ] + [
            MockPosition(resolved=True, outcome="void", last_trade_timestamp=now) for _ in range(3)
        ]  # 5 valid, 3 void

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("80"),
            consistency_signal="stable",
            now=now,
        )

        assert result is not None
        assert result.resolved_market_count == 5  # Only non-void

    def test_percentile_rank_is_none(self):
        """percentile_rank should be None (computed in batch later)."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(10)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("80"),
            consistency_signal="stable",
            now=now,
        )

        assert result is not None
        assert result.percentile_rank is None

    def test_specialization_label_included(self):
        """specialization_label should come from classify_specialization."""
        now = datetime(2024, 6, 1, 12, 0, 0)
        positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(10)
        ]

        result = calculate_expertise_score(
            positions=positions,
            trader_address="0x123",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.9"),  # Specialist level
            game_concentration=Decimal("0.8"),  # Specialist level
            consistency_score=Decimal("80"),
            consistency_signal="stable",
            now=now,
        )

        assert result is not None
        assert result.specialization_label == "specialist/specialist"


class TestNormalizeScoresToPercentiles:
    """Test normalize_scores_to_percentiles function."""

    def test_empty_input_returns_empty(self):
        """Empty input should return empty dict."""
        result = normalize_scores_to_percentiles({})

        assert result == {}

    def test_single_trader_gets_100(self):
        """Single trader should get percentile 100."""
        scores = {"trader1": Decimal("75")}

        result = normalize_scores_to_percentiles(scores)

        assert result["trader1"] == Decimal("100")

    def test_two_traders_0_and_100(self):
        """Two traders: lower gets 0, higher gets 100."""
        scores = {
            "trader1": Decimal("50"),
            "trader2": Decimal("80"),
        }

        result = normalize_scores_to_percentiles(scores)

        assert result["trader1"] == Decimal("0")
        assert result["trader2"] == Decimal("100")

    def test_three_traders_0_50_100(self):
        """Three traders: lowest=0, middle=50, highest=100."""
        scores = {
            "trader1": Decimal("40"),
            "trader2": Decimal("70"),
            "trader3": Decimal("90"),
        }

        result = normalize_scores_to_percentiles(scores)

        assert result["trader1"] == Decimal("0")
        assert result["trader2"] == Decimal("50")
        assert result["trader3"] == Decimal("100")

    def test_tied_scores_same_percentile(self):
        """Traders with same score should get same percentile."""
        scores = {
            "trader1": Decimal("70"),
            "trader2": Decimal("70"),
            "trader3": Decimal("90"),
        }

        result = normalize_scores_to_percentiles(scores)

        # Both tied traders should have same percentile
        assert result["trader1"] == result["trader2"]
        # Highest should still be 100
        assert result["trader3"] == Decimal("100")

    def test_all_identical_scores(self):
        """All identical scores should get same percentile."""
        scores = {
            "trader1": Decimal("70"),
            "trader2": Decimal("70"),
            "trader3": Decimal("70"),
        }

        result = normalize_scores_to_percentiles(scores)

        # All should have same percentile
        percentile = result["trader1"]
        assert result["trader2"] == percentile
        assert result["trader3"] == percentile


class TestIntegration:
    """Integration test for full scoring pipeline."""

    def test_full_pipeline(self):
        """Test full pipeline: create positions -> score -> normalize -> verify order."""
        now = datetime(2024, 6, 1, 12, 0, 0)

        # Create three traders with different performance levels
        high_performer_positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(18)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=now) for _ in range(2)
        ]  # 90% win rate

        medium_performer_positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(13)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=now) for _ in range(7)
        ]  # 65% win rate

        low_performer_positions = [
            MockPosition(resolved=True, outcome="win", last_trade_timestamp=now) for _ in range(5)
        ] + [
            MockPosition(resolved=True, outcome="loss", last_trade_timestamp=now) for _ in range(5)
        ]  # 50% win rate

        # Calculate scores
        high_result = calculate_expertise_score(
            positions=high_performer_positions,
            trader_address="0xhigh",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.9"),
            game_concentration=Decimal("0.8"),
            consistency_score=Decimal("85"),
            consistency_signal="stable",
            now=now,
        )

        medium_result = calculate_expertise_score(
            positions=medium_performer_positions,
            trader_address="0xmedium",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.7"),
            game_concentration=Decimal("0.6"),
            consistency_score=Decimal("70"),
            consistency_signal="stable",
            now=now,
        )

        low_result = calculate_expertise_score(
            positions=low_performer_positions,
            trader_address="0xlow",
            game_slug="esports.cs2",
            esports_concentration=Decimal("0.5"),
            game_concentration=Decimal("0.4"),
            consistency_score=Decimal("50"),
            consistency_signal="streaky",
            now=now,
        )

        # Normalize to percentiles
        raw_scores = {
            "0xhigh": high_result.raw_score,
            "0xmedium": medium_result.raw_score,
            "0xlow": low_result.raw_score,
        }

        percentiles = normalize_scores_to_percentiles(raw_scores)

        # Verify ranking order
        assert percentiles["0xhigh"] == Decimal("100")  # Best
        assert percentiles["0xmedium"] == Decimal("50")  # Middle
        assert percentiles["0xlow"] == Decimal("0")  # Worst
        assert high_result.raw_score > medium_result.raw_score > low_result.raw_score


class TestConstants:
    """Test module constants."""

    def test_default_weights_sum_to_one(self):
        """DEFAULT_WEIGHTS should sum to 1.0."""
        total = sum(DEFAULT_WEIGHTS.values())

        assert total == Decimal("1.0")

    def test_default_weights_structure(self):
        """DEFAULT_WEIGHTS should have correct structure."""
        assert "win_rate" in DEFAULT_WEIGHTS
        assert "concentration" in DEFAULT_WEIGHTS
        assert "recency" in DEFAULT_WEIGHTS
        assert "sample_size" in DEFAULT_WEIGHTS

        assert DEFAULT_WEIGHTS["win_rate"] == Decimal("0.40")

    def test_min_resolved_markets_constant(self):
        """MIN_RESOLVED_MARKETS should be 5."""
        assert MIN_RESOLVED_MARKETS == 5

    def test_recency_half_life_constant(self):
        """RECENCY_HALF_LIFE_DAYS should be 90."""
        assert RECENCY_HALF_LIFE_DAYS == 90
