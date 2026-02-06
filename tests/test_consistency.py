"""
Tests for consistency detection module.

Tests for:
1. ConsistencyResult dataclass
2. calculate_consistency - cross-timeframe stability detection
3. analyze_streaks - streak length analysis
"""

import pytest
from dataclasses import FrozenInstanceError
from decimal import Decimal

from src.evaluation.consistency import (
    ConsistencyResult,
    calculate_consistency,
    analyze_streaks,
)


# Mock position-like object for duck typing
class MockPosition:
    def __init__(self, resolved=True, outcome="win", pnl=None):
        self.resolved = resolved
        self.outcome = outcome
        self.pnl = pnl


class TestConsistencyResult:
    """Test ConsistencyResult frozen dataclass."""

    def test_consistency_result_creation(self):
        """Test creating ConsistencyResult instance."""
        result = ConsistencyResult(
            is_consistent=True,
            consistency_score=Decimal("85.5"),
            primary_signal="stable",
            secondary_signal="alternating",
            timeframe_win_rates={"30d": Decimal("65"), "90d": Decimal("68"), "all": Decimal("70")},
            win_rate_variance=Decimal("6.33"),
            low_confidence_windows=["7d"],
            profile_type="selective",
        )

        assert result.is_consistent is True
        assert result.consistency_score == Decimal("85.5")
        assert result.primary_signal == "stable"
        assert result.secondary_signal == "alternating"
        assert result.profile_type == "selective"
        assert len(result.timeframe_win_rates) == 3
        assert "7d" in result.low_confidence_windows

    def test_consistency_result_frozen(self):
        """Test that ConsistencyResult is immutable."""
        result = ConsistencyResult(
            is_consistent=False,
            consistency_score=Decimal("30"),
            primary_signal="streaky",
            secondary_signal="clustered",
            timeframe_win_rates={},
            win_rate_variance=Decimal("200"),
            low_confidence_windows=[],
            profile_type="active",
        )

        with pytest.raises(FrozenInstanceError):
            result.is_consistent = True


class TestCalculateConsistency:
    """Test calculate_consistency function."""

    def test_stable_trader_selective_profile(self):
        """Test stable trader with low variance across timeframes (selective profile)."""
        # Win rates: 65%, 68%, 70% across windows
        positions_30d = [
            MockPosition(resolved=True, outcome="win") for _ in range(65)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(35)]

        positions_90d = [
            MockPosition(resolved=True, outcome="win") for _ in range(68)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(32)]

        positions_all = [
            MockPosition(resolved=True, outcome="win") for _ in range(70)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(30)]

        positions_by_timeframe = {
            "7d": [],  # Excluded from consistency
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "selective")

        assert result.primary_signal == "stable"
        assert result.is_consistent is True
        assert result.profile_type == "selective"
        assert result.timeframe_win_rates["30d"] == Decimal("65")
        assert result.timeframe_win_rates["90d"] == Decimal("68")
        assert result.timeframe_win_rates["all"] == Decimal("70")
        assert result.win_rate_variance < Decimal("100")  # Selective bar
        assert result.consistency_score > Decimal("50")
        assert "7d" not in result.timeframe_win_rates  # 7d excluded from consistency

    def test_stable_trader_active_profile(self):
        """Test stable trader with low variance (active profile - tighter bar)."""
        # Even lower variance needed for active traders
        positions_30d = [
            MockPosition(resolved=True, outcome="win") for _ in range(60)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(40)]

        positions_90d = [
            MockPosition(resolved=True, outcome="win") for _ in range(62)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(38)]

        positions_all = [
            MockPosition(resolved=True, outcome="win") for _ in range(61)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(39)]

        positions_by_timeframe = {
            "7d": [],
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "active")

        assert result.primary_signal == "stable"
        assert result.is_consistent is True
        assert result.profile_type == "active"
        assert result.win_rate_variance < Decimal("50")  # Active bar (tighter)

    def test_streaky_trader_high_variance(self):
        """Test streaky trader with divergent win rates across windows."""
        # Win rates: 90%, 45%, 60% - high variance
        positions_30d = [
            MockPosition(resolved=True, outcome="win") for _ in range(90)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(10)]

        positions_90d = [
            MockPosition(resolved=True, outcome="win") for _ in range(45)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(55)]

        positions_all = [
            MockPosition(resolved=True, outcome="win") for _ in range(60)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(40)]

        positions_by_timeframe = {
            "7d": [],
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "selective")

        assert result.primary_signal == "streaky"
        assert result.is_consistent is False
        assert result.win_rate_variance > Decimal("100")  # Exceeds selective bar
        assert result.consistency_score < Decimal("50")

    def test_low_confidence_windows_flagged(self):
        """Test that windows with < 5 resolved markets are flagged as low confidence."""
        # Only 3 positions in 30d window
        positions_30d = [
            MockPosition(resolved=True, outcome="win") for _ in range(2)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(1)]

        # Sufficient positions in other windows
        positions_90d = [
            MockPosition(resolved=True, outcome="win") for _ in range(60)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(40)]

        positions_all = [
            MockPosition(resolved=True, outcome="win") for _ in range(65)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(35)]

        positions_by_timeframe = {
            "7d": [],
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "selective", sparse_threshold=5)

        assert "30d" in result.low_confidence_windows
        assert "90d" not in result.low_confidence_windows
        assert "all" not in result.low_confidence_windows

    def test_insufficient_data_only_one_qualifying_window(self):
        """Test insufficient data when only 1 qualifying window exists."""
        # Only all-time window has sufficient data
        positions_30d = [MockPosition(resolved=True, outcome="win") for _ in range(2)]
        positions_90d = [MockPosition(resolved=True, outcome="win") for _ in range(3)]
        positions_all = [
            MockPosition(resolved=True, outcome="win") for _ in range(60)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(40)]

        positions_by_timeframe = {
            "7d": [],
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "selective", sparse_threshold=5)

        assert result.primary_signal == "insufficient_data"
        assert result.is_consistent is False
        assert result.consistency_score == Decimal("0")
        assert len(result.low_confidence_windows) == 2  # 30d and 90d

    def test_insufficient_data_all_windows_low_confidence(self):
        """Test insufficient data when all windows are low confidence."""
        positions_30d = [MockPosition(resolved=True, outcome="win")]
        positions_90d = [MockPosition(resolved=True, outcome="win") for _ in range(2)]
        positions_all = [MockPosition(resolved=True, outcome="win") for _ in range(3)]

        positions_by_timeframe = {
            "7d": [],
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "selective", sparse_threshold=5)

        assert result.primary_signal == "insufficient_data"
        assert result.is_consistent is False
        assert result.consistency_score == Decimal("0")
        assert len(result.low_confidence_windows) == 3

    def test_empty_positions(self):
        """Test with no positions at all."""
        positions_by_timeframe = {
            "7d": [],
            "30d": [],
            "90d": [],
            "all": [],
        }

        result = calculate_consistency(positions_by_timeframe, "selective")

        assert result.primary_signal == "insufficient_data"
        assert result.is_consistent is False
        assert result.consistency_score == Decimal("0")

    def test_voided_markets_excluded(self):
        """Test that voided markets are excluded from win rate calculations."""
        positions_30d = [
            MockPosition(resolved=True, outcome="win") for _ in range(50)
        ] + [
            MockPosition(resolved=True, outcome="loss") for _ in range(50)
        ] + [
            MockPosition(resolved=True, outcome="void") for _ in range(100)  # Should be excluded
        ]

        positions_90d = [
            MockPosition(resolved=True, outcome="win") for _ in range(50)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(50)]

        positions_all = [
            MockPosition(resolved=True, outcome="win") for _ in range(50)
        ] + [MockPosition(resolved=True, outcome="loss") for _ in range(50)]

        positions_by_timeframe = {
            "7d": [],
            "30d": positions_30d,
            "90d": positions_90d,
            "all": positions_all,
        }

        result = calculate_consistency(positions_by_timeframe, "selective")

        # All windows should have 50% win rate (voided excluded)
        assert result.timeframe_win_rates["30d"] == Decimal("50")
        assert result.timeframe_win_rates["90d"] == Decimal("50")
        assert result.timeframe_win_rates["all"] == Decimal("50")
        assert result.win_rate_variance == Decimal("0")  # Perfect consistency
        assert result.primary_signal == "stable"


class TestAnalyzeStreaks:
    """Test analyze_streaks function."""

    def test_perfect_alternation(self):
        """Test perfectly alternating W/L sequence."""
        outcomes = ["win", "loss", "win", "loss", "win", "loss", "win"]

        result = analyze_streaks(outcomes)

        assert result["max_win_streak"] == 1
        assert result["max_loss_streak"] == 1
        assert result["alternation_rate"] == Decimal("1.0")
        assert result["signal"] == "alternating"

    def test_clustered_streaks(self):
        """Test clustered W/L sequences (low alternation)."""
        outcomes = ["win", "win", "win", "win", "loss", "loss", "loss", "loss"]

        result = analyze_streaks(outcomes)

        assert result["max_win_streak"] == 4
        assert result["max_loss_streak"] == 4
        assert result["alternation_rate"] < Decimal("0.4")
        assert result["signal"] == "clustered"

    def test_mixed_alternation(self):
        """Test mixed sequence with moderate alternation."""
        outcomes = ["win", "win", "loss", "win", "loss", "win", "win"]

        result = analyze_streaks(outcomes)

        assert result["max_win_streak"] == 2
        assert result["max_loss_streak"] == 1
        # 4 transitions out of 6 possible = 66.7% > 40%
        assert result["alternation_rate"] >= Decimal("0.4")
        assert result["signal"] == "alternating"

    def test_exclude_void_and_flat(self):
        """Test that void and flat outcomes are excluded from streak analysis."""
        outcomes = ["win", "void", "loss", "flat", "win", "void", "loss"]

        result = analyze_streaks(outcomes)

        # Should analyze: [win, loss, win, loss]
        assert result["alternation_rate"] == Decimal("1.0")
        assert result["signal"] == "alternating"

    def test_empty_outcomes(self):
        """Test with no outcomes."""
        result = analyze_streaks([])

        assert result["max_win_streak"] == 0
        assert result["max_loss_streak"] == 0
        assert result["avg_streak_length"] == Decimal("0")
        assert result["alternation_rate"] == Decimal("0")
        assert result["signal"] == "alternating"  # No evidence of clustering

    def test_single_outcome(self):
        """Test with single outcome (no transitions)."""
        result = analyze_streaks(["win"])

        assert result["max_win_streak"] == 1
        assert result["max_loss_streak"] == 0
        assert result["avg_streak_length"] == Decimal("1")
        assert result["alternation_rate"] == Decimal("0")
        assert result["signal"] == "alternating"  # No streak evidence

    def test_all_wins(self):
        """Test sequence of all wins."""
        outcomes = ["win"] * 10

        result = analyze_streaks(outcomes)

        assert result["max_win_streak"] == 10
        assert result["max_loss_streak"] == 0
        assert result["alternation_rate"] == Decimal("0")
        assert result["signal"] == "alternating"  # Default when < 0.4 but edge case

    def test_all_losses(self):
        """Test sequence of all losses."""
        outcomes = ["loss"] * 8

        result = analyze_streaks(outcomes)

        assert result["max_win_streak"] == 0
        assert result["max_loss_streak"] == 8
        assert result["alternation_rate"] == Decimal("0")
        assert result["signal"] == "alternating"

    def test_avg_streak_length_calculation(self):
        """Test average streak length calculation."""
        # Streaks: WW (2), L (1), WWW (3), LL (2)
        outcomes = ["win", "win", "loss", "win", "win", "win", "loss", "loss"]

        result = analyze_streaks(outcomes)

        # 4 streaks: lengths 2, 1, 3, 2 -> avg = 2.0
        assert result["avg_streak_length"] == Decimal("2.0")

    def test_long_win_streak(self):
        """Test detection of long win streak."""
        outcomes = ["win"] * 15 + ["loss", "win", "loss"]

        result = analyze_streaks(outcomes)

        assert result["max_win_streak"] == 15
        assert result["signal"] == "clustered"  # Very low alternation
