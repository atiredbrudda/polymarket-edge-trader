"""
Tests for trader discovery and position computation.

Tests trader discovery with threshold filtering and position storage.
Uses in-memory SQLite with pre-seeded data.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    Market,
    Trade,
    MarketEntity,
    Position,
)
from src.discovery.trader_discovery import (
    discover_esports_traders,
    compute_and_store_positions,
    refresh_all_positions,
)


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


@pytest.fixture
def seed_esports_data(in_memory_db):
    """Seed database with eSports entities and markets."""
    with in_memory_db() as session:
        # Create market entities
        entity1 = MarketEntity(
            condition_id="market_cs2_1",
            team_a="NaVi",
            team_b="FaZe",
            tournament="IEM Katowice",
            game="CS2",
            market_type="match",
        )
        entity2 = MarketEntity(
            condition_id="market_cs2_2",
            team_a="G2",
            team_b="Vitality",
            tournament="ESL Pro League",
            game="CS2",
            market_type="match",
        )
        session.add_all([entity1, entity2])

        # Create markets
        market1 = Market(
            condition_id="market_cs2_1",
            question="NaVi vs FaZe IEM Katowice",
            category="eSports",
            active=True,
        )
        market2 = Market(
            condition_id="market_cs2_2",
            question="G2 vs Vitality ESL Pro League",
            category="eSports",
            active=True,
        )
        market3 = Market(
            condition_id="market_politics",
            question="US Election 2024",
            category="Politics",
            active=True,
        )
        session.add_all([market1, market2, market3])
        # market_politics has NO MarketEntity row (not esports)
        session.commit()


@pytest.fixture
def seed_trader_data(in_memory_db, seed_esports_data):
    """Seed trade data for testing trader discovery."""
    with in_memory_db() as session:
        base_time = datetime.utcnow()

        # Trader A: 10 trades, $1000 volume in eSports -> SHOULD be discovered
        for i in range(10):
            trade = Trade(
                market_id="market_cs2_1",
                trader_address="0xAAAA",
                side="BUY",
                size=Decimal("100"),
                price=Decimal("0.5"),
                timestamp=base_time + timedelta(minutes=i),
                trade_id=f"trade_a_{i}",
            )
            session.add(trade)

        # Trader B: 3 trades, $1000 volume in eSports -> SHOULD NOT (below trade threshold)
        for i in range(3):
            trade = Trade(
                market_id="market_cs2_1",
                trader_address="0xBBBB",
                side="BUY",
                size=Decimal("333"),
                price=Decimal("0.5"),
                timestamp=base_time + timedelta(minutes=i),
                trade_id=f"trade_b_{i}",
            )
            session.add(trade)

        # Trader C: 10 trades, $100 volume in eSports -> SHOULD NOT (below volume threshold)
        for i in range(10):
            trade = Trade(
                market_id="market_cs2_1",
                trader_address="0xCCCC",
                side="BUY",
                size=Decimal("10"),
                price=Decimal("0.5"),
                timestamp=base_time + timedelta(minutes=i),
                trade_id=f"trade_c_{i}",
            )
            session.add(trade)

        # Trader D: 10 trades, $1000 volume in NON-eSports -> SHOULD NOT (wrong category)
        for i in range(10):
            trade = Trade(
                market_id="market_politics",
                trader_address="0xDDDD",
                side="BUY",
                size=Decimal("100"),
                price=Decimal("0.5"),
                timestamp=base_time + timedelta(minutes=i),
                trade_id=f"trade_d_{i}",
            )
            session.add(trade)

        # Trader E: 6 trades, $600 volume across two eSports markets -> SHOULD be discovered
        for i in range(3):
            trade = Trade(
                market_id="market_cs2_1",
                trader_address="0xEEEE",
                side="BUY",
                size=Decimal("200"),
                price=Decimal("0.5"),
                timestamp=base_time + timedelta(minutes=i),
                trade_id=f"trade_e1_{i}",
            )
            session.add(trade)
        for i in range(3):
            trade = Trade(
                market_id="market_cs2_2",
                trader_address="0xEEEE",
                side="BUY",
                size=Decimal("200"),
                price=Decimal("0.5"),
                timestamp=base_time + timedelta(minutes=i + 10),
                trade_id=f"trade_e2_{i}",
            )
            session.add(trade)

        session.commit()


def test_discover_traders_above_threshold(in_memory_db, seed_trader_data):
    """Traders above both thresholds are discovered."""
    with in_memory_db() as session:
        traders = discover_esports_traders(session, min_trades=5, min_volume=Decimal("500"))

        # Should discover traders A and E
        assert len(traders) == 2
        assert "0xAAAA" in traders
        assert "0xEEEE" in traders


def test_discover_traders_below_trade_threshold(in_memory_db, seed_trader_data):
    """Trader with high volume but low trade count is NOT discovered."""
    with in_memory_db() as session:
        traders = discover_esports_traders(session, min_trades=5, min_volume=Decimal("500"))

        # Trader B has $1000 volume but only 3 trades
        assert "0xBBBB" not in traders


def test_discover_traders_below_volume_threshold(in_memory_db, seed_trader_data):
    """Trader with many trades but low volume is NOT discovered."""
    with in_memory_db() as session:
        traders = discover_esports_traders(session, min_trades=5, min_volume=Decimal("500"))

        # Trader C has 10 trades but only $100 volume
        assert "0xCCCC" not in traders


def test_discover_traders_esports_only(in_memory_db, seed_trader_data):
    """Trader active in non-eSports markets is NOT discovered."""
    with in_memory_db() as session:
        traders = discover_esports_traders(session, min_trades=5, min_volume=Decimal("500"))

        # Trader D has 10 trades and $1000 volume, but in Politics category
        assert "0xDDDD" not in traders


def test_compute_positions_for_trader(in_memory_db, seed_trader_data):
    """Position computation creates correct Position rows."""
    with in_memory_db() as session:
        # Compute positions for Trader A
        positions = compute_and_store_positions(session, "0xAAAA")

        # Should have one position (one market)
        assert len(positions) == 1

        position = positions[0]
        assert position.trader_address == "0xAAAA"
        assert position.market_id == "market_cs2_1"
        assert position.size == Decimal("1000")  # 10 trades * 100 size
        assert position.direction == "LONG"
        assert position.avg_entry_price == Decimal("0.5")
        assert position.trade_count == 10


def test_refresh_positions_upserts(in_memory_db, seed_trader_data):
    """Second refresh updates existing position, doesn't duplicate."""
    with in_memory_db() as session:
        # First computation
        positions1 = compute_and_store_positions(session, "0xAAAA")
        assert len(positions1) == 1

        # Add more trades for same trader
        base_time = datetime.utcnow()
        for i in range(5):
            trade = Trade(
                market_id="market_cs2_1",
                trader_address="0xAAAA",
                side="SELL",
                size=Decimal("50"),
                price=Decimal("0.6"),
                timestamp=base_time + timedelta(hours=i),
                trade_id=f"trade_a_new_{i}",
            )
            session.add(trade)
        session.commit()

        # Second computation (should update, not duplicate)
        positions2 = compute_and_store_positions(session, "0xAAAA")
        assert len(positions2) == 1

        # Verify only one position exists in DB
        total = session.query(Position).filter_by(trader_address="0xAAAA").count()
        assert total == 1

        # Verify position was updated
        position = positions2[0]
        assert position.size == Decimal("750")  # 1000 bought - 250 sold
        assert position.trade_count == 15  # 10 original + 5 new


def test_refresh_all_positions(in_memory_db, seed_trader_data):
    """Refresh all positions processes multiple traders."""
    with in_memory_db() as session:
        # Refresh for specific traders
        stats = refresh_all_positions(session, trader_addresses=["0xAAAA", "0xEEEE"])

        assert stats["traders_processed"] == 2
        assert stats["positions_computed"] >= 2  # At least 2 positions

        # Verify positions were created
        positions_a = session.query(Position).filter_by(trader_address="0xAAAA").all()
        positions_e = session.query(Position).filter_by(trader_address="0xEEEE").all()

        assert len(positions_a) == 1  # Trader A has 1 market
        assert len(positions_e) == 2  # Trader E has 2 markets
