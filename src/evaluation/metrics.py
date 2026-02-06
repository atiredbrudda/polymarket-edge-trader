"""
Pure functions for trader performance metrics calculation.

This module provides stateless metrics calculators following the pure-function,
duck-typed pattern from position_tracker.py. All functions accept simple data
objects and use Decimal arithmetic for financial precision.

Design principles:
- Pure functions, no classes or state
- Duck-typed inputs (works with any object having the right attributes)
- All financial math uses Decimal, never float
- No SQLAlchemy imports (keeps module pure and decoupled)

Resolution handling:
- Voided: exclude from all calculations (outcome == "void")
- Resolved: include in realized PnL and win rate
- Unresolved: mark-to-market via calculate_unrealized_pnl, flagged as "unrealized"
"""

from decimal import Decimal
from typing import Any


def calculate_realized_pnl(positions: list[Any]) -> Decimal:
    """
    Calculate total realized profit/loss from resolved positions.

    Filters for resolved positions excluding voided markets, then sums their PnL.

    Args:
        positions: List of position-like objects with attributes:
                  - resolved: bool (True if market resolved)
                  - outcome: str | None ("win", "loss", "void", "flat", None)
                  - pnl: Decimal | None (profit/loss amount)

    Returns:
        Total realized PnL as Decimal. Returns Decimal("0") if no valid positions.

    Examples:
        >>> positions = [MockPosition(resolved=True, outcome="win", pnl=Decimal("20"))]
        >>> calculate_realized_pnl(positions)
        Decimal('20')

        >>> positions = [MockPosition(resolved=True, outcome="void", pnl=Decimal("0"))]
        >>> calculate_realized_pnl(positions)
        Decimal('0')
    """
    if not positions:
        return Decimal("0")

    total_pnl = Decimal("0")

    for position in positions:
        # Only count resolved positions that are not voided
        if position.resolved and position.outcome != "void":
            if position.pnl is not None:
                total_pnl += position.pnl

    return total_pnl


def calculate_win_rate(positions: list[Any]) -> dict[str, int | Decimal | None]:
    """
    Calculate win rate from resolved positions.

    Filters for resolved positions excluding void, flat, and None outcomes.
    Counts wins and losses, then calculates win percentage.

    Args:
        positions: List of position-like objects with attributes:
                  - resolved: bool (True if market resolved)
                  - outcome: str | None ("win", "loss", "void", "flat", None)

    Returns:
        Dictionary with:
            - wins: int (number of winning positions)
            - losses: int (number of losing positions)
            - total: int (wins + losses)
            - win_rate: Decimal | None (wins/total * 100, None if total == 0)

    Examples:
        >>> positions = [
        ...     MockPosition(resolved=True, outcome="win"),
        ...     MockPosition(resolved=True, outcome="win"),
        ...     MockPosition(resolved=True, outcome="loss"),
        ... ]
        >>> calculate_win_rate(positions)
        {'wins': 2, 'losses': 1, 'total': 3, 'win_rate': Decimal('66.66666666666666666666666667')}
    """
    wins = 0
    losses = 0

    for position in positions:
        # Only count resolved positions with valid outcomes
        if position.resolved and position.outcome not in ("void", "flat", None):
            if position.outcome == "win":
                wins += 1
            elif position.outcome == "loss":
                losses += 1

    total = wins + losses
    win_rate = None if total == 0 else (Decimal(wins) / Decimal(total)) * Decimal("100")

    return {
        "wins": wins,
        "losses": losses,
        "total": total,
        "win_rate": win_rate,
    }


def calculate_total_volume(trades: list[Any]) -> Decimal:
    """
    Calculate total trading volume from trade history.

    Sums absolute value of (size * price) for all trades.

    Args:
        trades: List of trade-like objects with attributes:
               - size: Decimal (trade size, negative for SELL)
               - price: Decimal (trade price)

    Returns:
        Total volume as Decimal. Returns Decimal("0") if no trades.

    Examples:
        >>> trades = [MockTrade(size=Decimal("10"), price=Decimal("0.65"))]
        >>> calculate_total_volume(trades)
        Decimal('6.5')

        >>> trades = [
        ...     MockTrade(size=Decimal("10"), price=Decimal("0.65")),
        ...     MockTrade(size=Decimal("-20"), price=Decimal("0.5")),
        ... ]
        >>> calculate_total_volume(trades)
        Decimal('16.5')
    """
    if not trades:
        return Decimal("0")

    total_volume = Decimal("0")

    for trade in trades:
        volume = abs(trade.size * trade.price)
        total_volume += volume

    return total_volume


def calculate_unrealized_pnl(
    position: Any, current_price: Decimal
) -> dict[str, Decimal | bool | str]:
    """
    Calculate unrealized profit/loss via mark-to-market.

    Computes PnL for unresolved positions using current market price.
    LONG: pnl = size * (current_price - avg_entry_price)
    SHORT: pnl = abs(size) * (avg_entry_price - current_price)
    FLAT: pnl = 0

    Args:
        position: Position-like object with attributes:
                 - size: Decimal (net shares, positive=long, negative=short, zero=flat)
                 - direction: str ("LONG", "SHORT", or "FLAT")
                 - avg_entry_price: Decimal | None (weighted average entry price)
        current_price: Current market price for mark-to-market calculation

    Returns:
        Dictionary with:
            - pnl: Decimal (unrealized profit/loss)
            - unrealized: bool (always True to flag as unrealized)
            - direction: str (optional, position direction)
            - current_price: Decimal (optional, current market price)

    Examples:
        >>> position = MockPosition(size=Decimal("100"), direction="LONG",
        ...                         avg_entry_price=Decimal("0.4"))
        >>> calculate_unrealized_pnl(position, Decimal("0.6"))
        {'pnl': Decimal('20'), 'unrealized': True, 'direction': 'LONG', 'current_price': Decimal('0.6')}

        >>> position = MockPosition(size=Decimal("-50"), direction="SHORT",
        ...                         avg_entry_price=Decimal("0.7"))
        >>> calculate_unrealized_pnl(position, Decimal("0.3"))
        {'pnl': Decimal('20'), 'unrealized': True, 'direction': 'SHORT', 'current_price': Decimal('0.3')}
    """
    # Handle FLAT position
    if position.size == Decimal("0"):
        return {
            "pnl": Decimal("0"),
            "unrealized": True,
        }

    # Calculate PnL based on direction
    if position.direction == "LONG":
        pnl = position.size * (current_price - position.avg_entry_price)
    else:  # SHORT
        pnl = abs(position.size) * (position.avg_entry_price - current_price)

    return {
        "pnl": pnl,
        "unrealized": True,
        "direction": position.direction,
        "current_price": current_price,
    }


def aggregate_trader_metrics(
    positions: list[Any],
    trades: list[Any],
    unrealized_positions: list[tuple[Any, Decimal]] | None = None,
) -> dict[str, Decimal | dict | int]:
    """
    Aggregate all trader performance metrics into a single snapshot.

    Combines realized PnL, unrealized PnL, win rate, and volume calculations.
    Provides a comprehensive view of trader performance across all markets.

    Args:
        positions: List of position-like objects (both resolved and unresolved)
        trades: List of trade-like objects for volume calculation
        unrealized_positions: Optional list of (position, current_price) tuples
                             for mark-to-market calculation of unresolved positions

    Returns:
        Dictionary with:
            - realized_pnl: Decimal (PnL from resolved positions)
            - unrealized_pnl: Decimal (mark-to-market PnL from unresolved positions)
            - total_pnl: Decimal (realized + unrealized)
            - win_rate: dict (from calculate_win_rate)
            - total_volume: Decimal (total trading volume)
            - resolved_markets: int (count of resolved non-voided positions)
            - unresolved_markets: int (count of unresolved positions with unrealized PnL)

    Examples:
        >>> positions = [
        ...     MockPosition(resolved=True, outcome="win", pnl=Decimal("20")),
        ...     MockPosition(resolved=False, outcome=None, pnl=None),
        ... ]
        >>> trades = [MockTrade(size=Decimal("100"), price=Decimal("0.5"))]
        >>> unrealized = [(positions[1], Decimal("0.6"))]
        >>> metrics = aggregate_trader_metrics(positions, trades, unrealized)
        >>> metrics['total_pnl']
        Decimal('30')  # Depends on position details
    """
    # Calculate realized PnL from resolved positions
    realized_pnl = calculate_realized_pnl(positions)

    # Calculate unrealized PnL from unresolved positions
    unrealized_pnl = Decimal("0")
    unresolved_count = 0

    if unrealized_positions:
        for position, current_price in unrealized_positions:
            unrealized_result = calculate_unrealized_pnl(position, current_price)
            unrealized_pnl += unrealized_result["pnl"]
            unresolved_count += 1

    # Calculate total PnL
    total_pnl = realized_pnl + unrealized_pnl

    # Calculate win rate
    win_rate = calculate_win_rate(positions)

    # Calculate total volume
    total_volume = calculate_total_volume(trades)

    # Count resolved markets (exclude voided)
    resolved_count = sum(
        1 for p in positions if p.resolved and p.outcome != "void"
    )

    return {
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "total_volume": total_volume,
        "resolved_markets": resolved_count,
        "unresolved_markets": unresolved_count,
    }
