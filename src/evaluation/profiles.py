"""
Trader profile classification (selective vs active).

Pure functions for classifying traders based on their market participation patterns.

Design principles:
- Pure functions, no state
- Duck-typed position input (works with any object having market_id attribute)
- Classification based on unique markets, not trade count (per user decision)
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TraderProfile:
    """
    Immutable trader profile classification result.

    Attributes:
        trader_address: Trader's address
        profile_type: "selective" or "active"
        unique_markets: Count of unique markets entered
        total_trades: Total number of trades/positions
        threshold_used: Threshold value used for classification
    """
    trader_address: str
    profile_type: str
    unique_markets: int
    total_trades: int
    threshold_used: int


def classify_trader_profile(
    positions: list[Any],
    trader_address: str,
    threshold: int = 10,
) -> TraderProfile:
    """
    Classify trader as 'selective' or 'active' based on unique markets entered.

    Per user decision: Classification uses unique markets count, NOT trade count.
    A trader with 50 trades on 3 markets is "selective" (focused).
    A trader with 15 trades on 15 markets is "active" (broad).

    Args:
        positions: List of position-like objects with market_id attribute
        trader_address: Trader's address
        threshold: Unique markets threshold (default 10 per research recommendation)

    Returns:
        TraderProfile with classification result

    Classification logic:
        - unique_markets < threshold → "selective"
        - unique_markets >= threshold → "active"

    Examples:
        >>> positions = [MockPosition("m1", "0xabc"), MockPosition("m2", "0xabc")]
        >>> profile = classify_trader_profile(positions, "0xabc", threshold=10)
        >>> profile.profile_type
        'selective'
        >>> profile.unique_markets
        2

        >>> positions = [MockPosition(f"m{i}", "0xabc") for i in range(15)]
        >>> profile = classify_trader_profile(positions, "0xabc", threshold=10)
        >>> profile.profile_type
        'active'
    """
    # Count unique markets
    unique_markets_set = {p.market_id for p in positions}
    unique_markets = len(unique_markets_set)

    # Total trades is just the position count
    total_trades = len(positions)

    # Classify based on unique markets vs threshold
    if unique_markets < threshold:
        profile_type = "selective"
    else:
        profile_type = "active"

    return TraderProfile(
        trader_address=trader_address,
        profile_type=profile_type,
        unique_markets=unique_markets,
        total_trades=total_trades,
        threshold_used=threshold,
    )


def get_profile_consistency_bar(profile_type: str) -> dict:
    """
    Get consistency thresholds for a trader profile type.

    Per user decision: Different consistency bars per profile.
    - Selective traders: Need stability across fewer windows, looser variance
    - Active traders: Tighter variance bar (more data means tighter requirements)

    Args:
        profile_type: "selective" or "active"

    Returns:
        Dictionary with:
            - min_timeframes: Minimum timeframes needed for consistency check
            - max_variance: Maximum allowed variance for consistency

    Raises:
        ValueError: If profile_type is unknown

    Examples:
        >>> get_profile_consistency_bar("selective")
        {'min_timeframes': 2, 'max_variance': 100}

        >>> get_profile_consistency_bar("active")
        {'min_timeframes': 2, 'max_variance': 50}

    Note:
        These thresholds are starting points that will be tuned via validation
        framework in later phases.
    """
    if profile_type == "selective":
        return {
            "min_timeframes": 2,
            "max_variance": 100,  # Looser bar (fewer data points)
        }
    elif profile_type == "active":
        return {
            "min_timeframes": 2,
            "max_variance": 50,  # Tighter bar (more data points)
        }
    else:
        raise ValueError(f"Unknown profile type: {profile_type}")
