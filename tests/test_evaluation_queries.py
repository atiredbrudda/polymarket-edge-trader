"""Tests for evaluation-specific query functions.

Tests for:
- get_positions_by_timeframe - time-windowed position filtering
- get_resolved_positions - resolution with grace period
- get_trader_unique_markets - unique market count
- get_trader_outcomes_chronological - chronological outcome list
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import Base, Market, Position
from src.pipeline.queries import (
    get_positions_by_timeframe,
    get_resolved_positions,
    get_trader_unique_markets,
    get_trader_outcomes_chronological,
)


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


@pytest.fixture
def evaluation_db(in_memory_db):
    """Create database with evaluation test data.

    Creates:
    - 5 markets (3 resolved with different update times, 2 unresolved)
    - Multiple positions across different timestamps for timeframe testing
    - Position outcomes for streak analysis
    """
    _, session_factory = in_memory_db
    session: Session = session_factory()

    now = datetime.utcnow()

    # Create markets with different resolution times
    market1 = Market(
        condition_id="market1",
        question="Old resolved market",
        category="eSports",
        active=False,
        outcome="YES",
        updated_at=now - timedelta(days=10),  # Resolved 10 days ago
    )
    market2 = Market(
        condition_id="market2",
        question="Recent resolved market",
        category="eSports",
        active=False,
        outcome="YES",
        updated_at=now - timedelta(hours=2),  # Resolved 2 hours ago (within grace period)
    )
    market3 = Market(
        condition_id="market3",
        question="Just resolved market",
        category="eSports",
        active=False,
        outcome="NO",
        updated_at=now - timedelta(hours=5),  # Resolved 5 hours ago (outside grace period)
    )
    market4 = Market(
        condition_id="market4",
        question="Active market 1",
        category="eSports",
        active=True,
        outcome=None,
        updated_at=now,
    )
    market5 = Market(
        condition_id="market5",
        question="Active market 2",
        category="eSports",
        active=True,
        outcome=None,
        updated_at=now,
    )

    session.add_all([market1, market2, market3, market4, market5])
    session.commit()

    # Create additional markets for unique positions
    market6 = Market(
        condition_id="market6",
        question="Old resolved market 2",
        category="eSports",
        active=False,
        outcome="NO",
        updated_at=now - timedelta(days=25),
    )
    market7 = Market(
        condition_id="market7",
        question="Old resolved market 3",
        category="eSports",
        active=False,
        outcome="YES",
        updated_at=now - timedelta(days=105),
    )
    market8 = Market(
        condition_id="market8",
        question="Old resolved market 4",
        category="eSports",
        active=False,
        outcome="YES",
        updated_at=now - timedelta(days=15),
    )
    market9 = Market(
        condition_id="market9",
        question="Old resolved market 5",
        category="eSports",
        active=False,
        outcome="YES",
        updated_at=now - timedelta(days=12),
    )

    session.add_all([market6, market7, market8, market9])
    session.commit()

    # Create positions for trader1 with various timestamps
    # Each position must be on a different market (unique constraint on trader_address, market_id)
    positions = [
        # Position from 5 days ago (resolved, win) - market1
        Position(
            market_id="market1",
            trader_address="0xTrader1",
            size=Decimal("100.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.55"),
            entry_timestamp=now - timedelta(days=12),
            first_trade_timestamp=now - timedelta(days=12),
            last_trade_timestamp=now - timedelta(days=5),
            trade_count=3,
            resolved=True,
            outcome="win",
            pnl=Decimal("45.0"),
        ),
        # Position from 20 days ago (resolved, loss) - market6
        Position(
            market_id="market6",
            trader_address="0xTrader1",
            size=Decimal("50.0"),
            direction="SHORT",
            avg_entry_price=Decimal("0.60"),
            entry_timestamp=now - timedelta(days=25),
            first_trade_timestamp=now - timedelta(days=25),
            last_trade_timestamp=now - timedelta(days=20),
            trade_count=2,
            resolved=True,
            outcome="loss",
            pnl=Decimal("-20.0"),
        ),
        # Position from 35 days ago (resolved, win)
        Position(
            market_id="market3",
            trader_address="0xTrader1",
            size=Decimal("75.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.50"),
            entry_timestamp=now - timedelta(days=40),
            first_trade_timestamp=now - timedelta(days=40),
            last_trade_timestamp=now - timedelta(days=35),
            trade_count=4,
            resolved=True,
            outcome="win",
            pnl=Decimal("37.5"),
        ),
        # Position from 100 days ago (resolved, loss) - market7
        Position(
            market_id="market7",
            trader_address="0xTrader1",
            size=Decimal("200.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.45"),
            entry_timestamp=now - timedelta(days=105),
            first_trade_timestamp=now - timedelta(days=105),
            last_trade_timestamp=now - timedelta(days=100),
            trade_count=5,
            resolved=True,
            outcome="loss",
            pnl=Decimal("-90.0"),
        ),
        # Position from 2 days ago (resolved recently - within grace period)
        Position(
            market_id="market2",
            trader_address="0xTrader1",
            size=Decimal("150.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.52"),
            entry_timestamp=now - timedelta(days=3),
            first_trade_timestamp=now - timedelta(days=3),
            last_trade_timestamp=now - timedelta(days=2),
            trade_count=2,
            resolved=True,
            outcome="win",
            pnl=Decimal("72.0"),
        ),
        # Active position from yesterday (unresolved)
        Position(
            market_id="market4",
            trader_address="0xTrader1",
            size=Decimal("80.0"),
            direction="SHORT",
            avg_entry_price=Decimal("0.48"),
            entry_timestamp=now - timedelta(days=2),
            first_trade_timestamp=now - timedelta(days=2),
            last_trade_timestamp=now - timedelta(days=1),
            trade_count=3,
            resolved=False,
            outcome=None,
            pnl=None,
        ),
        # Position with void outcome (should be excluded from outcomes) - market8
        Position(
            market_id="market8",
            trader_address="0xTrader1",
            size=Decimal("30.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.55"),
            entry_timestamp=now - timedelta(days=15),
            first_trade_timestamp=now - timedelta(days=15),
            last_trade_timestamp=now - timedelta(days=10),
            trade_count=1,
            resolved=True,
            outcome="void",
            pnl=Decimal("0.0"),
        ),
        # Position with flat outcome (should be excluded from outcomes) - market9
        Position(
            market_id="market9",
            trader_address="0xTrader1",
            size=Decimal("0.0"),
            direction="FLAT",
            avg_entry_price=None,
            entry_timestamp=now - timedelta(days=8),
            first_trade_timestamp=now - timedelta(days=8),
            last_trade_timestamp=now - timedelta(days=8),
            trade_count=2,
            resolved=True,
            outcome="flat",
            pnl=Decimal("0.0"),
        ),
        # Positions for trader2 on different markets (for unique market count)
        Position(
            market_id="market4",
            trader_address="0xTrader2",
            size=Decimal("100.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.60"),
            entry_timestamp=now - timedelta(days=5),
            first_trade_timestamp=now - timedelta(days=5),
            last_trade_timestamp=now - timedelta(days=5),
            trade_count=2,
            resolved=False,
            outcome=None,
            pnl=None,
        ),
        Position(
            market_id="market5",
            trader_address="0xTrader2",
            size=Decimal("120.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.55"),
            entry_timestamp=now - timedelta(days=3),
            first_trade_timestamp=now - timedelta(days=3),
            last_trade_timestamp=now - timedelta(days=3),
            trade_count=3,
            resolved=False,
            outcome=None,
            pnl=None,
        ),
    ]

    session.add_all(positions)
    session.commit()
    session.close()

    return session_factory


class TestGetPositionsByTimeframe:
    """Test get_positions_by_timeframe function."""

    def test_7d_window_filtering(self, evaluation_db):
        """Test 7-day window returns only positions from last week."""
        session = evaluation_db()
        now = datetime.utcnow()

        positions = get_positions_by_timeframe(session, "0xTrader1", "7d", now=now)

        # Should include: position from 5 days ago, 2 days ago, 1 day ago
        assert len(positions) == 3

        # Verify all within 7 days
        cutoff = now - timedelta(days=7)
        for pos in positions:
            assert pos.last_trade_timestamp >= cutoff

        session.close()

    def test_30d_window_filtering(self, evaluation_db):
        """Test 30-day window returns positions from last month."""
        session = evaluation_db()
        now = datetime.utcnow()

        positions = get_positions_by_timeframe(session, "0xTrader1", "30d", now=now)

        # Should include: 5, 20, 2, 1, 10, 8 days ago (6 positions within 30 days)
        assert len(positions) == 6

        # Verify all within 30 days
        cutoff = now - timedelta(days=30)
        for pos in positions:
            assert pos.last_trade_timestamp >= cutoff

        session.close()

    def test_90d_window_filtering(self, evaluation_db):
        """Test 90-day window returns positions from last quarter."""
        session = evaluation_db()
        now = datetime.utcnow()

        positions = get_positions_by_timeframe(session, "0xTrader1", "90d", now=now)

        # Should include: all except 100 days ago (7 positions within 90 days)
        assert len(positions) == 7

        # Verify all within 90 days
        cutoff = now - timedelta(days=90)
        for pos in positions:
            assert pos.last_trade_timestamp >= cutoff

        session.close()

    def test_all_window_returns_everything(self, evaluation_db):
        """Test 'all' window returns all positions."""
        session = evaluation_db()
        now = datetime.utcnow()

        positions = get_positions_by_timeframe(session, "0xTrader1", "all", now=now)

        # Should include all 8 positions for trader1
        assert len(positions) == 8

        session.close()

    def test_ordering_by_timestamp_desc(self, evaluation_db):
        """Test positions are ordered by last_trade_timestamp DESC."""
        session = evaluation_db()
        now = datetime.utcnow()

        positions = get_positions_by_timeframe(session, "0xTrader1", "all", now=now)

        # Verify descending order
        for i in range(len(positions) - 1):
            assert positions[i].last_trade_timestamp >= positions[i + 1].last_trade_timestamp

        session.close()

    def test_trader_isolation(self, evaluation_db):
        """Test query only returns positions for specified trader."""
        session = evaluation_db()
        now = datetime.utcnow()

        trader1_positions = get_positions_by_timeframe(session, "0xTrader1", "all", now=now)
        trader2_positions = get_positions_by_timeframe(session, "0xTrader2", "all", now=now)

        assert len(trader1_positions) == 8
        assert len(trader2_positions) == 2

        for pos in trader1_positions:
            assert pos.trader_address == "0xTrader1"

        for pos in trader2_positions:
            assert pos.trader_address == "0xTrader2"

        session.close()


class TestGetResolvedPositions:
    """Test get_resolved_positions function."""

    def test_grace_period_exclusion(self, evaluation_db):
        """Test positions on recently-resolved markets are excluded."""
        session = evaluation_db()

        # Use 4-hour grace period (default)
        positions = get_resolved_positions(session, "0xTrader1", grace_period_hours=4)

        # Should exclude position on market2 (resolved 2 hours ago)
        # Should include positions on market1, market3, market6, market7, market8, market9
        market_ids = [pos.market_id for pos in positions]
        assert "market2" not in market_ids
        assert "market1" in market_ids
        assert "market3" in market_ids
        assert len(positions) == 6  # All except market2 and unresolved market4

        session.close()

    def test_custom_grace_period(self, evaluation_db):
        """Test custom grace period value."""
        session = evaluation_db()

        # Use 6-hour grace period (stricter)
        positions = get_resolved_positions(session, "0xTrader1", grace_period_hours=6)

        # Should exclude market2 (2h) and market3 (5h)
        # Should include market1, market6, market7, market8, market9
        market_ids = [pos.market_id for pos in positions]
        assert "market2" not in market_ids
        assert "market3" not in market_ids
        assert "market1" in market_ids
        assert len(positions) == 5  # All except market2, market3, and unresolved market4

        session.close()

    def test_only_resolved_positions(self, evaluation_db):
        """Test query only returns resolved positions."""
        session = evaluation_db()

        positions = get_resolved_positions(session, "0xTrader1")

        # Should not include unresolved position on market4
        for pos in positions:
            assert pos.resolved is True

        session.close()

    def test_ordering_by_timestamp_desc(self, evaluation_db):
        """Test resolved positions ordered by last_trade_timestamp DESC."""
        session = evaluation_db()

        positions = get_resolved_positions(session, "0xTrader1")

        # Verify descending order
        for i in range(len(positions) - 1):
            assert positions[i].last_trade_timestamp >= positions[i + 1].last_trade_timestamp

        session.close()


class TestGetTraderUniqueMarkets:
    """Test get_trader_unique_markets function."""

    def test_count_unique_markets(self, evaluation_db):
        """Test counting distinct markets for a trader."""
        session = evaluation_db()

        count = get_trader_unique_markets(session, "0xTrader1")

        # Trader1 has positions on market1, market2, market3, market4, market6, market7, market8, market9 (8 unique)
        assert count == 8

        session.close()

    def test_duplicate_markets_counted_once(self, evaluation_db):
        """Test each trader-market pair has exactly one position (unique constraint)."""
        session = evaluation_db()

        # Trader1 has one position per market (unique constraint enforced)
        count = get_trader_unique_markets(session, "0xTrader1")

        # 8 unique markets
        assert count == 8

        session.close()

    def test_different_trader_separate_count(self, evaluation_db):
        """Test counts are trader-specific."""
        session = evaluation_db()

        trader1_count = get_trader_unique_markets(session, "0xTrader1")
        trader2_count = get_trader_unique_markets(session, "0xTrader2")

        assert trader1_count == 8  # markets 1,2,3,4,6,7,8,9
        assert trader2_count == 2  # market4 and market5

        session.close()

    def test_nonexistent_trader_returns_zero(self, evaluation_db):
        """Test nonexistent trader returns 0."""
        session = evaluation_db()

        count = get_trader_unique_markets(session, "0xNonexistent")

        assert count == 0

        session.close()


class TestGetTraderOutcomesChronological:
    """Test get_trader_outcomes_chronological function."""

    def test_chronological_ordering(self, evaluation_db):
        """Test outcomes returned in chronological order."""
        session = evaluation_db()

        outcomes = get_trader_outcomes_chronological(session, "0xTrader1")

        # Should be ordered by last_trade_timestamp ASC:
        # 1. 100 days ago: loss
        # 2. 35 days ago: win
        # 3. 20 days ago: loss
        # 4. 5 days ago: win
        # 5. 2 days ago: win (within grace period, but query doesn't filter grace period)
        # (void and flat excluded)
        assert outcomes == ["loss", "win", "loss", "win", "win"]

        session.close()

    def test_void_outcomes_excluded(self, evaluation_db):
        """Test void outcomes are excluded."""
        session = evaluation_db()

        outcomes = get_trader_outcomes_chronological(session, "0xTrader1")

        # Should not include "void"
        assert "void" not in outcomes

        session.close()

    def test_flat_outcomes_excluded(self, evaluation_db):
        """Test flat outcomes are excluded."""
        session = evaluation_db()

        outcomes = get_trader_outcomes_chronological(session, "0xTrader1")

        # Should not include "flat"
        assert "flat" not in outcomes

        session.close()

    def test_only_resolved_positions(self, evaluation_db):
        """Test only resolved positions included."""
        session = evaluation_db()

        outcomes = get_trader_outcomes_chronological(session, "0xTrader1")

        # Unresolved position on market4 should not be included
        # (it has outcome=None anyway)
        assert len(outcomes) == 5  # Only resolved, non-void, non-flat outcomes

        session.close()

    def test_empty_result_for_no_outcomes(self, evaluation_db):
        """Test empty list for trader with no resolved outcomes."""
        session = evaluation_db()

        outcomes = get_trader_outcomes_chronological(session, "0xTrader2")

        # Trader2 has no resolved positions
        assert outcomes == []

        session.close()

    def test_nonexistent_trader_returns_empty(self, evaluation_db):
        """Test nonexistent trader returns empty list."""
        session = evaluation_db()

        outcomes = get_trader_outcomes_chronological(session, "0xNonexistent")

        assert outcomes == []

        session.close()
