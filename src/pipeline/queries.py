"""Query layer for filtering stored trade data.

Provides functions for:
- Date range filtering
- Resolution status filtering
- Trader-specific queries
- Active market queries

All queries use SQLAlchemy 2.0 select() syntax and leverage composite indexes
for optimal performance on time-series data.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Market, Trade, TraderCategorySummary


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
