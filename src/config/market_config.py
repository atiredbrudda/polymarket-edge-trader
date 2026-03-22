"""Per-category market configuration for lift-based scoring.

Defines min_positions thresholds and actionable flags per category.
Based on backtest evidence (348 experiments across 5 markets).

NBA is intentionally absent — signal=0.12, not scorable.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketConfig:
    """Configuration for a scorable market category.

    Attributes:
        min_positions: Minimum resolved positions required for scoring inclusion.
        actionable: True if Q5 signals from this category should trigger trades.
    """

    min_positions: int
    actionable: bool


MARKET_CONFIGS: dict[str, MarketConfig] = {
    "esports": MarketConfig(min_positions=30, actionable=True),
    "epl": MarketConfig(min_positions=10, actionable=True),
    "politics": MarketConfig(min_positions=30, actionable=True),
    "la-liga": MarketConfig(min_positions=20, actionable=False),
    "ligue-1": MarketConfig(min_positions=10, actionable=False),
}
# NBA intentionally absent -- signal=0.12, not scorable.


def get_market_config(category: str) -> MarketConfig | None:
    """Look up market configuration for a category.

    Case-insensitive. Returns None for unknown or non-scorable categories (e.g., NBA).

    Args:
        category: Category name (e.g., "esports", "eSports", "epl").

    Returns:
        MarketConfig if category is scorable, None otherwise.

    Examples:
        >>> get_market_config("esports")
        MarketConfig(min_positions=30, actionable=True)
        >>> get_market_config("eSports")
        MarketConfig(min_positions=30, actionable=True)
        >>> get_market_config("nba")
        None
    """
    return MARKET_CONFIGS.get(category.lower())
