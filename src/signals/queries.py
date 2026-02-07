"""Query layer for signal snapshots and expert activity filtering.

Provides functions for:
- Latest signal retrieval per market
- Signal history tracking
- Expert position filtering
- Time-windowed market activity ranking

All queries use SQLAlchemy 2.0 select() syntax and leverage composite indexes
for optimal performance on time-series data.
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.db.models import SignalSnapshot, Position, ExpertiseScore


def get_latest_signals(
    session: Session,
    status: str | None = "active",
    min_confidence: Decimal | None = None,
    limit: int = 50,
) -> list[SignalSnapshot]:
    """Query latest SignalSnapshot per (market_id, direction).

    Returns the most recent signal snapshot for each market+direction pair,
    ordered by confidence_score DESC.

    Args:
        session: SQLAlchemy session
        status: Filter by status ("active", "inactive", or None for all)
        min_confidence: Optional minimum confidence_score filter (0-100)
        limit: Maximum number of entries to return (default: 50)

    Returns:
        List of SignalSnapshot ORM objects, ordered by confidence DESC

    Example:
        # Get top 20 active signals
        signals = get_latest_signals(session, status="active", limit=20)

        # Get all signals above 80 confidence
        high_conf = get_latest_signals(session, min_confidence=Decimal("80"), limit=100)
    """
    # Subquery to find max(computed_at) per market_id and direction
    subquery = (
        select(
            SignalSnapshot.market_id,
            SignalSnapshot.direction,
            func.max(SignalSnapshot.computed_at).label("max_computed_at"),
        )
        .group_by(SignalSnapshot.market_id, SignalSnapshot.direction)
        .subquery()
    )

    # Main query: join to get latest signals
    query = (
        select(SignalSnapshot)
        .join(
            subquery,
            (SignalSnapshot.market_id == subquery.c.market_id)
            & (SignalSnapshot.direction == subquery.c.direction)
            & (SignalSnapshot.computed_at == subquery.c.max_computed_at),
        )
    )

    # Apply status filter if provided
    if status is not None:
        query = query.where(SignalSnapshot.status == status)

    # Apply min_confidence filter if provided
    if min_confidence is not None:
        query = query.where(SignalSnapshot.confidence_score >= min_confidence)

    # Order by confidence_score DESC
    query = query.order_by(SignalSnapshot.confidence_score.desc())

    # Limit results
    query = query.limit(limit)

    result = session.execute(query)
    return list(result.scalars().all())


def get_signal_history(
    session: Session,
    market_id: str,
    direction: str | None = None,
    limit: int = 20,
) -> list[SignalSnapshot]:
    """Query all SignalSnapshot rows for a market.

    Returns signal history ordered by computed_at DESC for tracking
    strength changes over time (used in Phase 6 alerting).

    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        direction: Optional direction filter ("LONG" or "SHORT")
        limit: Maximum number of entries to return (default: 20)

    Returns:
        List of SignalSnapshot ORM objects, ordered by computed_at DESC

    Example:
        # Get all signal history for a market
        history = get_signal_history(session, "0xMarket123")

        # Get LONG signal history only
        long_history = get_signal_history(session, "0xMarket123", direction="LONG")
    """
    query = select(SignalSnapshot).where(SignalSnapshot.market_id == market_id)

    # Apply direction filter if provided
    if direction is not None:
        query = query.where(SignalSnapshot.direction == direction)

    # Order by computed_at DESC
    query = query.order_by(SignalSnapshot.computed_at.desc())

    # Limit results
    query = query.limit(limit)

    result = session.execute(query)
    return list(result.scalars().all())


def get_expert_positions_for_market(
    session: Session,
    market_id: str,
    min_score: Decimal = Decimal("70"),
) -> list[Position]:
    """Query expert positions for a specific market.

    Returns positions for traders with expertise score > min_score,
    excluding FLAT positions. This is the database-backed version of
    the pure function's input assembly.

    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        min_score: Minimum expertise score threshold (default: 70)

    Returns:
        List of Position ORM objects for experts in this market

    Example:
        # Get all expert positions in a market
        positions = get_expert_positions_for_market(session, "0xMarket123")

        # Get only top-tier experts (score >= 80)
        top_positions = get_expert_positions_for_market(
            session, "0xMarket123", min_score=Decimal("80")
        )
    """
    # Subquery to find max(computed_at) per trader (latest expertise score)
    subquery = (
        select(
            ExpertiseScore.trader_address,
            func.max(ExpertiseScore.computed_at).label("max_computed_at"),
        )
        .group_by(ExpertiseScore.trader_address)
        .subquery()
    )

    # Main query: join Position -> ExpertiseScore (latest) -> filter
    query = (
        select(Position)
        .join(
            subquery,
            Position.trader_address == subquery.c.trader_address,
        )
        .join(
            ExpertiseScore,
            (ExpertiseScore.trader_address == subquery.c.trader_address)
            & (ExpertiseScore.computed_at == subquery.c.max_computed_at),
        )
        .where(Position.market_id == market_id)
        .where(Position.direction.in_(["LONG", "SHORT"]))
        .where(ExpertiseScore.raw_score > min_score)
    )

    result = session.execute(query)
    return list(result.scalars().all())


def get_markets_by_expert_activity(
    session: Session,
    window_hours: int = 24,
    min_experts: int = 1,
) -> list[tuple[str, int, datetime]]:
    """Query markets with expert position activity within a time window.

    Returns markets that have expert (score >70) position activity within
    the specified time window, grouped by market and ranked by expert count.

    Args:
        session: SQLAlchemy session
        window_hours: Time window in hours (default: 24)
        min_experts: Minimum number of distinct experts required (default: 1)

    Returns:
        List of tuples: (market_id, expert_count, latest_activity_timestamp)
        Ordered by expert_count DESC, latest_activity DESC

    Example:
        # Get markets with expert activity in last 24 hours
        markets = get_markets_by_expert_activity(session, window_hours=24)

        # Get markets with 3+ experts active in last 6 hours
        hot_markets = get_markets_by_expert_activity(
            session, window_hours=6, min_experts=3
        )
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=window_hours)

    # Subquery to find max(computed_at) per trader (latest expertise score)
    subquery = (
        select(
            ExpertiseScore.trader_address,
            func.max(ExpertiseScore.computed_at).label("max_computed_at"),
        )
        .group_by(ExpertiseScore.trader_address)
        .subquery()
    )

    # Main query: join Position -> ExpertiseScore (latest) -> filter by time window
    query = (
        select(
            Position.market_id,
            func.count(func.distinct(Position.trader_address)).label("expert_count"),
            func.max(Position.last_trade_timestamp).label("latest_activity"),
        )
        .join(
            subquery,
            Position.trader_address == subquery.c.trader_address,
        )
        .join(
            ExpertiseScore,
            (ExpertiseScore.trader_address == subquery.c.trader_address)
            & (ExpertiseScore.computed_at == subquery.c.max_computed_at),
        )
        .where(Position.last_trade_timestamp >= window_start)
        .where(ExpertiseScore.raw_score > Decimal("70"))
        .group_by(Position.market_id)
        .having(func.count(func.distinct(Position.trader_address)) >= min_experts)
        .order_by(
            func.count(func.distinct(Position.trader_address)).desc(),
            func.max(Position.last_trade_timestamp).desc(),
        )
    )

    result = session.execute(query)
    return [(row.market_id, row.expert_count, row.latest_activity) for row in result]
