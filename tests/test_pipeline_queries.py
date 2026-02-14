"""Tests for pipeline query functions (backfill state queries)."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Trader
from src.pipeline.queries import (
    get_traders_by_backfill_status,
    get_trader_counts_by_status,
)


@pytest.fixture
def session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def test_get_traders_by_backfill_status_pending(session):
    """Test filtering for pending (not backfilled) traders."""
    t1 = Trader(
        address="0x111", backfill_complete=False, first_seen=datetime(2025, 1, 1)
    )
    t2 = Trader(
        address="0x222", backfill_complete=False, first_seen=datetime(2025, 2, 1)
    )
    t3 = Trader(
        address="0x333", backfill_complete=True, first_seen=datetime(2025, 3, 1)
    )
    session.add_all([t1, t2, t3])
    session.commit()

    result = get_traders_by_backfill_status(session, backfilled=False)

    assert len(result) == 2
    assert all(trader.backfill_complete == False for trader in result)


def test_get_traders_by_backfill_status_completed(session):
    """Test filtering for completed (backfilled) traders."""
    t1 = Trader(
        address="0x111", backfill_complete=False, first_seen=datetime(2025, 1, 1)
    )
    t2 = Trader(
        address="0x222", backfill_complete=False, first_seen=datetime(2025, 2, 1)
    )
    t3 = Trader(
        address="0x333", backfill_complete=True, first_seen=datetime(2025, 3, 1)
    )
    session.add_all([t1, t2, t3])
    session.commit()

    result = get_traders_by_backfill_status(session, backfilled=True)

    assert len(result) == 1
    assert result[0].backfill_complete == True


def test_get_traders_by_backfill_status_empty(session):
    """Test filtering returns empty list when no matches."""
    t1 = Trader(
        address="0x111", backfill_complete=True, first_seen=datetime(2025, 1, 1)
    )
    t2 = Trader(
        address="0x222", backfill_complete=True, first_seen=datetime(2025, 2, 1)
    )
    session.add_all([t1, t2])
    session.commit()

    result = get_traders_by_backfill_status(session, backfilled=False)

    assert result == []


def test_get_traders_by_backfill_status_ordering(session):
    """Test that results are ordered by first_seen DESC (most recent first)."""
    t1 = Trader(
        address="0x111", backfill_complete=False, first_seen=datetime(2025, 1, 1)
    )
    t2 = Trader(
        address="0x222", backfill_complete=False, first_seen=datetime(2025, 6, 1)
    )
    t3 = Trader(
        address="0x333", backfill_complete=False, first_seen=datetime(2025, 3, 1)
    )
    session.add_all([t1, t2, t3])
    session.commit()

    result = get_traders_by_backfill_status(session, backfilled=False)

    assert result[0].first_seen == datetime(2025, 6, 1)
    assert result[1].first_seen == datetime(2025, 3, 1)
    assert result[2].first_seen == datetime(2025, 1, 1)


def test_get_trader_counts_by_status(session):
    """Test count summary returns correct totals."""
    t1 = Trader(address="0x111", backfill_complete=False)
    t2 = Trader(address="0x222", backfill_complete=False)
    t3 = Trader(address="0x333", backfill_complete=False)
    t4 = Trader(address="0x444", backfill_complete=True)
    t5 = Trader(address="0x555", backfill_complete=True)
    session.add_all([t1, t2, t3, t4, t5])
    session.commit()

    result = get_trader_counts_by_status(session)

    assert result == {"discovered": 3, "backfilled": 2, "total": 5}


def test_get_trader_counts_by_status_empty(session):
    """Test count summary returns zeros for empty database."""
    result = get_trader_counts_by_status(session)

    assert result == {"discovered": 0, "backfilled": 0, "total": 0}
