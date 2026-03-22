"""Pure functions for consensus detection and first-mover identification.

This module provides stateless consensus detection following the pure-function,
duck-typed pattern from position_tracker.py and metrics.py. All functions accept
simple data objects and use Decimal arithmetic for financial precision.

Design principles:
- Pure functions, no classes or state
- Duck-typed inputs (works with any object having the right attributes)
- All financial math uses Decimal, never float
- No SQLAlchemy imports (keeps module pure and decoupled)

Consensus detection:
- Caller pre-filters to Q5 experts only (LiftScore quintile==5)
- Any trader present in expert_scores dict is treated as an expert
- Excludes FLAT positions (only LONG/SHORT count)
- Agreement % uses total market experts as denominator (not just one direction)
- Requires both min_experts AND min_agreement_pct thresholds
- ConsensusResult includes expert_avg_entry: avg entry price across expert positions

First-mover identification:
- Finds earliest entry_timestamp among experts in a direction
- Returns None if no valid timestamps
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ConsensusResult:
    """Immutable consensus detection result.

    Attributes:
        market_id: Market identifier
        direction: Consensus direction ("LONG" or "SHORT")
        expert_count: Number of experts agreeing on this direction
        total_experts_in_market: Total unique experts in market (across all directions)
        agreement_percentage: Percentage of experts agreeing (expert_count / total_experts * 100)
        expert_positions: List of position objects for experts in this direction
        first_mover_address: Trader address of earliest entry, or None if no timestamps
        expert_avg_entry: Average avg_entry_price across expert positions in this direction,
                         or None if no positions have entry prices.
    """

    market_id: str
    direction: str
    expert_count: int
    total_experts_in_market: int
    agreement_percentage: Decimal
    expert_positions: list[Any]
    first_mover_address: str | None
    expert_avg_entry: Decimal | None


def detect_consensus(
    positions: list[Any],
    expert_scores: dict[str, Decimal],
    min_experts: int = 3,
    min_agreement_pct: Decimal = Decimal("75"),
) -> list[ConsensusResult]:
    """Detect consensus among expert traders in markets.

    A consensus is detected when:
    1. min_experts or more experts agree on a direction (LONG or SHORT)
    2. Agreement percentage >= min_agreement_pct (calculated as experts_in_direction / total_experts_in_market * 100)

    FLAT positions are excluded from both numerator and denominator.

    The caller is responsible for pre-filtering expert_scores to Q5 traders only
    (LiftScore quintile==5). Any trader present in the expert_scores dict is treated
    as an expert — no additional score threshold is applied here.

    Args:
        positions: List of position-like objects with attributes:
                  - market_id: str
                  - trader_address: str
                  - direction: str ("LONG", "SHORT", or "FLAT")
                  - size: Decimal
                  - avg_entry_price: Decimal | None
                  - entry_timestamp: datetime | None
        expert_scores: Dict mapping trader_address -> composite_score (Decimal).
                      Any trader present in this dict is treated as an expert (Q5 pre-filtered).
        min_experts: Minimum number of experts required for consensus (default: 3)
        min_agreement_pct: Minimum agreement percentage required (default: 75)

    Returns:
        List of ConsensusResult objects for each (market_id, direction) meeting thresholds.
        Empty list if no consensus detected.

    Examples:
        >>> positions = [
        ...     MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1)),
        ...     MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2)),
        ...     MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3)),
        ... ]
        >>> expert_scores = {"trader1": Decimal("2.5"), "trader2": Decimal("2.0"), "trader3": Decimal("1.9")}
        >>> results = detect_consensus(positions, expert_scores)
        >>> results[0].expert_count
        3
        >>> results[0].agreement_percentage
        Decimal('100')
    """
    if not positions:
        return []

    # Filter to expert positions only: trader must be present in expert_scores dict (Q5 pre-filtered)
    expert_positions = [
        p for p in positions if p.trader_address in expert_scores
    ]

    # Filter to LONG/SHORT only (exclude FLAT)
    active_positions = [p for p in expert_positions if p.direction in ("LONG", "SHORT")]

    if not active_positions:
        return []

    # Group positions by (market_id, direction)
    from collections import defaultdict

    market_direction_groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for position in active_positions:
        key = (position.market_id, position.direction)
        market_direction_groups[key].append(position)

    # Count total unique experts per market (across all directions)
    market_expert_counts: dict[str, int] = {}
    for position in active_positions:
        if position.market_id not in market_expert_counts:
            # Count unique expert traders in this market
            unique_experts = {
                p.trader_address
                for p in active_positions
                if p.market_id == position.market_id
            }
            market_expert_counts[position.market_id] = len(unique_experts)

    # Evaluate each (market_id, direction) group for consensus
    results: list[ConsensusResult] = []
    for (market_id, direction), group_positions in market_direction_groups.items():
        # Count unique experts in this direction
        unique_experts_in_direction = {p.trader_address for p in group_positions}
        expert_count = len(unique_experts_in_direction)

        # Get total experts in market
        total_experts = market_expert_counts[market_id]

        # Calculate agreement percentage
        agreement_pct = (Decimal(expert_count) / Decimal(total_experts)) * 100

        # Check thresholds
        if expert_count >= min_experts and agreement_pct >= min_agreement_pct:
            # Identify first mover
            first_mover = identify_first_mover(group_positions)

            # Compute expert_avg_entry: average of non-None avg_entry_price
            entry_prices = [
                p.avg_entry_price
                for p in group_positions
                if p.avg_entry_price is not None
            ]
            if entry_prices:
                expert_avg_entry: Decimal | None = sum(entry_prices, Decimal("0")) / Decimal(len(entry_prices))
            else:
                expert_avg_entry = None

            result = ConsensusResult(
                market_id=market_id,
                direction=direction,
                expert_count=expert_count,
                total_experts_in_market=total_experts,
                agreement_percentage=agreement_pct,
                expert_positions=group_positions,
                first_mover_address=first_mover,
                expert_avg_entry=expert_avg_entry,
            )
            results.append(result)

    return results


def identify_first_mover(positions: list[Any]) -> str | None:
    """Identify the first mover (earliest entry) among positions.

    Args:
        positions: List of position-like objects with attributes:
                  - trader_address: str
                  - entry_timestamp: datetime | None

    Returns:
        trader_address of position with earliest entry_timestamp,
        or None if no positions have valid timestamps.

    Examples:
        >>> positions = [
        ...     MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3)),
        ...     MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 1)),
        ... ]
        >>> identify_first_mover(positions)
        'trader2'
    """
    if not positions:
        return None

    # Filter to positions with valid entry_timestamp
    valid_positions = [p for p in positions if p.entry_timestamp is not None]

    if not valid_positions:
        return None

    # Find position with earliest entry_timestamp
    earliest = min(valid_positions, key=lambda p: p.entry_timestamp)
    return earliest.trader_address


def classify_followers(
    positions: list[Any], first_mover_address: str, fast_follower_hours: int = 6
) -> dict[str, str]:
    """Classify traders as first-mover, fast-follower, or independent.

    This is metadata only - does NOT affect consensus or confidence calculations.

    Args:
        positions: List of position-like objects with attributes:
                  - trader_address: str
                  - entry_timestamp: datetime | None
        first_mover_address: Trader address of the first mover
        fast_follower_hours: Time window in hours for fast follower classification (default: 6)

    Returns:
        Dict mapping trader_address -> classification:
        - "first_mover": The identified first mover
        - "fast_follower": Entered within fast_follower_hours of first mover
        - "independent": All others (entered after window or no timestamp)

    Examples:
        >>> base_time = datetime(2024, 1, 1, 12, 0)
        >>> positions = [
        ...     MockPosition("market1", "first", "LONG", Decimal("100"), Decimal("0.5"), base_time),
        ...     MockPosition("market1", "fast", "LONG", Decimal("200"), Decimal("0.5"), base_time + timedelta(hours=3)),
        ... ]
        >>> classify_followers(positions, "first", fast_follower_hours=6)
        {'first': 'first_mover', 'fast': 'fast_follower'}
    """
    classifications: dict[str, str] = {}

    # Find first mover's entry timestamp
    first_mover_timestamp: datetime | None = None
    for position in positions:
        if position.trader_address == first_mover_address:
            first_mover_timestamp = position.entry_timestamp
            classifications[first_mover_address] = "first_mover"
            break

    # If first mover has no timestamp, everyone else is independent
    if first_mover_timestamp is None:
        for position in positions:
            if position.trader_address != first_mover_address:
                classifications[position.trader_address] = "independent"
        return classifications

    # Calculate time window
    fast_follower_window = timedelta(hours=fast_follower_hours)

    # Classify other traders
    for position in positions:
        if position.trader_address == first_mover_address:
            continue  # Already classified

        if position.entry_timestamp is None:
            classifications[position.trader_address] = "independent"
        else:
            time_diff = position.entry_timestamp - first_mover_timestamp
            if time_diff <= fast_follower_window:
                classifications[position.trader_address] = "fast_follower"
            else:
                classifications[position.trader_address] = "independent"

    return classifications
