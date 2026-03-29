"""Integration tests for scoring extraction module.

Tests:
- extract_resolved_positions filters by 30-day window using last_trade_timestamp
- extract_resolved_positions filters by niche_slug
- extract_resolved_positions requires resolved=1
- extract_resolved_positions returns empty DataFrame on no results (no crash)
"""

import pytest
import sqlite_utils
import pandas as pd
from datetime import datetime, timedelta

from polymarket_analytics.db.schema import init_database
from polymarket_analytics.scoring.extraction import extract_resolved_positions


@pytest.fixture
def test_db(tmp_path):
    """Create temporary database with schema for testing.

    Args:
        tmp_path: Pytest temp directory fixture

    Returns:
        sqlite_utils.Database instance with schema initialized
    """
    db_path = tmp_path / "test.db"
    db = sqlite_utils.Database(db_path)
    init_database(db_path)
    return db


@pytest.fixture
def positions_db(test_db):
    """Fixture with positions at different timestamps and niches.

    Creates:
    - Markets in different niches (esports, politics)
    - Positions with different last_trade_timestamps (recent and old)
    - Mix of resolved and unresolved positions

    Args:
        test_db: Base database fixture

    Returns:
        Database with fixture data
    """
    # Calculate dates relative to now
    now = datetime.now()
    recent_date = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_date = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Insert markets for different niches
    test_db["markets"].insert_all(
        [
            {
                "condition_id": "market-esports-1",
                "question": "Will Team Liquid win?",
                "outcome": "YES",
                "resolved": True,
                "niche_slug": "esports",
                "created_at": recent_date,
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": False,
                "tokens": "[]",
            },
            {
                "condition_id": "market-esports-2",
                "question": "Will T1 win?",
                "outcome": "NO",
                "resolved": True,
                "niche_slug": "esports",
                "created_at": recent_date,
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": False,
                "tokens": "[]",
            },
            {
                "condition_id": "market-politics-1",
                "question": "Will candidate X win?",
                "outcome": "YES",
                "resolved": True,
                "niche_slug": "politics",
                "created_at": recent_date,
                "end_date": "2025-12-31T23:59:59Z",
                "category": "politics",
                "active": False,
                "tokens": "[]",
            },
        ]
    )

    # Insert positions with different timestamps and resolved status
    import hashlib

    def make_id(trader: str, market: str) -> str:
        return hashlib.sha256(f"{trader}{market}".encode()).hexdigest()[:16]

    test_db["positions"].insert_all(
        [
            # Recent resolved position in esports (should be returned)
            {
                "id": make_id("trader1", "market-esports-1"),
                "trader_address": "trader1",
                "market_id": "market-esports-1",
                "direction": "LONG",
                "size": 100,
                "avg_entry_price": 0.60,
                "entry_timestamp": old_date,
                "last_trade_timestamp": recent_date,  # 10 days ago - within 30-day window
                "trade_count": 1,
                "resolved": 1,
                "outcome": "WIN",
                "pnl": 40.0,
            },
            # Old resolved position in esports (should NOT be returned - outside window)
            {
                "id": make_id("trader2", "market-esports-1"),
                "trader_address": "trader2",
                "market_id": "market-esports-1",
                "direction": "LONG",
                "size": 50,
                "avg_entry_price": 0.55,
                "entry_timestamp": old_date,
                "last_trade_timestamp": old_date,  # 60 days ago - outside 30-day window
                "trade_count": 1,
                "resolved": 1,
                "outcome": "WIN",
                "pnl": 22.5,
            },
            # Recent unresolved position (should NOT be returned - not resolved)
            {
                "id": make_id("trader3", "market-esports-2"),
                "trader_address": "trader3",
                "market_id": "market-esports-2",
                "direction": "SHORT",
                "size": 75,
                "avg_entry_price": 0.45,
                "entry_timestamp": recent_date,
                "last_trade_timestamp": recent_date,
                "trade_count": 1,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
            # Recent resolved position in politics (should NOT be returned - wrong niche)
            {
                "id": make_id("trader4", "market-politics-1"),
                "trader_address": "trader4",
                "market_id": "market-politics-1",
                "direction": "LONG",
                "size": 200,
                "avg_entry_price": 0.70,
                "entry_timestamp": recent_date,
                "last_trade_timestamp": recent_date,
                "trade_count": 1,
                "resolved": 1,
                "outcome": "WIN",
                "pnl": 60.0,
            },
        ]
    )

    return test_db


def test_extract_resolved_positions_filters_by_window(positions_db):
    """Test that only positions within 30-day window are returned.

    Args:
        positions_db: Database with fixture data including old and recent positions
    """
    df = extract_resolved_positions(positions_db, "esports", window_days=30)

    # Should return only trader1 (recent resolved esports position)
    # trader2 is too old (60 days), trader3 is unresolved, trader4 is wrong niche
    assert len(df) == 1, f"Expected 1 position, got {len(df)}"
    assert df.iloc[0]["trader_address"] == "trader1"
    assert df.iloc[0]["market_id"] == "market-esports-1"


def test_extract_resolved_positions_filters_by_niche(positions_db):
    """Test that only positions from requested niche are returned.

    Args:
        positions_db: Database with fixture data for multiple niches
    """
    # Query esports niche
    df_esports = extract_resolved_positions(positions_db, "esports", window_days=30)
    assert len(df_esports) == 1
    assert df_esports.iloc[0]["trader_address"] == "trader1"

    # Query politics niche - should return trader4
    df_politics = extract_resolved_positions(positions_db, "politics", window_days=30)
    assert len(df_politics) == 1
    assert df_politics.iloc[0]["trader_address"] == "trader4"


def test_extract_resolved_positions_requires_resolved(positions_db):
    """Test that only resolved positions are returned.

    Args:
        positions_db: Database with fixture data including unresolved positions
    """
    df = extract_resolved_positions(positions_db, "esports", window_days=30)

    # trader3 has a recent position but resolved=0, should not be in results
    assert len(df) == 1
    assert "trader3" not in df["trader_address"].values


def test_extract_empty_result_no_crash(test_db):
    """Test that querying with no matching data returns empty DataFrame.

    Args:
        test_db: Database with schema but no data
    """
    df = extract_resolved_positions(test_db, "esports", window_days=30)

    # Should return empty DataFrame, not raise exception
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0

    # Should have expected columns
    expected_columns = [
        "trader_address",
        "market_id",
        "direction",
        "size",
        "avg_entry_price",
        "pnl",
        "trade_count",
        "outcome",
        "end_date",
    ]
    assert list(df.columns) == expected_columns
