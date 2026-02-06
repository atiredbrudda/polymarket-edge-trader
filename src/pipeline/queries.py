"""Query layer for filtering stored trade data.

Provides functions for:
- Date range filtering
- Resolution status filtering
- Trader-specific queries
- Active market queries
- Time-windowed evaluation queries

All queries use SQLAlchemy 2.0 select() syntax and leverage composite indexes
for optimal performance on time-series data.
"""

from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.db.models import Market, Position, Trade, TraderCategorySummary


def get_trades_by_date_range(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    trader_address: str | None = None,
) -> list[Trade]:
    """Query trades within a date range with optional trader filter.

    Uses composite index ix_trade_trader_timestamp for efficient filtering.

    Args:
        session: SQLAlchemy session
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        trader_address: Optional trader address filter

    Returns:
        List of Trade ORM objects ordered by timestamp DESC

    Example:
        trades = get_trades_by_date_range(
            session,
            datetime(2025, 1, 1),
            datetime(2025, 1, 31),
            trader_address="0xTrader1"
        )
    """
    query = select(Trade).where(Trade.timestamp.between(start_date, end_date))

    if trader_address:
        query = query.where(Trade.trader_address == trader_address)

    query = query.order_by(Trade.timestamp.desc())

    result = session.execute(query)
    return list(result.scalars().all())


def get_trades_by_resolution_status(
    session: Session, resolved: bool, trader_address: str | None = None
) -> list[Trade]:
    """Query trades filtered by market resolution status.

    Joins with markets table to check if market has an outcome.

    Args:
        session: SQLAlchemy session
        resolved: If True, return trades on resolved markets (outcome IS NOT NULL)
                  If False, return trades on unresolved markets (outcome IS NULL)
        trader_address: Optional trader address filter

    Returns:
        List of Trade ORM objects

    Example:
        # Get all trades on resolved markets
        resolved_trades = get_trades_by_resolution_status(session, resolved=True)

        # Get trader's trades on unresolved markets
        active_trades = get_trades_by_resolution_status(
            session,
            resolved=False,
            trader_address="0xTrader1"
        )
    """
    query = (
        select(Trade)
        .join(Market, Trade.market_id == Market.condition_id)
    )

    if resolved:
        query = query.where(Market.outcome.is_not(None))
    else:
        query = query.where(Market.outcome.is_(None))

    if trader_address:
        query = query.where(Trade.trader_address == trader_address)

    result = session.execute(query)
    return list(result.scalars().all())


def get_trader_trades(
    session: Session, trader_address: str, category: str | None = None
) -> list[Trade]:
    """Query all trades for a specific trader with optional category filter.

    Uses composite index ix_trade_trader_timestamp for efficient retrieval.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address
        category: Optional category filter (joins with markets table)

    Returns:
        List of Trade ORM objects ordered by timestamp DESC

    Example:
        # Get all trades for trader
        all_trades = get_trader_trades(session, "0xTrader1")

        # Get trader's eSports trades
        esports_trades = get_trader_trades(session, "0xTrader1", category="eSports")
    """
    query = select(Trade).where(Trade.trader_address == trader_address)

    if category:
        query = query.join(Market, Trade.market_id == Market.condition_id).where(
            Market.category == category
        )

    query = query.order_by(Trade.timestamp.desc())

    result = session.execute(query)
    return list(result.scalars().all())


def get_trader_summary(session: Session, trader_address: str) -> list[TraderCategorySummary]:
    """Query all category summaries for a trader.

    Returns aggregated data for non-detail categories.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        List of TraderCategorySummary ORM objects

    Example:
        summaries = get_trader_summary(session, "0xTrader1")
        for summary in summaries:
            print(f"{summary.category}: {summary.total_volume} volume")
    """
    query = select(TraderCategorySummary).where(
        TraderCategorySummary.trader_address == trader_address
    )

    result = session.execute(query)
    return list(result.scalars().all())


def get_active_markets(session: Session, category: str | None = None) -> list[Market]:
    """Query active markets with optional category filter.

    Args:
        session: SQLAlchemy session
        category: Optional category filter

    Returns:
        List of Market ORM objects where active=True

    Example:
        # Get all active markets
        active = get_active_markets(session)

        # Get active eSports markets
        esports = get_active_markets(session, category="eSports")
    """
    query = select(Market).where(Market.active == True)

    if category:
        query = query.where(Market.category == category)

    result = session.execute(query)
    return list(result.scalars().all())


def get_positions_by_timeframe(
    session: Session,
    trader_address: str,
    window_key: str,
    now: datetime | None = None,
) -> list[Position]:
    """Query positions within a timeframe window.

    Uses get_timeframe_bounds from src.evaluation.timeframes to calculate bounds.
    Filters positions by last_trade_timestamp within the window.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address
        window_key: Window identifier ("7d", "30d", "90d", "all")
        now: Current time for window calculation (defaults to utcnow)

    Returns:
        List of Position ORM objects ordered by last_trade_timestamp DESC

    Example:
        # Get trader's positions from last 7 days
        positions = get_positions_by_timeframe(session, "0xTrader1", "7d")

        # Get all trader's positions
        all_positions = get_positions_by_timeframe(session, "0xTrader1", "all")
    """
    from src.evaluation.timeframes import get_timeframe_bounds

    start, end = get_timeframe_bounds(window_key, now=now)

    query = select(Position).where(Position.trader_address == trader_address)

    if start is not None:
        query = query.where(Position.last_trade_timestamp >= start)

    query = query.where(Position.last_trade_timestamp <= end)
    query = query.order_by(Position.last_trade_timestamp.desc())

    result = session.execute(query)
    return list(result.scalars().all())


def get_resolved_positions(
    session: Session,
    trader_address: str,
    grace_period_hours: int = 4,
) -> list[Position]:
    """Query resolved positions excluding grace period.

    Filters out positions on markets resolved within the last grace_period_hours
    to allow for UMA challenge period (2 hours) and processing time.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address
        grace_period_hours: Hours to exclude after resolution (default: 4)

    Returns:
        List of Position ORM objects ordered by last_trade_timestamp DESC

    Example:
        # Get trader's resolved positions (excluding last 4 hours)
        resolved = get_resolved_positions(session, "0xTrader1")

        # Use custom grace period
        resolved = get_resolved_positions(session, "0xTrader1", grace_period_hours=8)
    """
    now = datetime.utcnow()
    grace_cutoff = now - timedelta(hours=grace_period_hours)

    query = (
        select(Position)
        .join(Market, Position.market_id == Market.condition_id)
        .where(Position.trader_address == trader_address)
        .where(Position.resolved == True)
        .where(Market.updated_at < grace_cutoff)
        .order_by(Position.last_trade_timestamp.desc())
    )

    result = session.execute(query)
    return list(result.scalars().all())


def get_trader_unique_markets(session: Session, trader_address: str) -> int:
    """Count unique markets a trader has entered.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        Integer count of distinct market_id values

    Example:
        # Get count of markets trader participated in
        count = get_trader_unique_markets(session, "0xTrader1")
    """
    query = (
        select(func.count(func.distinct(Position.market_id)))
        .where(Position.trader_address == trader_address)
    )

    result = session.execute(query)
    return result.scalar() or 0


def get_trader_outcomes_chronological(session: Session, trader_address: str) -> list[str]:
    """Get trader's position outcomes in chronological order.

    Excludes void and flat outcomes for consistency analysis.
    Used for streak detection and pattern analysis.

    Args:
        session: SQLAlchemy session
        trader_address: Trader wallet address

    Returns:
        List of outcome strings ["win", "loss", "win", ...] ordered by last_trade_timestamp ASC

    Example:
        # Get trader's outcome history
        outcomes = get_trader_outcomes_chronological(session, "0xTrader1")
        # ["win", "loss", "win", "win", "loss"]
    """
    query = (
        select(Position.outcome)
        .where(Position.trader_address == trader_address)
        .where(Position.resolved == True)
        .where(Position.outcome.is_not(None))
        .where(Position.outcome.not_in(["void", "flat"]))
        .order_by(Position.last_trade_timestamp.asc())
    )

    result = session.execute(query)
    return [outcome for outcome in result.scalars().all()]
