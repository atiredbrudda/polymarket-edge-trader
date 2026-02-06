"""
Tests for stateless position tracker.

Tests cover:
- Basic position calculation (single trade, multiple trades)
- Weighted average entry price with multiple fills
- Partial and full closures
- Entry timestamp tracking and resets
- Position direction (LONG/SHORT/FLAT)
- Decimal precision
- PnL calculation (win/loss/void/flat)
"""

from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass
import pytest

from src.discovery.position_tracker import (
    PositionData,
    calculate_position,
    calculate_pnl,
)


# Test stub for trade objects (duck-typed, no SQLAlchemy dependency)
@dataclass
class Trade:
    """Stub trade object for testing."""
    side: str
    size: Decimal
    price: Decimal
    timestamp: datetime
    market_id: str = "test_market"
    trader_address: str = "0xTestTrader"


class TestBasicPositionCalculation:
    """Test basic position calculation scenarios."""

    def test_single_buy(self):
        """One BUY trade creates LONG position."""
        trades = [
            Trade(
                side="BUY",
                size=Decimal("10"),
                price=Decimal("0.50"),
                timestamp=datetime(2025, 1, 1, 12, 0, 0),
            )
        ]
        position = calculate_position(trades)

        assert position.size == Decimal("10")
        assert position.direction == "LONG"
        assert position.avg_entry_price == Decimal("0.50")
        assert position.entry_timestamp == datetime(2025, 1, 1, 12, 0, 0)
        assert position.total_cost_basis == Decimal("5.0")  # 10 * 0.50
        assert position.trade_count == 1
        assert position.first_trade_timestamp == datetime(2025, 1, 1, 12, 0, 0)
        assert position.last_trade_timestamp == datetime(2025, 1, 1, 12, 0, 0)

    def test_single_sell(self):
        """One SELL trade creates SHORT position."""
        trades = [
            Trade(
                side="SELL",
                size=Decimal("5"),
                price=Decimal("0.70"),
                timestamp=datetime(2025, 1, 2, 14, 0, 0),
            )
        ]
        position = calculate_position(trades)

        assert position.size == Decimal("-5")
        assert position.direction == "SHORT"
        assert position.avg_entry_price == Decimal("0.70")
        assert position.entry_timestamp == datetime(2025, 1, 2, 14, 0, 0)
        assert position.total_cost_basis == Decimal("-3.5")  # -5 * 0.70
        assert position.trade_count == 1

    def test_multiple_buys_weighted_average(self):
        """Multiple buys at different prices calculate correct weighted average."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.40"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("BUY", Decimal("20"), Decimal("0.50"), datetime(2025, 1, 1, 11, 0, 0)),
            Trade("BUY", Decimal("30"), Decimal("0.60"), datetime(2025, 1, 1, 12, 0, 0)),
        ]
        position = calculate_position(trades)

        # Expected: (10*0.40 + 20*0.50 + 30*0.60) / (10+20+30) = 32/60 = 0.533333...
        expected_avg = (Decimal("10") * Decimal("0.40") +
                       Decimal("20") * Decimal("0.50") +
                       Decimal("30") * Decimal("0.60")) / Decimal("60")

        assert position.size == Decimal("60")
        assert position.direction == "LONG"
        assert position.avg_entry_price == expected_avg
        assert position.entry_timestamp == datetime(2025, 1, 1, 10, 0, 0)
        assert position.trade_count == 3

    def test_buy_then_sell_partial(self):
        """Buy then partial sell reduces position, keeps original avg entry."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("5"), Decimal("0.70"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)

        assert position.size == Decimal("5")
        assert position.direction == "LONG"
        # Avg entry should still reflect the original BUY price
        assert position.avg_entry_price == Decimal("0.50")
        assert position.entry_timestamp == datetime(2025, 1, 1, 10, 0, 0)
        assert position.trade_count == 2

    def test_buy_then_sell_full_closure(self):
        """Buy then full sell results in FLAT position."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("10"), Decimal("0.70"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)

        assert position.size == Decimal("0")
        assert position.direction == "FLAT"
        assert position.avg_entry_price is None
        assert position.entry_timestamp is None
        assert position.total_cost_basis == Decimal("0")
        assert position.trade_count == 2

    def test_empty_trades_raises(self):
        """Empty trade list raises ValueError."""
        with pytest.raises(ValueError, match="No trades provided"):
            calculate_position([])


class TestEdgeCases:
    """Test edge cases and complex scenarios."""

    def test_full_closure_then_reopen(self):
        """Full closure resets entry timestamp; reopening sets new entry."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("10"), Decimal("0.70"), datetime(2025, 1, 1, 11, 0, 0)),
            Trade("BUY", Decimal("5"), Decimal("0.60"), datetime(2025, 1, 1, 12, 0, 0)),
        ]
        position = calculate_position(trades)

        assert position.size == Decimal("5")
        assert position.direction == "LONG"
        # Entry timestamp should be the third trade (after closure)
        assert position.entry_timestamp == datetime(2025, 1, 1, 12, 0, 0)
        assert position.avg_entry_price == Decimal("0.60")
        assert position.trade_count == 3

    def test_multiple_partial_fills(self):
        """Many small buys and sells compute correct net position."""
        trades = [
            Trade("BUY", Decimal("3"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("BUY", Decimal("2"), Decimal("0.51"), datetime(2025, 1, 1, 10, 5, 0)),
            Trade("SELL", Decimal("1"), Decimal("0.52"), datetime(2025, 1, 1, 10, 10, 0)),
            Trade("BUY", Decimal("4"), Decimal("0.49"), datetime(2025, 1, 1, 10, 15, 0)),
            Trade("SELL", Decimal("3"), Decimal("0.53"), datetime(2025, 1, 1, 10, 20, 0)),
        ]
        position = calculate_position(trades)

        # Net: +3 +2 -1 +4 -3 = +5
        assert position.size == Decimal("5")
        assert position.direction == "LONG"
        assert position.trade_count == 5

    def test_decimal_precision(self):
        """Prices with high precision maintain precision through calculation."""
        trades = [
            Trade("BUY", Decimal("7"), Decimal("0.567890"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("BUY", Decimal("3"), Decimal("0.432110"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)

        # Expected: (7*0.567890 + 3*0.432110) / 10 = (3.97523 + 1.29633) / 10 = 0.527156
        expected_avg = (Decimal("7") * Decimal("0.567890") +
                       Decimal("3") * Decimal("0.432110")) / Decimal("10")

        assert position.avg_entry_price == expected_avg
        # Verify no float rounding errors
        assert isinstance(position.avg_entry_price, Decimal)

    def test_position_direction_long(self):
        """Net positive size results in LONG direction."""
        trades = [Trade("BUY", Decimal("15"), Decimal("0.50"), datetime(2025, 1, 1))]
        position = calculate_position(trades)
        assert position.direction == "LONG"

    def test_position_direction_short(self):
        """Net negative size results in SHORT direction."""
        trades = [Trade("SELL", Decimal("15"), Decimal("0.50"), datetime(2025, 1, 1))]
        position = calculate_position(trades)
        assert position.direction == "SHORT"

    def test_position_direction_flat(self):
        """Net zero size results in FLAT direction."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("10"), Decimal("0.60"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)
        assert position.direction == "FLAT"


class TestEntryTiming:
    """Test entry timestamp tracking."""

    def test_entry_timestamp_first_trade(self):
        """Entry timestamp is first BUY for long position."""
        trades = [
            Trade("BUY", Decimal("5"), Decimal("0.40"), datetime(2025, 1, 1, 9, 0, 0)),
            Trade("BUY", Decimal("5"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
        ]
        position = calculate_position(trades)
        assert position.entry_timestamp == datetime(2025, 1, 1, 9, 0, 0)

    def test_entry_timestamp_resets_on_closure(self):
        """After full close, entry timestamp becomes next opening trade."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1, 9, 0, 0)),
            Trade("SELL", Decimal("10"), Decimal("0.60"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("5"), Decimal("0.70"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)
        # After flat at second trade, third trade opens SHORT position
        assert position.entry_timestamp == datetime(2025, 1, 1, 11, 0, 0)
        assert position.direction == "SHORT"

    def test_first_last_trade_timestamps(self):
        """first_trade_timestamp and last_trade_timestamp are correct."""
        trades = [
            Trade("BUY", Decimal("5"), Decimal("0.50"), datetime(2025, 1, 1, 9, 0, 0)),
            Trade("BUY", Decimal("3"), Decimal("0.51"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("2"), Decimal("0.52"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)
        assert position.first_trade_timestamp == datetime(2025, 1, 1, 9, 0, 0)
        assert position.last_trade_timestamp == datetime(2025, 1, 1, 11, 0, 0)


class TestPnLCalculation:
    """Test PnL calculation for resolved positions."""

    def test_pnl_long_win(self):
        """Long position with YES resolution wins."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.40"), datetime(2025, 1, 1)),
        ]
        position = calculate_position(trades)
        result = calculate_pnl(position, Decimal("1.0"), "YES")

        # PnL = 10 * (1.0 - 0.40) = 6.0
        assert result["pnl"] == Decimal("6.0")
        assert result["outcome"] == "win"
        # Return % = 6.0 / 4.0 = 150%
        assert result["return_pct"] == Decimal("150")

    def test_pnl_long_loss(self):
        """Long position with NO resolution loses."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.80"), datetime(2025, 1, 1)),
        ]
        position = calculate_position(trades)
        result = calculate_pnl(position, Decimal("0.0"), "NO")

        # PnL = 10 * (0.0 - 0.80) = -8.0
        assert result["pnl"] == Decimal("-8.0")
        assert result["outcome"] == "loss"
        # Return % = -8.0 / 8.0 = -100%
        assert result["return_pct"] == Decimal("-100")

    def test_pnl_short_win(self):
        """Short position with NO resolution wins."""
        trades = [
            Trade("SELL", Decimal("10"), Decimal("0.70"), datetime(2025, 1, 1)),
        ]
        position = calculate_position(trades)
        result = calculate_pnl(position, Decimal("0.0"), "NO")

        # PnL = 10 * (0.70 - 0.0) = 7.0
        assert result["pnl"] == Decimal("7.0")
        assert result["outcome"] == "win"

    def test_pnl_void(self):
        """VOID outcome returns zero PnL."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1)),
        ]
        position = calculate_position(trades)
        result = calculate_pnl(position, Decimal("0.0"), "VOID")

        assert result["pnl"] == Decimal("0")
        assert result["outcome"] == "void"
        assert result["return_pct"] is None

    def test_pnl_flat_position(self):
        """Flat position returns zero PnL."""
        trades = [
            Trade("BUY", Decimal("10"), Decimal("0.50"), datetime(2025, 1, 1, 10, 0, 0)),
            Trade("SELL", Decimal("10"), Decimal("0.60"), datetime(2025, 1, 1, 11, 0, 0)),
        ]
        position = calculate_position(trades)
        result = calculate_pnl(position, Decimal("1.0"), "YES")

        assert result["pnl"] == Decimal("0")
        assert result["outcome"] == "flat"
        assert result["return_pct"] is None

    def test_pnl_return_pct(self):
        """Return percentage calculated correctly."""
        trades = [
            Trade("BUY", Decimal("20"), Decimal("0.30"), datetime(2025, 1, 1)),
        ]
        position = calculate_position(trades)
        result = calculate_pnl(position, Decimal("0.80"), "YES")

        # Cost basis = 20 * 0.30 = 6.0
        # PnL = 20 * (0.80 - 0.30) = 10.0
        # Return % = 10.0 / 6.0 * 100 = 166.666...%
        assert result["pnl"] == Decimal("10.0")
        expected_pct = (Decimal("10.0") / Decimal("6.0")) * Decimal("100")
        assert result["return_pct"] == expected_pct
