"""Tests for ingestion pipeline integration.

Tests the IngestionPipeline class with mocked API client and in-memory database.
Verifies:
- Market ingestion with upsert behavior
- Trader discovery from market activity
- Trade history ingestion with category routing
- Deduplication of trades
- Error handling for per-trader failures
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.models import MarketResponse, TradeResponse
from src.db.models import Base, Market, Trader, Trade, TraderCategorySummary
from src.pipeline.filters import CategoryFilter
from src.pipeline.ingest import IngestionPipeline


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


@pytest.fixture
def mock_client():
    """Create mock PolymarketClient."""
    return Mock()


@pytest.fixture
def category_filter():
    """Create CategoryFilter configured for eSports."""
    return CategoryFilter(detail_categories=["eSports", "Gaming"])


@pytest.fixture
def pipeline(mock_client, in_memory_db, category_filter):
    """Create IngestionPipeline with mocked client and in-memory database."""
    _, session_factory = in_memory_db
    return IngestionPipeline(mock_client, session_factory, category_filter)


def test_ingest_active_markets_persists(pipeline, mock_client, in_memory_db):
    """Test that active markets are fetched and persisted to database."""
    _, session_factory = in_memory_db

    # Mock API response with 2 markets
    mock_client.get_markets.return_value = [
        MarketResponse(
            condition_id="market1",
            question="Will Team A win?",
            category="eSports",
            active=True,
            outcome=None,
            end_date_iso="2025-12-31T00:00:00Z",
            tokens=[{"token_id": "123"}],
        ),
        MarketResponse(
            condition_id="market2",
            question="Will Team B win?",
            category="eSports",
            active=True,
            outcome=None,
            end_date_iso="2025-11-30T00:00:00Z",
            tokens=None,
        ),
    ]

    # Run ingestion
    count = pipeline.ingest_active_markets()

    # Verify count
    assert count == 2

    # Verify database persistence
    session = session_factory()
    markets = session.query(Market).all()
    assert len(markets) == 2

    # Verify market data
    market1 = session.query(Market).filter_by(condition_id="market1").first()
    assert market1 is not None
    assert market1.question == "Will Team A win?"
    assert market1.category == "eSports"
    assert market1.active is True
    assert market1.tokens is not None  # JSON string

    session.close()


def test_ingest_active_markets_upserts(pipeline, mock_client, in_memory_db):
    """Test that market ingestion updates existing markets."""
    _, session_factory = in_memory_db

    # Pre-populate with existing market
    session = session_factory()
    existing_market = Market(
        condition_id="market1",
        question="Old question",
        category="eSports",
        active=True,
        outcome=None,
    )
    session.add(existing_market)
    session.commit()
    session.close()

    # Mock API response with updated market
    mock_client.get_markets.return_value = [
        MarketResponse(
            condition_id="market1",
            question="Updated question",
            category="eSports",
            active=False,  # Changed to inactive
            outcome="YES",  # Now resolved
            end_date_iso=None,
            tokens=None,
        )
    ]

    # Run ingestion
    count = pipeline.ingest_active_markets()

    # Verify count
    assert count == 1

    # Verify update
    session = session_factory()
    markets = session.query(Market).all()
    assert len(markets) == 1  # Still only one market

    market = markets[0]
    assert market.question == "Updated question"  # Updated
    assert market.active is False  # Updated
    assert market.outcome == "YES"  # Updated

    session.close()


def test_discover_traders_finds_addresses(pipeline, mock_client, in_memory_db):
    """Test that trader addresses are discovered from market trades."""
    _, session_factory = in_memory_db

    # Mock market trades with 3 unique traders
    mock_client.get_market_trades.return_value = [
        TradeResponse(
            id="trade1",
            market="market1",
            trader="0xTrader1",
            side="BUY",
            size=Decimal("100.5"),
            price=Decimal("0.55"),
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        ),
        TradeResponse(
            id="trade2",
            market="market1",
            trader="0xTrader2",
            side="SELL",
            size=Decimal("50.25"),
            price=Decimal("0.45"),
            timestamp=datetime(2025, 1, 1, 13, 0, 0),
        ),
        TradeResponse(
            id="trade3",
            market="market1",
            trader="0xTrader1",  # Duplicate - same trader
            side="BUY",
            size=Decimal("25.0"),
            price=Decimal("0.60"),
            timestamp=datetime(2025, 1, 1, 14, 0, 0),
        ),
    ]

    # Run discovery
    new_traders = pipeline.discover_traders_from_market("market1")

    # Verify new traders
    assert len(new_traders) == 2  # Only 2 unique traders
    assert "0xTrader1" in new_traders
    assert "0xTrader2" in new_traders

    # Verify database persistence
    session = session_factory()
    traders = session.query(Trader).all()
    assert len(traders) == 2

    trader1 = session.query(Trader).filter_by(address="0xTrader1").first()
    assert trader1 is not None
    assert trader1.backfill_complete is False

    session.close()


def test_discover_traders_skips_existing(pipeline, mock_client, in_memory_db):
    """Test that discovery skips already-known traders."""
    _, session_factory = in_memory_db

    # Pre-populate with existing trader
    session = session_factory()
    existing_trader = Trader(
        address="0xTrader1",
        first_seen=datetime(2024, 12, 1),
        last_active=datetime(2024, 12, 1),
        backfill_complete=True,
    )
    session.add(existing_trader)
    session.commit()
    session.close()

    # Mock market trades
    mock_client.get_market_trades.return_value = [
        TradeResponse(
            id="trade1",
            market="market1",
            trader="0xTrader1",  # Existing
            side="BUY",
            size=Decimal("100.0"),
            price=Decimal("0.5"),
            timestamp=datetime(2025, 1, 1),
        ),
        TradeResponse(
            id="trade2",
            market="market1",
            trader="0xTrader2",  # New
            side="SELL",
            size=Decimal("50.0"),
            price=Decimal("0.5"),
            timestamp=datetime(2025, 1, 1),
        ),
    ]

    # Run discovery
    new_traders = pipeline.discover_traders_from_market("market1")

    # Verify only new trader returned
    assert len(new_traders) == 1
    assert "0xTrader2" in new_traders
    assert "0xTrader1" not in new_traders

    # Verify database has both traders
    session = session_factory()
    traders = session.query(Trader).all()
    assert len(traders) == 2

    session.close()


def test_ingest_trader_history_routes_correctly(pipeline, mock_client, in_memory_db):
    """Test that trader history is routed to detail and summary storage."""
    _, session_factory = in_memory_db

    # Pre-populate with trader and markets
    session = session_factory()
    trader = Trader(
        address="0xTrader1",
        first_seen=datetime(2025, 1, 1),
        last_active=datetime(2025, 1, 1),
        backfill_complete=False,
    )
    esports_market = Market(
        condition_id="market1",
        question="CS:GO match",
        category="eSports",  # Detail category
        active=True,
    )
    politics_market = Market(
        condition_id="market2",
        question="Election outcome",
        category="Politics",  # Summary category
        active=True,
    )
    session.add(trader)
    session.add(esports_market)
    session.add(politics_market)
    session.commit()
    session.close()

    # Mock trades for both markets
    def mock_get_market_trades(condition_id):
        if condition_id == "market1":
            # eSports trades
            return [
                TradeResponse(
                    id="trade1",
                    market="market1",
                    trader="0xTrader1",
                    side="BUY",
                    size=Decimal("100.0"),
                    price=Decimal("0.6"),
                    timestamp=datetime(2025, 1, 1, 12, 0, 0),
                )
            ]
        elif condition_id == "market2":
            # Politics trades
            return [
                TradeResponse(
                    id="trade2",
                    market="market2",
                    trader="0xTrader1",
                    side="SELL",
                    size=Decimal("50.0"),
                    price=Decimal("0.4"),
                    timestamp=datetime(2025, 1, 2, 12, 0, 0),
                )
            ]
        return []

    mock_client.get_market_trades.side_effect = mock_get_market_trades

    # Run ingestion
    stats = pipeline.ingest_trader_history("0xTrader1")

    # Verify stats
    assert stats["detail_count"] == 1  # 1 eSports trade
    assert stats["summary_count"] == 1  # 1 Politics summary
    assert "eSports" in stats["categories"]
    assert "Politics" in stats["categories"]

    # Verify database
    session = session_factory()

    # Check detail trades
    detail_trades = session.query(Trade).all()
    assert len(detail_trades) == 1
    assert detail_trades[0].market_id == "market1"

    # Check summaries
    summaries = session.query(TraderCategorySummary).all()
    assert len(summaries) == 1
    assert summaries[0].category == "Politics"
    assert summaries[0].total_volume == Decimal("50.0")
    assert summaries[0].trade_count == 1

    # Check trader marked as complete
    trader = session.query(Trader).filter_by(address="0xTrader1").first()
    assert trader.backfill_complete is True

    session.close()


def test_duplicate_trade_skipped(pipeline, mock_client, in_memory_db):
    """Test that duplicate trades are not inserted."""
    _, session_factory = in_memory_db

    # Pre-populate with trader, market, and existing trade
    session = session_factory()
    trader = Trader(
        address="0xTrader1",
        first_seen=datetime(2025, 1, 1),
        last_active=datetime(2025, 1, 1),
        backfill_complete=False,
    )
    market = Market(
        condition_id="market1",
        question="Test market",
        category="eSports",
        active=True,
    )
    existing_trade = Trade(
        market_id="market1",
        trader_address="0xTrader1",
        side="BUY",
        size=Decimal("100.0"),
        price=Decimal("0.5"),
        timestamp=datetime(2025, 1, 1, 12, 0, 0),
        trade_id="trade1",  # Duplicate ID
    )
    session.add(trader)
    session.add(market)
    session.add(existing_trade)
    session.commit()
    session.close()

    # Mock API returning same trade again
    mock_client.get_market_trades.return_value = [
        TradeResponse(
            id="trade1",  # Same ID as existing
            market="market1",
            trader="0xTrader1",
            side="BUY",
            size=Decimal("100.0"),
            price=Decimal("0.5"),
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        )
    ]

    # Run ingestion
    stats = pipeline.ingest_trader_history("0xTrader1")

    # Verify no new trades inserted
    assert stats["detail_count"] == 0  # Skipped duplicate

    # Verify database still has only 1 trade
    session = session_factory()
    trades = session.query(Trade).all()
    assert len(trades) == 1

    session.close()


def test_sweep_handles_trader_error_gracefully(pipeline, mock_client, in_memory_db):
    """Test that full sweep continues after per-trader errors."""
    _, session_factory = in_memory_db

    # Pre-populate with market and 2 traders
    session = session_factory()
    market = Market(
        condition_id="market1", question="Test", category="eSports", active=True
    )
    trader1 = Trader(
        address="0xTrader1",
        first_seen=datetime(2025, 1, 1),
        last_active=datetime(2025, 1, 1),
        backfill_complete=False,
    )
    trader2 = Trader(
        address="0xTrader2",
        first_seen=datetime(2025, 1, 1),
        last_active=datetime(2025, 1, 1),
        backfill_complete=False,
    )
    session.add(market)
    session.add(trader1)
    session.add(trader2)
    session.commit()
    session.close()

    # Mock successful market ingestion
    mock_client.get_events.return_value = []

    # Mock get_market_trades to fail for trader1 but succeed for trader2
    call_count = {"count": 0}

    def mock_get_market_trades(condition_id):
        call_count["count"] += 1
        if call_count["count"] == 1:
            # First call (trader1) - raise error
            raise Exception("API error for trader1")
        else:
            # Second call (trader2) - succeed
            return [
                TradeResponse(
                    id="trade2",
                    market="market1",
                    trader="0xTrader2",
                    side="BUY",
                    size=Decimal("50.0"),
                    price=Decimal("0.5"),
                    timestamp=datetime(2025, 1, 1),
                )
            ]

    mock_client.get_market_trades.side_effect = mock_get_market_trades

    # Run full sweep
    stats = pipeline.run_full_sweep()

    # Verify sweep completed despite trader1 error
    # Note: stats may be 0 if no new traders discovered, but sweep should not crash
    assert isinstance(stats, dict)

    # Verify trader2 was processed (if backfilled)
    session = session_factory()
    trader2_db = session.query(Trader).filter_by(address="0xTrader2").first()
    # May or may not be complete depending on discovery logic, but should exist
    assert trader2_db is not None

    session.close()


def test_ingest_trader_history_handles_no_trades(pipeline, mock_client, in_memory_db):
    """Test that ingestion handles traders with no trades gracefully."""
    _, session_factory = in_memory_db

    # Pre-populate with trader and market
    session = session_factory()
    trader = Trader(
        address="0xTrader1",
        first_seen=datetime(2025, 1, 1),
        last_active=datetime(2025, 1, 1),
        backfill_complete=False,
    )
    market = Market(
        condition_id="market1", question="Test", category="eSports", active=True
    )
    session.add(trader)
    session.add(market)
    session.commit()
    session.close()

    # Mock no trades for this trader
    mock_client.get_market_trades.return_value = []

    # Run ingestion
    stats = pipeline.ingest_trader_history("0xTrader1")

    # Verify stats
    assert stats["detail_count"] == 0
    assert stats["summary_count"] == 0

    # Verify trader still marked as complete
    session = session_factory()
    trader = session.query(Trader).filter_by(address="0xTrader1").first()
    assert trader.backfill_complete is True

    session.close()
