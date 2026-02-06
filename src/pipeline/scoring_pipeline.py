"""Orchestration layer for scoring pipeline.

This module connects the pure scoring logic (src.evaluation.scoring) to the database layer.
It computes expertise scores for all traders in a game, stores score snapshots for history,
and provides leaderboard generation.

Pipeline flow:
1. Query positions for game
2. Group by trader
3. Calculate concentrations per trader
4. Retrieve consistency data per trader
5. Compute expertise scores
6. Normalize to percentiles
7. Persist ExpertiseScore snapshots
8. Return LeaderboardEntry list

Design principles:
- Append-only score history (INSERT new rows on each run)
- Batch processing for efficiency (all traders at once)
- Percentile normalization for population-relative ranking
"""

from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from sqlalchemy import select

from src.db.models import ExpertiseScore, MarketClassification, PerformanceSnapshot, Position, TaxonomyNode
from src.evaluation.concentration import (
    calculate_esports_concentration,
    calculate_game_concentration,
)
from src.evaluation.metrics import calculate_total_volume
from src.evaluation.scoring import calculate_expertise_score, normalize_scores_to_percentiles
from src.pipeline.queries import get_all_game_slugs_with_positions, get_positions_for_game


@dataclass(frozen=True)
class LeaderboardEntry:
    """Immutable leaderboard entry for a trader in a game.

    Attributes:
        rank: int - Position in leaderboard (1 = best)
        trader_address: str - Trader Ethereum address
        game_slug: str - Game identifier
        raw_score: Decimal - Weighted composite score (0-100)
        percentile_rank: Decimal - Population-relative rank (0-100)
        win_rate: Decimal | None - Win rate percentage (0-100), None if no wins/losses
        realized_pnl: Decimal - Total realized PnL
        trade_count: int - Number of resolved positions
        unique_markets: int - Number of unique markets traded
        last_active: datetime | None - Timestamp of last trade
        specialization_label: str - "specialist/specialist", "specialist/generalist", etc.
    """

    rank: int
    trader_address: str
    game_slug: str
    raw_score: Decimal
    percentile_rank: Decimal
    win_rate: Decimal | None
    realized_pnl: Decimal
    trade_count: int
    unique_markets: int
    last_active: datetime | None
    specialization_label: str


def _compute_position_volume(position: Any) -> Decimal:
    """Compute volume proxy for a position.

    Uses abs(size * avg_entry_price) if avg_entry_price available,
    otherwise falls back to abs(size).

    Args:
        position: Position-like object with size and avg_entry_price attributes

    Returns:
        Volume as Decimal
    """
    if position.avg_entry_price is not None:
        return abs(position.size * position.avg_entry_price)
    else:
        return abs(position.size)


def _get_all_trader_positions(session: Session, trader_address: str) -> list[Any]:
    """Query ALL positions for a trader (across all categories).

    Used to compute total_volume for eSports concentration ratio.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        List of Position ORM objects
    """
    query = select(Position).where(Position.trader_address == trader_address)
    result = session.execute(query)
    return list(result.scalars().all())


def _get_esports_positions(session: Session, trader_address: str) -> list[Any]:
    """Query all eSports positions for a trader.

    Joins Position -> MarketClassification -> TaxonomyNode where slug LIKE 'esports%'.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        List of Position ORM objects in eSports markets
    """
    query = (
        select(Position)
        .join(MarketClassification, Position.market_id == MarketClassification.market_id)
        .join(TaxonomyNode, MarketClassification.taxonomy_node_id == TaxonomyNode.id)
        .where(TaxonomyNode.slug.like("esports%"))
        .where(Position.trader_address == trader_address)
    )
    result = session.execute(query)
    return list(result.scalars().all())


def _get_consistency_data(session: Session, trader_address: str) -> tuple[Decimal, str]:
    """Retrieve consistency data from PerformanceSnapshot.

    Queries PerformanceSnapshot for timeframe="all" to get consistency score and signal.
    Returns defaults if snapshot doesn't exist or consistency data is None.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        Tuple of (consistency_score, consistency_signal)
        Defaults: (Decimal("50"), "insufficient_data")
    """
    query = (
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.trader_address == trader_address)
        .where(PerformanceSnapshot.timeframe == "all")
    )

    result = session.execute(query)
    snapshot = result.scalar_one_or_none()

    # If snapshot exists AND consistency_score is not None, use stored values
    if snapshot is not None and snapshot.consistency_score is not None:
        return snapshot.consistency_score, snapshot.consistency_signal or "insufficient_data"

    # Otherwise return defaults
    return Decimal("50"), "insufficient_data"


def compute_game_scores(
    session: Session,
    game_slug: str,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> list[LeaderboardEntry]:
    """Compute expertise scores for all traders in a game.

    Pipeline:
    1. Query all positions for game
    2. Group by trader_address
    3. Filter to traders with >= 5 resolved markets
    4. Calculate concentrations per trader
    5. Retrieve consistency data per trader
    6. Compute expertise scores
    7. Normalize to percentiles
    8. Persist ExpertiseScore snapshots (INSERT new rows)
    9. Build LeaderboardEntry list
    10. Return sorted by percentile_rank DESC

    Args:
        session: SQLAlchemy session
        game_slug: Game identifier (e.g., "esports.cs2")
        weights: Optional custom scoring weights
        now: Optional current timestamp (default: datetime.now(UTC))

    Returns:
        List of LeaderboardEntry objects sorted by percentile_rank DESC
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Get all positions for game
    all_positions = get_positions_for_game(session, game_slug)

    # 2. Group by trader_address
    positions_by_trader: dict[str, list[Any]] = {}
    for position in all_positions:
        if position.trader_address not in positions_by_trader:
            positions_by_trader[position.trader_address] = []
        positions_by_trader[position.trader_address].append(position)

    # 3-7. Compute scores per trader
    score_results = {}
    for trader_address, trader_positions in positions_by_trader.items():
        # Filter to resolved, non-void positions
        resolved_positions = [
            p for p in trader_positions if p.resolved and p.outcome != "void"
        ]

        # Skip if < 5 resolved markets
        if len(resolved_positions) < 5:
            continue

        # Calculate concentrations from actual trader position volumes
        game_volume = sum(
            (_compute_position_volume(p) for p in trader_positions), Decimal("0")
        )

        # Get all eSports positions and total positions for this trader
        esports_positions = _get_esports_positions(session, trader_address)
        esports_volume = sum(
            (_compute_position_volume(p) for p in esports_positions), Decimal("0")
        )

        all_positions = _get_all_trader_positions(session, trader_address)
        total_volume = sum(
            (_compute_position_volume(p) for p in all_positions), Decimal("0")
        )

        # Compute concentration ratios
        esports_concentration = calculate_esports_concentration(esports_volume, total_volume)
        game_concentration = calculate_game_concentration(game_volume, esports_volume)

        # Retrieve consistency data
        consistency_score, consistency_signal = _get_consistency_data(session, trader_address)

        # Compute expertise score
        result = calculate_expertise_score(
            positions=trader_positions,
            trader_address=trader_address,
            game_slug=game_slug,
            esports_concentration=esports_concentration,
            game_concentration=game_concentration,
            consistency_score=consistency_score,
            consistency_signal=consistency_signal,
            weights=weights,
            now=now,
        )

        if result is not None:
            score_results[trader_address] = result

    # 8. Normalize to percentiles
    raw_scores = {addr: result.raw_score for addr, result in score_results.items()}
    percentiles = normalize_scores_to_percentiles(raw_scores)

    # 9. Persist ExpertiseScore snapshots
    for trader_address, result in score_results.items():
        expertise_score = ExpertiseScore(
            trader_address=trader_address,
            game_slug=game_slug,
            raw_score=result.raw_score,
            percentile_rank=percentiles[trader_address],
            win_rate_component=result.win_rate_component,
            concentration_component=result.concentration_component,
            recency_component=result.recency_component,
            sample_size_component=result.sample_size_component,
            consistency_multiplier=result.consistency_multiplier,
            specialization_label=result.specialization_label,
            resolved_market_count=result.resolved_market_count,
            computed_at=now,
        )
        session.add(expertise_score)

    session.commit()

    # 10. Build LeaderboardEntry list
    leaderboard: list[LeaderboardEntry] = []
    for trader_address, result in score_results.items():
        trader_positions = positions_by_trader[trader_address]
        resolved_positions = [
            p for p in trader_positions if p.resolved and p.outcome != "void"
        ]

        # Calculate metrics
        realized_pnl = sum(
            (p.pnl for p in resolved_positions if p.pnl is not None), Decimal("0")
        )

        trade_count = len(resolved_positions)

        unique_markets = len(set(p.market_id for p in trader_positions))

        last_active = max(
            (p.last_trade_timestamp for p in trader_positions if p.last_trade_timestamp),
            default=None,
        )

        # Win rate from result
        win_rate = result.win_rate_component if result.win_rate_component > Decimal("0") else None

        leaderboard.append(
            LeaderboardEntry(
                rank=0,  # Will be set after sorting
                trader_address=trader_address,
                game_slug=game_slug,
                raw_score=result.raw_score,
                percentile_rank=percentiles[trader_address],
                win_rate=win_rate,
                realized_pnl=realized_pnl,
                trade_count=trade_count,
                unique_markets=unique_markets,
                last_active=last_active,
                specialization_label=result.specialization_label,
            )
        )

    # Sort by percentile_rank DESC
    leaderboard.sort(key=lambda x: x.percentile_rank, reverse=True)

    # Assign ranks
    leaderboard = [
        LeaderboardEntry(
            rank=idx + 1,
            trader_address=entry.trader_address,
            game_slug=entry.game_slug,
            raw_score=entry.raw_score,
            percentile_rank=entry.percentile_rank,
            win_rate=entry.win_rate,
            realized_pnl=entry.realized_pnl,
            trade_count=entry.trade_count,
            unique_markets=entry.unique_markets,
            last_active=entry.last_active,
            specialization_label=entry.specialization_label,
        )
        for idx, entry in enumerate(leaderboard)
    ]

    return leaderboard


def compute_all_game_scores(
    session: Session,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> dict[str, list[LeaderboardEntry]]:
    """Compute expertise scores for all games.

    Args:
        session: SQLAlchemy session
        weights: Optional custom scoring weights
        now: Optional current timestamp (default: datetime.now(UTC))

    Returns:
        Dict mapping game_slug -> leaderboard
    """
    game_slugs = get_all_game_slugs_with_positions(session)

    results = {}
    for game_slug in game_slugs:
        leaderboard = compute_game_scores(session, game_slug, weights=weights, now=now)
        results[game_slug] = leaderboard

    return results
