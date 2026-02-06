"""Trade aggregation logic for producing category summaries.

aggregate_trades produces TraderCategorySummary-compatible dicts from trade lists.
group_and_aggregate groups trades by category then aggregates each group.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from .filters import TradeWithCategory


def aggregate_trades(trades: list[Any], trader_address: str, category: str) -> dict:
    """Aggregate a list of trades into a category summary.

    Args:
        trades: List of TradeResponse objects (from API models)
        trader_address: Trader wallet address
        category: Category name for this trade group

    Returns:
        Dict compatible with TraderCategorySummary model containing:
        - trader_address: str
        - category: str
        - total_volume: Decimal (sum of all trade sizes)
        - trade_count: int (number of trades)
        - first_trade: datetime (earliest timestamp)
        - last_trade: datetime (latest timestamp)

    Raises:
        ValueError: If trades list is empty
    """
    if not trades:
        raise ValueError("Cannot aggregate empty trade list")

    # Initialize accumulators
    total_volume = Decimal("0")
    first_trade = trades[0].timestamp
    last_trade = trades[0].timestamp

    # Accumulate values
    for trade in trades:
        # Sum volume using Decimal arithmetic (no float precision loss)
        total_volume += trade.size

        # Track date range
        if trade.timestamp < first_trade:
            first_trade = trade.timestamp
        if trade.timestamp > last_trade:
            last_trade = trade.timestamp

    return {
        "trader_address": trader_address,
        "category": category,
        "total_volume": total_volume,
        "trade_count": len(trades),
        "first_trade": first_trade,
        "last_trade": last_trade,
    }


def group_and_aggregate(trades: list[TradeWithCategory], trader_address: str) -> list[dict]:
    """Group trades by category and aggregate each group.

    Args:
        trades: List of TradeWithCategory objects
        trader_address: Trader wallet address

    Returns:
        List of aggregated summary dicts (one per category)
    """
    if not trades:
        return []

    # Group trades by category
    groups: dict[str, list[Any]] = {}
    for trade_with_cat in trades:
        category = trade_with_cat.category
        if category not in groups:
            groups[category] = []
        groups[category].append(trade_with_cat.trade)

    # Aggregate each group
    summaries = []
    for category, category_trades in groups.items():
        summary = aggregate_trades(category_trades, trader_address, category)
        summaries.append(summary)

    return summaries
