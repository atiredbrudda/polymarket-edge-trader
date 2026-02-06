"""Tests for query layer filtering functions.

Tests all query functions with pre-populated in-memory database.
Verifies:
- Date range filtering
- Resolution status filtering
- Trader-specific queries
- Category filtering
- Active market queries
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import Base, Market, Trader, Trade, TraderCategorySummary
from src.pipeline.queries import (
    get_active_markets,
    get_trades_by_date_range,
    get_trades_by_resolution_status,
    get_trader_summary,
    get_trader_trades,
)


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


@pytest.fixture
def populated_db(in_memory_db):
    """Create database with test data.

    Creates:
    - 3 markets (2 active, 1 resolved)
    - 2 traders
    - 10 trades across different dates and markets
    - 2 trader category summaries
    """
    _, session_factory = in_memory_db
    session: Session = session_factory()

    # Create markets
    market1 = Market(
        condition_id="market1",
        question="CS:GO match",
        category="eSports",
        active=True,
        outcome=None,
    )
    market2 = Market(
        condition_id="market2",
        question="Election result",
        category="Politics",
        active=True,
        outcome=None,
    )
    market3 = Market(
        condition_id="market3",
        question="Past eSports event",
        category="eSports",
        active=False,
        outcome="YES",  # Resolved
    )

    # Create traders
    trader1 = Trader(
        address="0xTrader1",
        first_seen=datetime(2025, 1, 1),
        last_active=datetime(2025, 1, 10),
        backfill_complete=True,
    )
    trader2 = Trader(
        address="0xTrader2",
        first_seen=datetime(2025, 1, 5),
        last_active=datetime(2025, 1, 15),
        backfill_complete=True,
    )

    session.add_all([market1, market2, market3, trader1, trader2])
    session.commit()

    # Create trades with different dates and markets
    trades = [
        # Trader1 trades on market1 (active eSports)
        Trade(
            market_id="market1",
            trader_address="0xTrader1",
            side="BUY",
            size=Decimal("100.0"),
            price=Decimal("0.55"),
            timestamp=datetime(2025, 1, 5, 10, 0, 0),
            trade_id="trade1",
        ),
        Trade(
            market_id="market1",
            trader_address="0xTrader1",
            side="SELL",
            size=Decimal("50.0"),
            price=Decimal("0.60"),
            timestamp=datetime(2025, 1, 10, 14, 0, 0),
            trade_id="trade2",
        ),
        # Trader1 trades on market2 (active Politics)
        Trade(
            market_id="market2",
            trader_address="0xTrader1",
            side="BUY",
            size=Decimal("200.0"),
            price=Decimal("0.45"),
            timestamp=datetime(2025, 1, 8, 12, 0, 0),
            trade_id="trade3",
        ),
        # Trader1 trades on market3 (resolved eSports)
        Trade(
            market_id="market3",
            trader_address="0xTrader1",
            side="BUY",
            size=Decimal("75.0"),
            price=Decimal("0.50"),
            timestamp=datetime(2024, 12, 20, 9, 0, 0),
            trade_id="trade4",
        ),
        # Trader2 trades on market1
        Trade(
            market_id="market1",
            trader_address="0xTrader2",
            side="BUY",
            size=Decimal("150.0"),
            price=Decimal("0.52"),
            timestamp=datetime(2025, 1, 6, 11, 0, 0),
            trade_id="trade5",
        ),
        Trade(
            market_id="market1",
            trader_address="0xTrader2",
            side="SELL",
            size=Decimal("100.0"),
            price=Decimal("0.58"),
            timestamp=datetime(2025, 1, 12, 15, 0, 0),
            trade_id="trade6",
        ),
        # Trader2 trades on market2
        Trade(
            market_id="market2",
            trader_address="0xTrader2",
            side="SELL",
            size=Decimal("80.0"),
            price=Decimal("0.42"),
            timestamp=datetime(2025, 1, 9, 13, 0, 0),
            trade_id="trade7",
        ),
        # More trades for date range testing
        Trade(
            market_id="market1",
            trader_address="0xTrader1",
            side="BUY",
            size=Decimal("25.0"),
            price=Decimal("0.56"),
            timestamp=datetime(2025, 1, 15, 10, 0, 0),
            trade_id="trade8",
        ),
        Trade(
            market_id="market1",
            trader_address="0xTrader2",
            side="SELL",
            size=Decimal("30.0"),
            price=Decimal("0.54"),
            timestamp=datetime(2025, 1, 20, 11, 0, 0),
            trade_id="trade9",
        ),
        Trade(
            market_id="market2",
            trader_address="0xTrader1",
            side="SELL",
            size=Decimal("40.0"),
            price=Decimal("0.48"),
            timestamp=datetime(2024, 12, 15, 14, 0, 0),
            trade_id="trade10",
        ),
    ]

    session.add_all(trades)
    session.commit()

    # Create category summaries
    summary1 = TraderCategorySummary(
        trader_address="0xTrader1",
        category="Crypto",
        total_volume=Decimal("500.0"),
        trade_count=5,
        first_trade=datetime(2024, 11, 1),
        last_trade=datetime(2024, 12, 1),
    )
    summary2 = TraderCategorySummary(
        trader_address="0xTrader2",
        category="Sports",
        total_volume=Decimal("300.0"),
        trade_count=3,
        first_trade=datetime(2024, 10, 15),
        last_trade=datetime(2024, 11, 20),
    )

    session.add_all([summary1, summary2])
    session.commit()
    session.close()

    return session_factory


def test_get_trades_by_date_range_filters_correctly(populated_db):
    """Test that date range query returns only trades within range."""
    session = populated_db()

    # Query trades in January 2025 (1-15)
    trades = get_trades_by_date_range(
        session,
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 1, 15, 23, 59, 59),
    )

    # Should include trades 1,2,3,5,6,7,8 (not 4,9,10)
    assert len(trades) == 7

    # Verify all trades are within range
    for trade in trades:
        assert datetime(2025, 1, 1) <= trade.timestamp <= datetime(2025, 1, 15, 23, 59, 59)

    # Verify ordering (DESC)
    assert trades[0].timestamp >= trades[-1].timestamp

    session.close()


def test_get_trades_by_date_range_with_trader(populated_db):
    """Test date range query with trader filter."""
    session = populated_db()

    # Query trader1's trades in January 2025
    trades = get_trades_by_date_range(
        session,
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 1, 31),
        trader_address="0xTrader1",
    )

    # Should include trades 1,2,3,8 (not trader2's trades)
    assert len(trades) == 4

    # Verify all trades belong to trader1
    for trade in trades:
        assert trade.trader_address == "0xTrader1"

    session.close()


def test_get_trades_resolved_only(populated_db):
    """Test resolution status query for resolved markets only."""
    session = populated_db()

    # Query trades on resolved markets
    trades = get_trades_by_resolution_status(session, resolved=True)

    # Should only include trade4 (on market3, which is resolved)
    assert len(trades) == 1
    assert trades[0].trade_id == "trade4"
    assert trades[0].market_id == "market3"

    session.close()


def test_get_trades_unresolved_only(populated_db):
    """Test resolution status query for unresolved markets only."""
    session = populated_db()

    # Query trades on unresolved markets
    trades = get_trades_by_resolution_status(session, resolved=False)

    # Should include all trades except trade4 (9 trades)
    assert len(trades) == 9

    # Verify none are on resolved market
    for trade in trades:
        assert trade.market_id != "market3"

    session.close()


def test_get_trades_by_resolution_status_with_trader(populated_db):
    """Test resolution status query with trader filter."""
    session = populated_db()

    # Query trader1's trades on unresolved markets
    trades = get_trades_by_resolution_status(
        session, resolved=False, trader_address="0xTrader1"
    )

    # Should include trades 1,2,3,8,10 (not trade4 which is resolved)
    assert len(trades) == 5

    # Verify all belong to trader1 and are unresolved
    for trade in trades:
        assert trade.trader_address == "0xTrader1"
        assert trade.market_id in ["market1", "market2"]

    session.close()


def test_get_trader_trades_returns_all(populated_db):
    """Test trader query returns all trades for trader."""
    session = populated_db()

    # Query all trader1 trades
    trades = get_trader_trades(session, "0xTrader1")

    # Should include trades 1,2,3,4,8,10 (6 trades)
    assert len(trades) == 6

    # Verify all belong to trader1
    for trade in trades:
        assert trade.trader_address == "0xTrader1"

    # Verify ordering (DESC)
    assert trades[0].timestamp >= trades[-1].timestamp

    session.close()


def test_get_trader_trades_with_category_filter(populated_db):
    """Test trader query with category filter."""
    session = populated_db()

    # Query trader1's eSports trades
    trades = get_trader_trades(session, "0xTrader1", category="eSports")

    # Should include trades 1,2,4,8 (all on market1 or market3)
    assert len(trades) == 4

    # Verify all are eSports
    for trade in trades:
        assert trade.market_id in ["market1", "market3"]

    session.close()


def test_get_trader_summary_returns_categories(populated_db):
    """Test trader summary query returns all category summaries."""
    session = populated_db()

    # Query trader1 summaries
    summaries = get_trader_summary(session, "0xTrader1")

    # Should have 1 summary (Crypto)
    assert len(summaries) == 1
    assert summaries[0].category == "Crypto"
    assert summaries[0].total_volume == Decimal("500.0")
    assert summaries[0].trade_count == 5

    session.close()


def test_get_active_markets_filters(populated_db):
    """Test active markets query filters correctly."""
    session = populated_db()

    # Query all active markets
    markets = get_active_markets(session)

    # Should return market1 and market2 (not market3 which is inactive)
    assert len(markets) == 2

    # Verify all are active
    for market in markets:
        assert market.active is True

    session.close()


def test_get_active_markets_by_category(populated_db):
    """Test active markets query with category filter."""
    session = populated_db()

    # Query active eSports markets
    markets = get_active_markets(session, category="eSports")

    # Should return only market1 (market3 is eSports but inactive)
    assert len(markets) == 1
    assert markets[0].condition_id == "market1"
    assert markets[0].category == "eSports"
    assert markets[0].active is True

    session.close()


def test_get_trades_by_date_range_empty_result(populated_db):
    """Test date range query with no matching trades."""
    session = populated_db()

    # Query future date range
    trades = get_trades_by_date_range(
        session, start_date=datetime(2026, 1, 1), end_date=datetime(2026, 12, 31)
    )

    # Should return empty list
    assert len(trades) == 0

    session.close()


def test_get_trader_trades_nonexistent_trader(populated_db):
    """Test trader query with nonexistent trader."""
    session = populated_db()

    # Query nonexistent trader
    trades = get_trader_trades(session, "0xNonexistent")

    # Should return empty list
    assert len(trades) == 0

    session.close()
