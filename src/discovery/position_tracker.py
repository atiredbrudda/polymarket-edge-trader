"""
Stateless position tracker for computing trader positions from trade history.

This module provides pure functions for position calculation with no incremental state.
Positions are always recomputed from the full trade list, ensuring accuracy with no drift.

Design principles:
- Pure functions, no classes or state
- Duck-typed trade input (works with any object having the right attributes)
- All financial math uses Decimal, never float
- No SQLAlchemy imports (keeps module pure and decoupled)
"""

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PositionData:
    """
    Immutable position data computed from trade history.

    Attributes:
        market_id: Market identifier
        trader_address: Trader's address
        size: Net shares (positive=long, negative=short, zero=flat)
        direction: Position direction ("LONG", "SHORT", or "FLAT")
        avg_entry_price: Weighted average entry price (None if flat)
        entry_timestamp: Timestamp of first trade opening current position
        total_cost_basis: Sum of size*price across opening trades
        trade_count: Number of trades in history
        first_trade_timestamp: Earliest trade timestamp
        last_trade_timestamp: Latest trade timestamp
    """
    market_id: str
    trader_address: str
    size: Decimal
    direction: str
    avg_entry_price: Decimal | None
    entry_timestamp: datetime | None
    total_cost_basis: Decimal
    trade_count: int
    first_trade_timestamp: datetime | None
    last_trade_timestamp: datetime | None


def calculate_position(trades: list[Any]) -> PositionData:
    """
    Calculate current position from full trade history.

    Pure function that accepts any trade-like objects (anything with side, size,
    price, timestamp, market_id, trader_address attributes).

    Algorithm:
    1. Sort trades chronologically
    2. Process each trade:
       - BUY: increase size, add to cost basis
       - SELL: decrease size, subtract from cost basis
    3. Track entry timestamp (first trade after flat, resets on full closure)
    4. Compute weighted average entry price from cost basis and size

    Args:
        trades: List of trade-like objects with attributes:
                - side: "BUY" or "SELL"
                - size: Decimal (trade size)
                - price: Decimal (trade price)
                - timestamp: datetime
                - market_id: str
                - trader_address: str

    Returns:
        PositionData with computed position details

    Raises:
        ValueError: If trades list is empty

    Note:
        All arithmetic uses Decimal to prevent float precision loss.
    """
    if not trades:
        raise ValueError("No trades provided")

    # Sort trades chronologically (ensure correct order)
    sorted_trades = sorted(trades, key=lambda t: t.timestamp)

    # Initialize position state
    net_size = Decimal("0")
    total_cost_basis = Decimal("0")
    entry_timestamp = None

    # Track trade timing
    first_trade_timestamp = sorted_trades[0].timestamp
    last_trade_timestamp = sorted_trades[-1].timestamp
    trade_count = len(sorted_trades)

    # Get market and trader from first trade
    market_id = sorted_trades[0].market_id
    trader_address = sorted_trades[0].trader_address

    # Process each trade
    for trade in sorted_trades:
        previous_size = net_size

        if trade.side == "BUY":
            # If we had a short position, this is closing (or flipping to long)
            if previous_size < Decimal("0"):
                # Closing short position
                if trade.size <= abs(previous_size):
                    # Partial or full close of short
                    close_amount = trade.size
                    # Reduce cost basis proportionally
                    if previous_size != Decimal("0"):
                        cost_per_share = total_cost_basis / previous_size
                        total_cost_basis -= close_amount * cost_per_share
                    net_size += close_amount

                    if net_size == Decimal("0"):
                        # Full closure
                        entry_timestamp = None
                        total_cost_basis = Decimal("0")
                else:
                    # Flip from short to long
                    net_size += trade.size
                    # Reset for new long position
                    remaining_long = net_size
                    total_cost_basis = remaining_long * trade.price
                    entry_timestamp = trade.timestamp
            else:
                # Opening or adding to long position
                net_size += trade.size
                total_cost_basis += trade.size * trade.price

                # If this is first BUY after flat, record entry timestamp
                if previous_size == Decimal("0"):
                    entry_timestamp = trade.timestamp

        elif trade.side == "SELL":
            # If we had a long position, this is closing (or flipping to short)
            if previous_size > Decimal("0"):
                # Closing long position
                if trade.size <= previous_size:
                    # Partial or full close of long
                    close_amount = trade.size
                    # Reduce cost basis proportionally to maintain avg entry price
                    if previous_size != Decimal("0"):
                        cost_per_share = total_cost_basis / previous_size
                        total_cost_basis -= close_amount * cost_per_share
                    net_size -= close_amount

                    if net_size == Decimal("0"):
                        # Full closure
                        entry_timestamp = None
                        total_cost_basis = Decimal("0")
                else:
                    # Flip from long to short
                    net_size -= trade.size
                    # Reset for new short position
                    remaining_short = abs(net_size)
                    total_cost_basis = net_size * trade.price  # Negative for short
                    entry_timestamp = trade.timestamp
            else:
                # Opening or adding to short position
                net_size -= trade.size
                total_cost_basis -= trade.size * trade.price

                # If this is first SELL after flat, record entry timestamp
                if previous_size == Decimal("0"):
                    entry_timestamp = trade.timestamp

    # Determine direction
    if net_size > Decimal("0"):
        direction = "LONG"
    elif net_size < Decimal("0"):
        direction = "SHORT"
    else:
        direction = "FLAT"

    # Calculate weighted average entry price
    if net_size != Decimal("0"):
        avg_entry_price = total_cost_basis / net_size
    else:
        avg_entry_price = None

    return PositionData(
        market_id=market_id,
        trader_address=trader_address,
        size=net_size,
        direction=direction,
        avg_entry_price=avg_entry_price,
        entry_timestamp=entry_timestamp,
        total_cost_basis=total_cost_basis,
        trade_count=trade_count,
        first_trade_timestamp=first_trade_timestamp,
        last_trade_timestamp=last_trade_timestamp,
    )


def calculate_pnl(
    position: PositionData,
    resolution_price: Decimal,
    market_outcome: str,
) -> dict[str, Decimal | str | None]:
    """
    Calculate profit/loss for a resolved position.

    Pure function that computes PnL based on position, resolution price, and outcome.

    Args:
        position: PositionData from calculate_position
        resolution_price: Final settlement price (typically 0 or 1 for binary markets)
        market_outcome: "YES", "NO", or "VOID"

    Returns:
        Dictionary with:
            - outcome: "win", "loss", "void", or "flat"
            - pnl: Decimal (profit/loss amount)
            - return_pct: Decimal | None (pnl / cost_basis * 100, None if flat/void)

    Logic:
        - VOID: pnl=0, outcome="void"
        - FLAT position: pnl=0, outcome="flat"
        - LONG: pnl = size * (resolution_price - avg_entry_price)
        - SHORT: pnl = abs(size) * (avg_entry_price - resolution_price)
        - outcome = "win" if pnl > 0, "loss" if pnl < 0, else based on context
    """
    # Handle VOID outcome
    if market_outcome == "VOID":
        return {
            "outcome": "void",
            "pnl": Decimal("0"),
            "return_pct": None,
        }

    # Handle FLAT position
    if position.size == Decimal("0"):
        return {
            "outcome": "flat",
            "pnl": Decimal("0"),
            "return_pct": None,
        }

    # Calculate PnL based on position direction
    if position.direction == "LONG":
        # Long: profit if resolution_price > avg_entry_price
        pnl = position.size * (resolution_price - position.avg_entry_price)
    else:  # SHORT
        # Short: profit if avg_entry_price > resolution_price
        pnl = abs(position.size) * (position.avg_entry_price - resolution_price)

    # Determine outcome
    if pnl > Decimal("0"):
        outcome = "win"
    elif pnl < Decimal("0"):
        outcome = "loss"
    else:
        outcome = "flat"

    # Calculate return percentage
    if abs(position.total_cost_basis) > Decimal("0"):
        return_pct = (pnl / abs(position.total_cost_basis)) * Decimal("100")
    else:
        return_pct = None

    return {
        "outcome": outcome,
        "pnl": pnl,
        "return_pct": return_pct,
    }
