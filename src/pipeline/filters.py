"""Category-based trade filtering for routing to detail or summary storage.

CategoryFilter implements config-driven routing logic - trades in detail_categories
go to full storage, others go to aggregate summaries.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class TradeWithCategory:
    """Associates a trade with its market's category.

    This wrapper avoids adding category directly to TradeResponse
    (which mirrors API structure).
    """

    trade: Any  # TradeResponse from API models (Plan 02)
    category: str


class CategoryFilter:
    """Routes trades to detail or summary storage based on category configuration.

    Uses a set of lowercased category names for O(1) case-insensitive lookup.
    """

    def __init__(self, detail_categories: list[str]):
        """Initialize filter with list of categories requiring full detail storage.

        Args:
            detail_categories: List of category names to store in full detail
        """
        # Store lowercased versions for case-insensitive matching
        self._detail_categories = {cat.lower() for cat in detail_categories}

    def requires_detail(self, category: str) -> bool:
        """Check if category requires full detail storage.

        Args:
            category: Category name to check

        Returns:
            True if category matches a detail category (case-insensitive)
        """
        return category.lower() in self._detail_categories

    def route_trades(
        self, trades: list[TradeWithCategory]
    ) -> tuple[list[TradeWithCategory], list[TradeWithCategory]]:
        """Split trades into detail and summary lists based on category.

        Args:
            trades: List of trades with associated categories

        Returns:
            Tuple of (detail_trades, summary_trades)
        """
        detail_trades = []
        summary_trades = []

        for trade in trades:
            if self.requires_detail(trade.category):
                detail_trades.append(trade)
            else:
                summary_trades.append(trade)

        return detail_trades, summary_trades
