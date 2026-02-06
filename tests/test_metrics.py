"""
TDD tests for performance metrics calculator.

Tests cover all metrics functions with focus on:
- Decimal arithmetic (no floats)
- Voided market exclusion
- Resolved/unresolved distinction
- LONG/SHORT PnL calculations
- Win rate calculation
- Aggregated metrics
"""

import pytest
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass

from src.evaluation.metrics import (
    calculate_realized_pnl,
    calculate_win_rate,
    calculate_total_volume,
    calculate_unrealized_pnl,
    aggregate_trader_metrics,
)


# Duck-typed test fixtures (no SQLAlchemy dependency)
@dataclass
class MockPosition:
    """Mock position object for testing."""
    size: Decimal
    direction: str
    avg_entry_price: Decimal | None
    resolved: bool
    outcome: str | None
    pnl: Decimal | None


@dataclass
class MockTrade:
    """Mock trade object for testing."""
    size: Decimal
    price: Decimal


class TestCalculateRealizedPnl:
    """Test realized PnL calculation."""

    def test_empty_positions(self):
        """Empty list returns zero."""
        result = calculate_realized_pnl([])
        assert result == Decimal("0")
        assert isinstance(result, Decimal)

    def test_all_voided_positions(self):
        """Voided positions excluded from PnL."""
        positions = [
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.5"),
                resolved=True,
                outcome="void",
                pnl=Decimal("0")
            ),
            MockPosition(
                size=Decimal("50"),
                direction="SHORT",
                avg_entry_price=Decimal("0.7"),
                resolved=True,
                outcome="void",
                pnl=Decimal("0")
            ),
        ]
        result = calculate_realized_pnl(positions)
        assert result == Decimal("0")

    def test_unresolved_positions_excluded(self):
        """Unresolved positions not counted in realized PnL."""
        positions = [
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.5"),
                resolved=False,
                outcome=None,
                pnl=None
            ),
            MockPosition(
                size=Decimal("50"),
                direction="SHORT",
                avg_entry_price=Decimal("0.7"),
                resolved=True,
                outcome="win",
                pnl=Decimal("15")
            ),
        ]
        result = calculate_realized_pnl(positions)
        assert result == Decimal("15")

    def test_mixed_wins_and_losses(self):
        """Mix of wins and losses returns net sum."""
        positions = [
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.5"),
                resolved=True,
                outcome="win",
                pnl=Decimal("20")
            ),
            MockPosition(
                size=Decimal("50"),
                direction="SHORT",
                avg_entry_price=Decimal("0.7"),
                resolved=True,
                outcome="loss",
                pnl=Decimal("-10")
            ),
            MockPosition(
                size=Decimal("75"),
                direction="LONG",
                avg_entry_price=Decimal("0.6"),
                resolved=True,
                outcome="win",
                pnl=Decimal("5")
            ),
        ]
        result = calculate_realized_pnl(positions)
        assert result == Decimal("15")

    def test_long_position_pnl(self):
        """LONG position PnL calculated correctly."""
        positions = [
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.4"),
                resolved=True,
                outcome="win",
                pnl=Decimal("20")
            ),
        ]
        result = calculate_realized_pnl(positions)
        assert result == Decimal("20")

    def test_short_position_pnl(self):
        """SHORT position PnL calculated correctly."""
        positions = [
            MockPosition(
                size=Decimal("-50"),
                direction="SHORT",
                avg_entry_price=Decimal("0.7"),
                resolved=True,
                outcome="win",
                pnl=Decimal("10")
            ),
        ]
        result = calculate_realized_pnl(positions)
        assert result == Decimal("10")

    def test_flat_outcome_excluded(self):
        """Flat outcome excluded from realized PnL."""
        positions = [
            MockPosition(
                size=Decimal("0"),
                direction="FLAT",
                avg_entry_price=None,
                resolved=True,
                outcome="flat",
                pnl=Decimal("0")
            ),
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.5"),
                resolved=True,
                outcome="win",
                pnl=Decimal("10")
            ),
        ]
        result = calculate_realized_pnl(positions)
        assert result == Decimal("10")


class TestCalculateWinRate:
    """Test win rate calculation."""

    def test_no_resolved_positions(self):
        """No resolved positions returns zero stats."""
        positions = [
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.5"),
                resolved=False,
                outcome=None,
                pnl=None
            ),
        ]
        result = calculate_win_rate(positions)
        assert result == {"wins": 0, "losses": 0, "total": 0, "win_rate": None}

    def test_all_wins(self):
        """All wins returns 100% win rate."""
        positions = [
            MockPosition(
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.5"),
                resolved=True,
                outcome="win",
                pnl=Decimal("20")
            ),
            MockPosition(
                size=Decimal("50"),
                direction="SHORT",
                avg_entry_price=Decimal("0.7"),
                resolved=True,
                outcome="win",
                pnl=Decimal("10")
            ),
        ]
        result = calculate_win_rate(positions)
        assert result["wins"] == 2
        assert result["losses"] == 0
        assert result["total"] == 2
        assert result["win_rate"] == Decimal("100")
        assert isinstance(result["win_rate"], Decimal)

    def test_three_wins_two_losses(self):
        """3 wins 2 losses returns 60% win rate."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="win", pnl=Decimal("10")),
            MockPosition(size=Decimal("50"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=True, outcome="loss", pnl=Decimal("-5")),
            MockPosition(size=Decimal("75"), direction="LONG", avg_entry_price=Decimal("0.6"),
                        resolved=True, outcome="win", pnl=Decimal("8")),
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.4"),
                        resolved=True, outcome="loss", pnl=Decimal("-10")),
            MockPosition(size=Decimal("60"), direction="SHORT", avg_entry_price=Decimal("0.8"),
                        resolved=True, outcome="win", pnl=Decimal("15")),
        ]
        result = calculate_win_rate(positions)
        assert result["wins"] == 3
        assert result["losses"] == 2
        assert result["total"] == 5
        assert result["win_rate"] == Decimal("60")

    def test_voided_excluded_from_win_rate(self):
        """Voided outcomes excluded from win rate calculation."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="void", pnl=Decimal("0")),
            MockPosition(size=Decimal("50"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=True, outcome="win", pnl=Decimal("10")),
            MockPosition(size=Decimal("75"), direction="LONG", avg_entry_price=Decimal("0.6"),
                        resolved=True, outcome="win", pnl=Decimal("5")),
        ]
        result = calculate_win_rate(positions)
        assert result["wins"] == 2
        assert result["losses"] == 0
        assert result["total"] == 2
        assert result["win_rate"] == Decimal("100")

    def test_flat_excluded_from_win_rate(self):
        """Flat outcomes excluded from win rate calculation."""
        positions = [
            MockPosition(size=Decimal("0"), direction="FLAT", avg_entry_price=None,
                        resolved=True, outcome="flat", pnl=Decimal("0")),
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="win", pnl=Decimal("10")),
        ]
        result = calculate_win_rate(positions)
        assert result["wins"] == 1
        assert result["losses"] == 0
        assert result["total"] == 1
        assert result["win_rate"] == Decimal("100")

    def test_none_outcome_excluded(self):
        """None outcomes excluded from win rate."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome=None, pnl=Decimal("0")),
            MockPosition(size=Decimal("50"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=True, outcome="win", pnl=Decimal("10")),
        ]
        result = calculate_win_rate(positions)
        assert result["wins"] == 1
        assert result["losses"] == 0
        assert result["total"] == 1


class TestCalculateTotalVolume:
    """Test total volume calculation."""

    def test_empty_trades(self):
        """Empty list returns zero volume."""
        result = calculate_total_volume([])
        assert result == Decimal("0")
        assert isinstance(result, Decimal)

    def test_single_trade(self):
        """Single trade size=10, price=0.65 returns 6.5."""
        trades = [
            MockTrade(size=Decimal("10"), price=Decimal("0.65"))
        ]
        result = calculate_total_volume(trades)
        assert result == Decimal("6.5")

    def test_multiple_trades(self):
        """Multiple trades sum correctly."""
        trades = [
            MockTrade(size=Decimal("10"), price=Decimal("0.65")),
            MockTrade(size=Decimal("20"), price=Decimal("0.5")),
            MockTrade(size=Decimal("5"), price=Decimal("0.8")),
        ]
        # 10*0.65 + 20*0.5 + 5*0.8 = 6.5 + 10 + 4 = 20.5
        result = calculate_total_volume(trades)
        assert result == Decimal("20.5")

    def test_negative_size_uses_absolute_value(self):
        """Negative size (SELL) uses absolute value."""
        trades = [
            MockTrade(size=Decimal("-10"), price=Decimal("0.65")),
        ]
        result = calculate_total_volume(trades)
        assert result == Decimal("6.5")


class TestCalculateUnrealizedPnl:
    """Test unrealized PnL mark-to-market calculation."""

    def test_flat_position(self):
        """FLAT position returns zero unrealized PnL."""
        position = MockPosition(
            size=Decimal("0"),
            direction="FLAT",
            avg_entry_price=None,
            resolved=False,
            outcome=None,
            pnl=None
        )
        result = calculate_unrealized_pnl(position, Decimal("0.5"))
        assert result["pnl"] == Decimal("0")
        assert result["unrealized"] is True

    def test_long_position_profit(self):
        """LONG position with current > entry shows profit."""
        position = MockPosition(
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.4"),
            resolved=False,
            outcome=None,
            pnl=None
        )
        # size=100, entry=0.40, current=0.60 -> pnl = 100 * (0.60 - 0.40) = 20
        result = calculate_unrealized_pnl(position, Decimal("0.6"))
        assert result["pnl"] == Decimal("20")
        assert result["unrealized"] is True
        assert result["direction"] == "LONG"
        assert result["current_price"] == Decimal("0.6")

    def test_long_position_loss(self):
        """LONG position with current < entry shows loss."""
        position = MockPosition(
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.6"),
            resolved=False,
            outcome=None,
            pnl=None
        )
        # size=100, entry=0.60, current=0.40 -> pnl = 100 * (0.40 - 0.60) = -20
        result = calculate_unrealized_pnl(position, Decimal("0.4"))
        assert result["pnl"] == Decimal("-20")
        assert result["unrealized"] is True

    def test_short_position_profit(self):
        """SHORT position with current < entry shows profit."""
        position = MockPosition(
            size=Decimal("-50"),
            direction="SHORT",
            avg_entry_price=Decimal("0.7"),
            resolved=False,
            outcome=None,
            pnl=None
        )
        # size=50 (abs), entry=0.70, current=0.30 -> pnl = 50 * (0.70 - 0.30) = 20
        result = calculate_unrealized_pnl(position, Decimal("0.3"))
        assert result["pnl"] == Decimal("20")
        assert result["unrealized"] is True
        assert result["direction"] == "SHORT"
        assert result["current_price"] == Decimal("0.3")

    def test_short_position_loss(self):
        """SHORT position with current > entry shows loss."""
        position = MockPosition(
            size=Decimal("-50"),
            direction="SHORT",
            avg_entry_price=Decimal("0.3"),
            resolved=False,
            outcome=None,
            pnl=None
        )
        # size=50 (abs), entry=0.30, current=0.70 -> pnl = 50 * (0.30 - 0.70) = -20
        result = calculate_unrealized_pnl(position, Decimal("0.7"))
        assert result["pnl"] == Decimal("-20")
        assert result["unrealized"] is True


class TestAggregateTraderMetrics:
    """Test aggregate trader metrics combining all calculations."""

    def test_empty_positions_and_trades(self):
        """Empty inputs return zero metrics."""
        result = aggregate_trader_metrics([], [])
        assert result["realized_pnl"] == Decimal("0")
        assert result["unrealized_pnl"] == Decimal("0")
        assert result["total_pnl"] == Decimal("0")
        assert result["win_rate"] == {"wins": 0, "losses": 0, "total": 0, "win_rate": None}
        assert result["total_volume"] == Decimal("0")
        assert result["resolved_markets"] == 0
        assert result["unresolved_markets"] == 0

    def test_only_resolved_positions(self):
        """Resolved positions only."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="win", pnl=Decimal("20")),
            MockPosition(size=Decimal("50"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=True, outcome="loss", pnl=Decimal("-10")),
        ]
        trades = [
            MockTrade(size=Decimal("100"), price=Decimal("0.5")),
            MockTrade(size=Decimal("50"), price=Decimal("0.7")),
        ]
        result = aggregate_trader_metrics(positions, trades)
        assert result["realized_pnl"] == Decimal("10")
        assert result["unrealized_pnl"] == Decimal("0")
        assert result["total_pnl"] == Decimal("10")
        assert result["win_rate"]["wins"] == 1
        assert result["win_rate"]["losses"] == 1
        assert result["total_volume"] == Decimal("85")  # 100*0.5 + 50*0.7 = 50 + 35
        assert result["resolved_markets"] == 2
        assert result["unresolved_markets"] == 0

    def test_mixed_resolved_and_unrealized(self):
        """Mix of resolved and unresolved positions."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="win", pnl=Decimal("20")),
            MockPosition(size=Decimal("50"), direction="LONG", avg_entry_price=Decimal("0.4"),
                        resolved=False, outcome=None, pnl=None),
            MockPosition(size=Decimal("-75"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=False, outcome=None, pnl=None),
        ]
        trades = [
            MockTrade(size=Decimal("100"), price=Decimal("0.5")),
            MockTrade(size=Decimal("50"), price=Decimal("0.4")),
            MockTrade(size=Decimal("75"), price=Decimal("0.7")),
        ]
        # Unrealized: position[1] at price 0.6, position[2] at price 0.3
        unrealized = [
            (positions[1], Decimal("0.6")),  # LONG: 50 * (0.6 - 0.4) = 10
            (positions[2], Decimal("0.3")),  # SHORT: 75 * (0.7 - 0.3) = 30
        ]
        result = aggregate_trader_metrics(positions, trades, unrealized)
        assert result["realized_pnl"] == Decimal("20")
        assert result["unrealized_pnl"] == Decimal("40")  # 10 + 30
        assert result["total_pnl"] == Decimal("60")  # 20 + 40
        assert result["win_rate"]["wins"] == 1
        assert result["win_rate"]["total"] == 1
        assert result["resolved_markets"] == 1
        assert result["unresolved_markets"] == 2

    def test_voided_positions_excluded(self):
        """Voided positions excluded from resolved count."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="void", pnl=Decimal("0")),
            MockPosition(size=Decimal("50"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=True, outcome="win", pnl=Decimal("15")),
        ]
        trades = []
        result = aggregate_trader_metrics(positions, trades)
        assert result["realized_pnl"] == Decimal("15")
        assert result["resolved_markets"] == 1  # Only non-voided counted
        assert result["win_rate"]["wins"] == 1
        assert result["win_rate"]["total"] == 1

    def test_all_metric_types_present(self):
        """Comprehensive test with all metric types."""
        positions = [
            MockPosition(size=Decimal("100"), direction="LONG", avg_entry_price=Decimal("0.5"),
                        resolved=True, outcome="win", pnl=Decimal("30")),
            MockPosition(size=Decimal("50"), direction="SHORT", avg_entry_price=Decimal("0.7"),
                        resolved=True, outcome="loss", pnl=Decimal("-10")),
            MockPosition(size=Decimal("75"), direction="LONG", avg_entry_price=Decimal("0.4"),
                        resolved=False, outcome=None, pnl=None),
        ]
        trades = [
            MockTrade(size=Decimal("100"), price=Decimal("0.5")),
            MockTrade(size=Decimal("50"), price=Decimal("0.7")),
            MockTrade(size=Decimal("75"), price=Decimal("0.4")),
        ]
        unrealized = [(positions[2], Decimal("0.6"))]  # LONG: 75 * (0.6 - 0.4) = 15

        result = aggregate_trader_metrics(positions, trades, unrealized)

        assert result["realized_pnl"] == Decimal("20")
        assert result["unrealized_pnl"] == Decimal("15")
        assert result["total_pnl"] == Decimal("35")
        assert result["win_rate"]["wins"] == 1
        assert result["win_rate"]["losses"] == 1
        assert result["win_rate"]["total"] == 2
        assert result["win_rate"]["win_rate"] == Decimal("50")
        assert result["total_volume"] == Decimal("115")  # 100*0.5 + 50*0.7 + 75*0.4
        assert result["resolved_markets"] == 2
        assert result["unresolved_markets"] == 1

        # Verify all values are Decimal types
        assert isinstance(result["realized_pnl"], Decimal)
        assert isinstance(result["unrealized_pnl"], Decimal)
        assert isinstance(result["total_pnl"], Decimal)
        assert isinstance(result["total_volume"], Decimal)
