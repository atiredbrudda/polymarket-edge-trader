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
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from sqlalchemy import func, select

from src.db.models import (
    ExpertiseScore,
    MarketEntity,
    PerformanceSnapshot,
    Position,
)
from src.evaluation.concentration import (
    calculate_esports_concentration,
    calculate_game_concentration,
    calculate_team_concentration,
    calculate_tournament_concentration,
)
from src.evaluation.metrics import calculate_total_volume
from src.evaluation.scoring import (
    calculate_expertise_score,
    normalize_scores_to_percentiles,
)
from src.pipeline.queries import (
    get_all_game_slugs_with_positions,
    get_all_slugs_with_positions_at_depth,
    get_positions_for_game,
    get_positions_for_slug,
)


@dataclass(frozen=True)
class LeaderboardEntry:
    """Immutable leaderboard entry for a trader in a game.

    Attributes:
        rank: int - Position in leaderboard (1 = best)
        trader_address: str - Trader Ethereum address
        game_slug: str - Game identifier
        taxonomy_depth: int - Taxonomy depth (1=game, 2=tournament, 3=team)
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
    taxonomy_depth: int
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

    Joins Position -> MarketEntity where game IS NOT NULL.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        List of Position ORM objects in eSports markets
    """
    query = (
        select(Position)
        .join(MarketEntity, Position.market_id == MarketEntity.condition_id)
        .where(MarketEntity.game.isnot(None))
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
        return (
            snapshot.consistency_score,
            snapshot.consistency_signal or "insufficient_data",
        )

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
        esports_concentration = calculate_esports_concentration(
            esports_volume, total_volume
        )
        game_concentration = calculate_game_concentration(game_volume, esports_volume)

        # Retrieve consistency data
        consistency_score, consistency_signal = _get_consistency_data(
            session, trader_address
        )

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
            taxonomy_depth=1,
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
            (
                p.last_trade_timestamp
                for p in trader_positions
                if p.last_trade_timestamp
            ),
            default=None,
        )

        # Win rate from result
        win_rate = (
            result.win_rate_component
            if result.win_rate_component > Decimal("0")
            else None
        )

        leaderboard.append(
            LeaderboardEntry(
                rank=0,  # Will be set after sorting
                trader_address=trader_address,
                game_slug=game_slug,
                taxonomy_depth=1,
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
            taxonomy_depth=entry.taxonomy_depth,
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


def _get_positions_for_depth(
    session: Session,
    slug: str,
    taxonomy_depth: int,
    trader_address: str | None = None,
) -> tuple[list[Any], Decimal]:
    """Get positions at a specific taxonomy depth and compute parent volume.

    Args:
        session: SQLAlchemy session
        slug: The entity name to query
        taxonomy_depth: Depth of the slug (1=game, 2=tournament, 3=team)
        trader_address: Optional trader filter

    Returns:
        Tuple of (positions list, parent_volume Decimal)
    """
    positions = get_positions_for_slug(session, slug, trader_address=trader_address)

    if not positions:
        return [], Decimal("0")

    current_volume = sum((_compute_position_volume(p) for p in positions), Decimal("0"))

    if taxonomy_depth <= 1:
        return positions, Decimal("0")

    # For depth 2 (tournament): parent is the game
    # For depth 3 (team): parent is the tournament
    # Look up the parent entity from MarketEntity
    if taxonomy_depth == 2:
        # slug is a tournament name; find its game
        parent_name = session.execute(
            select(MarketEntity.game)
            .where(MarketEntity.tournament == slug)
            .where(MarketEntity.game.isnot(None))
            .limit(1)
        ).scalar_one_or_none()
    else:
        # slug is a team name; find its tournament
        parent_name = session.execute(
            select(MarketEntity.tournament)
            .where((MarketEntity.team_a == slug) | (MarketEntity.team_b == slug))
            .where(MarketEntity.tournament.isnot(None))
            .limit(1)
        ).scalar_one_or_none()

    if parent_name:
        parent_positions = get_positions_for_slug(
            session, parent_name, trader_address=trader_address
        )
        parent_volume = sum(
            (_compute_position_volume(p) for p in parent_positions), Decimal("0")
        )
    else:
        parent_volume = Decimal("0")

    return positions, parent_volume


def compute_taxonomy_scores(
    session: Session,
    slug: str,
    taxonomy_depth: int,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> list[LeaderboardEntry]:
    """Compute expertise scores for all traders at a specific taxonomy depth.

    Similar to compute_game_scores but generalizes to tournament (depth 2) and team (depth 3).

    Pipeline:
    1. Query positions for slug at given depth
    2. Group by trader_address
    3. Filter to traders with >= 5 resolved markets
    4. Calculate concentrations per trader (depth-appropriate)
    5. Retrieve consistency data per trader
    6. Compute expertise scores
    7. Normalize to percentiles
    8. Persist ExpertiseScore snapshots with taxonomy_depth
    9. Build LeaderboardEntry list
    10. Return sorted by percentile_rank DESC

    Args:
        session: SQLAlchemy session
        slug: Taxonomy identifier (e.g., "esports.cs2.iem-katowice")
        taxonomy_depth: Depth level (1=game, 2=tournament, 3=team)
        weights: Optional custom scoring weights
        now: Optional current timestamp (default: datetime.now(UTC))

    Returns:
        List of LeaderboardEntry objects sorted by percentile_rank DESC
    """
    if now is None:
        now = datetime.now(UTC)

    positions_by_trader: dict[str, list[Any]] = {}
    trader_parent_volumes: dict[str, Decimal] = {}

    # Determine which column to filter by based on depth
    if taxonomy_depth == 1:
        entity_filter = MarketEntity.game == slug
    elif taxonomy_depth == 2:
        entity_filter = MarketEntity.tournament == slug
    else:
        entity_filter = (MarketEntity.team_a == slug) | (MarketEntity.team_b == slug)

    trader_addresses = (
        session.execute(
            select(Position.trader_address)
            .join(MarketEntity, Position.market_id == MarketEntity.condition_id)
            .where(entity_filter)
            .distinct()
        )
        .scalars()
        .all()
    )

    for trader_address in trader_addresses:
        positions, parent_volume = _get_positions_for_depth(
            session, slug, taxonomy_depth, trader_address
        )
        if positions:
            positions_by_trader[trader_address] = positions
            trader_parent_volumes[trader_address] = parent_volume

    score_results = {}
    for trader_address, trader_positions in positions_by_trader.items():
        resolved_positions = [
            p for p in trader_positions if p.resolved and p.outcome != "void"
        ]

        if len(resolved_positions) < 5:
            continue

        slug_volume = sum(
            (_compute_position_volume(p) for p in trader_positions), Decimal("0")
        )

        esports_positions = _get_esports_positions(session, trader_address)
        esports_volume = sum(
            (_compute_position_volume(p) for p in esports_positions), Decimal("0")
        )

        all_positions = _get_all_trader_positions(session, trader_address)
        total_volume = sum(
            (_compute_position_volume(p) for p in all_positions), Decimal("0")
        )

        esports_concentration = calculate_esports_concentration(
            esports_volume, total_volume
        )

        parent_volume = trader_parent_volumes.get(trader_address, Decimal("0"))
        if taxonomy_depth == 2:
            game_concentration = calculate_tournament_concentration(
                slug_volume, parent_volume
            )
        elif taxonomy_depth == 3:
            game_concentration = calculate_team_concentration(
                slug_volume, parent_volume
            )
        else:
            game_concentration = calculate_game_concentration(
                slug_volume, esports_volume
            )

        consistency_score, consistency_signal = _get_consistency_data(
            session, trader_address
        )

        result = calculate_expertise_score(
            positions=trader_positions,
            trader_address=trader_address,
            game_slug=slug,
            esports_concentration=esports_concentration,
            game_concentration=game_concentration,
            consistency_score=consistency_score,
            consistency_signal=consistency_signal,
            weights=weights,
            now=now,
        )

        if result is not None:
            score_results[trader_address] = result

    raw_scores = {addr: result.raw_score for addr, result in score_results.items()}
    percentiles = normalize_scores_to_percentiles(raw_scores)

    for trader_address, result in score_results.items():
        expertise_score = ExpertiseScore(
            trader_address=trader_address,
            game_slug=slug,
            taxonomy_depth=taxonomy_depth,
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

    leaderboard: list[LeaderboardEntry] = []
    for trader_address, result in score_results.items():
        trader_positions = positions_by_trader[trader_address]
        resolved_positions = [
            p for p in trader_positions if p.resolved and p.outcome != "void"
        ]

        realized_pnl = sum(
            (p.pnl for p in resolved_positions if p.pnl is not None), Decimal("0")
        )

        trade_count = len(resolved_positions)

        unique_markets = len(set(p.market_id for p in trader_positions))

        last_active = max(
            (
                p.last_trade_timestamp
                for p in trader_positions
                if p.last_trade_timestamp
            ),
            default=None,
        )

        win_rate = (
            result.win_rate_component
            if result.win_rate_component > Decimal("0")
            else None
        )

        leaderboard.append(
            LeaderboardEntry(
                rank=0,
                trader_address=trader_address,
                game_slug=slug,
                taxonomy_depth=taxonomy_depth,
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

    leaderboard.sort(key=lambda x: x.percentile_rank, reverse=True)

    leaderboard = [
        LeaderboardEntry(
            rank=idx + 1,
            trader_address=entry.trader_address,
            game_slug=entry.game_slug,
            taxonomy_depth=entry.taxonomy_depth,
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


def compute_all_taxonomy_scores(
    session: Session,
    depth: int,
    weights: dict[str, Decimal] | None = None,
    now: datetime | None = None,
) -> dict[str, list[LeaderboardEntry]]:
    """Compute scores for all slugs at a given taxonomy depth.

    Args:
        session: SQLAlchemy session
        depth: Taxonomy depth (1=game, 2=tournament, 3=team)
        weights: Optional custom scoring weights
        now: Optional current timestamp (default: datetime.now(UTC))

    Returns:
        Dict mapping slug -> leaderboard
    """
    slugs = get_all_slugs_with_positions_at_depth(session, depth)

    results = {}
    for slug in slugs:
        leaderboard = compute_taxonomy_scores(
            session, slug, depth, weights=weights, now=now
        )
        results[slug] = leaderboard

    return results


def identify_hidden_specialists(
    session: Session,
    game_slug: str,
    game_score_threshold: Decimal = Decimal("60"),
    deep_score_threshold: Decimal = Decimal("75"),
) -> list[dict]:
    """Identify traders with low game scores but high tournament/team scores.

    These are "hidden specialists" — traders who appear average at the game level
    but have deep expertise in specific tournaments or teams.

    Args:
        session: SQLAlchemy session
        game_slug: Game identifier (e.g., "esports.cs2")
        game_score_threshold: Max raw_score at depth 1 to consider (default 60)
        deep_score_threshold: Min raw_score at depth 2/3 to qualify (default 75)

    Returns:
        List of dicts with trader_address, game_slug, game_score, deep_slug,
        deep_depth, deep_score, score_delta. Sorted by score_delta DESC.
    """
    game_subquery = (
        select(
            ExpertiseScore.trader_address,
            ExpertiseScore.game_slug,
            ExpertiseScore.raw_score,
            func.max(ExpertiseScore.computed_at).label("max_computed_at"),
        )
        .where(ExpertiseScore.game_slug == game_slug)
        .where(ExpertiseScore.taxonomy_depth == 1)
        .where(ExpertiseScore.raw_score < game_score_threshold)
        .group_by(
            ExpertiseScore.trader_address,
            ExpertiseScore.game_slug,
            ExpertiseScore.raw_score,
        )
        .subquery()
    )

    game_scores = (
        select(ExpertiseScore)
        .join(
            game_subquery,
            (ExpertiseScore.trader_address == game_subquery.c.trader_address)
            & (ExpertiseScore.computed_at == game_subquery.c.max_computed_at),
        )
        .where(ExpertiseScore.game_slug == game_slug)
        .where(ExpertiseScore.taxonomy_depth == 1)
        .where(ExpertiseScore.raw_score < game_score_threshold)
    )

    game_results = session.execute(game_scores).scalars().all()

    hidden_specialists = []

    for game_score in game_results:
        # Find tournaments for this game
        tournament_slugs = (
            session.execute(
                select(MarketEntity.tournament)
                .where(MarketEntity.game == game_slug)
                .where(MarketEntity.tournament.isnot(None))
                .distinct()
            )
            .scalars()
            .all()
        )

        # Find teams for this game (via tournament association)
        team_slugs = (
            session.execute(
                select(MarketEntity.team_a.label("team"))
                .where(MarketEntity.game == game_slug)
                .where(MarketEntity.team_a.isnot(None))
                .union(
                    select(MarketEntity.team_b.label("team"))
                    .where(MarketEntity.game == game_slug)
                    .where(MarketEntity.team_b.isnot(None))
                )
            )
            .scalars()
            .all()
        )

        deep_slugs = set(tournament_slugs) | set(team_slugs)

        if not deep_slugs:
            continue

        deep_subquery = (
            select(
                ExpertiseScore.trader_address,
                ExpertiseScore.game_slug,
                ExpertiseScore.taxonomy_depth,
                ExpertiseScore.raw_score,
                func.max(ExpertiseScore.computed_at).label("max_computed_at"),
            )
            .where(ExpertiseScore.game_slug.in_(deep_slugs))
            .where(ExpertiseScore.taxonomy_depth.in_([2, 3]))
            .where(ExpertiseScore.raw_score >= deep_score_threshold)
            .group_by(
                ExpertiseScore.trader_address,
                ExpertiseScore.game_slug,
                ExpertiseScore.taxonomy_depth,
                ExpertiseScore.raw_score,
            )
            .subquery()
        )

        deep_scores = (
            select(ExpertiseScore)
            .join(
                deep_subquery,
                (ExpertiseScore.trader_address == deep_subquery.c.trader_address)
                & (ExpertiseScore.computed_at == deep_subquery.c.max_computed_at),
            )
            .where(ExpertiseScore.game_slug.in_(deep_slugs))
            .where(ExpertiseScore.taxonomy_depth.in_([2, 3]))
            .where(ExpertiseScore.raw_score >= deep_score_threshold)
        )

        deep_results = session.execute(deep_scores).scalars().all()

        for deep_score in deep_results:
            hidden_specialists.append(
                {
                    "trader_address": game_score.trader_address,
                    "game_slug": game_slug,
                    "game_score": game_score.raw_score,
                    "deep_slug": deep_score.game_slug,
                    "deep_depth": deep_score.taxonomy_depth,
                    "deep_score": deep_score.raw_score,
                    "score_delta": deep_score.raw_score - game_score.raw_score,
                }
            )

    hidden_specialists.sort(key=lambda x: x["score_delta"], reverse=True)

    return hidden_specialists


# ---------------------------------------------------------------------------
# Lift-based scoring pipeline (Phase 25)
# Replaces compute_game_scores / compute_all_game_scores as the active engine.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiftLeaderboardEntry:
    """Immutable leaderboard entry from lift-based scoring.

    Attributes:
        trader_address: Trader Ethereum address.
        composite_score: z(CLV) + z(ROI) + z(Sharpe) sum.
        clv_raw: Raw CLV value (price advantage over crowd).
        clv_zscore: Z-normalized CLV across population.
        roi_raw: Raw ROI value (total_pnl / capital_deployed).
        roi_zscore: Z-normalized ROI across population.
        sharpe_raw: Raw Sharpe ratio (avg_pnl / stddev_pnl).
        sharpe_zscore: Z-normalized Sharpe across population.
        quintile: Quintile rank 1-5 (Q5 = top 20%).
        position_count: Number of qualifying positions used.
        total_pnl: Sum of PnL across qualifying positions.
        capital_deployed: Sum of capital deployed.
    """

    trader_address: str
    composite_score: Decimal
    clv_raw: Decimal
    clv_zscore: Decimal
    roi_raw: Decimal
    roi_zscore: Decimal
    sharpe_raw: Decimal
    sharpe_zscore: Decimal
    quintile: int
    position_count: int
    total_pnl: Decimal
    capital_deployed: Decimal


def compute_category_scores(
    session: Session,
    category: str,
    window_days: int = 30,
    now: datetime | None = None,
) -> list[LiftLeaderboardEntry]:
    """Compute lift-based scores for all traders in a category.

    Pipeline:
    1. Validate category against MARKET_CONFIGS (return [] for unknown/NBA)
    2. Define 30-day rolling window
    3. Compute market avg entry prices (one SQL aggregate)
    4. Get qualified traders (>= min_positions resolved, non-void positions)
    5. Compute CLV, ROI, Sharpe per trader (pure functions)
    6. Z-score normalize across population
    7. Compute composite, assign quintiles
    8. Persist LiftScore rows (DELETE old, INSERT new)
    9. Return sorted LiftLeaderboardEntry list

    Args:
        session: SQLAlchemy session.
        category: Category name (e.g., "esports"). Case-insensitive.
        window_days: Rolling window in days (default: 30).
        now: Optional current timestamp for testing (default: datetime.now(UTC)).

    Returns:
        List of LiftLeaderboardEntry sorted by composite_score DESC.
    """
    from src.config.market_config import get_market_config, MARKET_CONFIGS
    from src.db.models import LiftScore
    from src.evaluation.lift_metrics import (
        compute_clv,
        compute_roi,
        compute_sharpe,
        compute_z_scores,
        compute_composite,
        assign_quintiles,
        LiftMetrics,
    )
    from src.pipeline.queries import get_market_avg_entries, get_positions_for_category
    from sqlalchemy import delete

    # Step 1: Validate category
    config = get_market_config(category)
    if config is None:
        return []

    # Step 2: Define window
    if now is None:
        now = datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Step 3: Market average entry prices
    market_avgs = get_market_avg_entries(session, category, window_start)

    # Step 4: Get qualified traders
    positions_by_trader = get_positions_for_category(
        session, category, window_start, config.min_positions
    )

    if not positions_by_trader:
        return []

    # Step 5: Compute raw metrics per trader
    metrics_by_trader: dict[str, LiftMetrics] = {}
    clv_raw_by_trader: dict[str, Decimal] = {}
    roi_raw_by_trader: dict[str, Decimal] = {}
    sharpe_raw_by_trader: dict[str, Decimal] = {}
    total_pnl_by_trader: dict[str, Decimal] = {}
    capital_by_trader: dict[str, Decimal] = {}

    for trader_address, positions in positions_by_trader.items():
        clv = compute_clv(positions, market_avgs)
        roi = compute_roi(positions)
        sharpe = compute_sharpe(positions)

        total_pnl = sum(
            (p.pnl for p in positions if p.pnl is not None),
            Decimal("0"),
        )

        # Capital deployed: LONG = size*price, SHORT = size*(1-price)
        capital = Decimal("0")
        for pos in positions:
            if pos.avg_entry_price is None:
                continue
            if pos.direction == "LONG":
                capital += pos.size * pos.avg_entry_price
            elif pos.direction == "SHORT":
                capital += pos.size * (Decimal("1") - pos.avg_entry_price)

        metrics_by_trader[trader_address] = LiftMetrics(
            clv=clv, roi=roi, sharpe=sharpe, position_count=len(positions)
        )
        clv_raw_by_trader[trader_address] = clv
        roi_raw_by_trader[trader_address] = roi
        sharpe_raw_by_trader[trader_address] = sharpe
        total_pnl_by_trader[trader_address] = total_pnl
        capital_by_trader[trader_address] = capital

    # Step 6: Z-score normalize
    clv_z = compute_z_scores(clv_raw_by_trader)
    roi_z = compute_z_scores(roi_raw_by_trader)
    sharpe_z = compute_z_scores(sharpe_raw_by_trader)

    # Step 7: Composite and quintiles
    composite = compute_composite(clv_z, roi_z, sharpe_z)
    quintiles = assign_quintiles(composite)

    # Step 8: Persist LiftScore (DELETE old rows for category, INSERT new)
    session.execute(
        delete(LiftScore).where(LiftScore.category == category)
    )

    for trader_address, composite_score in composite.items():
        metrics = metrics_by_trader[trader_address]
        lift_score = LiftScore(
            trader_address=trader_address,
            category=category,
            composite_score=composite_score,
            clv_raw=clv_raw_by_trader[trader_address],
            clv_zscore=clv_z[trader_address],
            roi_raw=roi_raw_by_trader[trader_address],
            roi_zscore=roi_z[trader_address],
            sharpe_raw=sharpe_raw_by_trader[trader_address],
            sharpe_zscore=sharpe_z[trader_address],
            quintile=quintiles[trader_address],
            position_count=metrics.position_count,
            total_pnl=total_pnl_by_trader[trader_address],
            capital_deployed=capital_by_trader[trader_address],
            window_start=window_start,
            window_end=now,
            computed_at=now,
        )
        session.add(lift_score)

    session.commit()

    # Step 9: Build and return sorted LiftLeaderboardEntry list
    entries: list[LiftLeaderboardEntry] = []
    for trader_address, composite_score in composite.items():
        metrics = metrics_by_trader[trader_address]
        entries.append(
            LiftLeaderboardEntry(
                trader_address=trader_address,
                composite_score=composite_score,
                clv_raw=clv_raw_by_trader[trader_address],
                clv_zscore=clv_z[trader_address],
                roi_raw=roi_raw_by_trader[trader_address],
                roi_zscore=roi_z[trader_address],
                sharpe_raw=sharpe_raw_by_trader[trader_address],
                sharpe_zscore=sharpe_z[trader_address],
                quintile=quintiles[trader_address],
                position_count=metrics.position_count,
                total_pnl=total_pnl_by_trader[trader_address],
                capital_deployed=capital_by_trader[trader_address],
            )
        )

    entries.sort(key=lambda x: x.composite_score, reverse=True)
    return entries


def compute_all_category_scores(
    session: Session,
    window_days: int = 30,
    now: datetime | None = None,
) -> dict[str, list[LiftLeaderboardEntry]]:
    """Compute lift-based scores for all configured categories.

    Iterates over all categories in MARKET_CONFIGS and calls
    compute_category_scores for each. Returns empty list for categories
    with no qualifying data.

    Args:
        session: SQLAlchemy session.
        window_days: Rolling window in days (default: 30).
        now: Optional current timestamp for testing.

    Returns:
        Dict of {category: list[LiftLeaderboardEntry]}.
    """
    from src.config.market_config import MARKET_CONFIGS

    results: dict[str, list[LiftLeaderboardEntry]] = {}
    for category in MARKET_CONFIGS:
        leaderboard = compute_category_scores(
            session, category, window_days=window_days, now=now
        )
        results[category] = leaderboard

    return results
