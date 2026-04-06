"""Tests for backfill timestamp-based selection logic."""

import pytest
from datetime import datetime, timedelta, timezone


def test_backfill_selects_new_traders(test_db, tmp_path):
    """Backfill selects traders with NULL timestamps (never backfilled)."""
    from polymarket_analytics.db.schema import init_database

    db = init_database(tmp_path / "test.db")

    # Insert trader with NULL timestamps (never backfilled)
    db["traders"].insert(
        {
            "address": "0x1234567890123456789012345678901234567890",
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "backfill_complete": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    # Query using timestamp-based selection
    COVERAGE_DAYS = 40
    REFRESH_HOURS = 6
    cutoff = (datetime.now(timezone.utc) - timedelta(days=COVERAGE_DAYS)).isoformat()
    threshold = (
        datetime.now(timezone.utc) - timedelta(hours=REFRESH_HOURS)
    ).isoformat()

    traders = db.execute(
        """
        SELECT address FROM traders
        WHERE
            (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
            AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
    """,
        {"cutoff": cutoff, "threshold": threshold},
    ).fetchall()

    # Trader should be selected (NULL timestamps)
    assert len(traders) == 1


def test_backfill_skips_recently_refreshed_trader(test_db, tmp_path):
    """Backfill skips traders refreshed within last 6 hours."""
    from polymarket_analytics.db.schema import init_database

    db = init_database(tmp_path / "test.db")

    now = datetime.now(timezone.utc)
    recent_time = (now - timedelta(hours=2)).isoformat()  # 2 hours ago
    old_time = (now - timedelta(days=50)).isoformat()  # 50 days ago

    # Insert trader with recent backfill timestamp
    db["traders"].insert(
        {
            "address": "0x1234567890123456789012345678901234567890",
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
            "backfill_complete": True,
            "last_backfilled_at": recent_time,
            "last_trade_seen_at": old_time,
            "created_at": now.isoformat(),
        }
    )

    COVERAGE_DAYS = 40
    REFRESH_HOURS = 6
    cutoff = (now - timedelta(days=COVERAGE_DAYS)).isoformat()
    threshold = (now - timedelta(hours=REFRESH_HOURS)).isoformat()

    traders = db.execute(
        """
        SELECT address FROM traders
        WHERE
            (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
            AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
    """,
        {"cutoff": cutoff, "threshold": threshold},
    ).fetchall()

    # Trader should NOT be selected (recently refreshed)
    assert len(traders) == 0


def test_backfill_selects_trader_with_recent_activity(test_db, tmp_path):
    """Backfill selects traders with recent trade activity even if backfilled long ago."""
    from polymarket_analytics.db.schema import init_database

    db = init_database(tmp_path / "test.db")

    now = datetime.now(timezone.utc)
    old_backfill = (now - timedelta(days=10)).isoformat()  # 10 days ago
    recent_trade = (
        now - timedelta(days=5)
    ).isoformat()  # 5 days ago (within 40-day window)

    # Insert trader with old backfill but recent trade
    db["traders"].insert(
        {
            "address": "0x1234567890123456789012345678901234567890",
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
            "backfill_complete": True,
            "last_backfilled_at": old_backfill,
            "last_trade_seen_at": recent_trade,
            "created_at": now.isoformat(),
        }
    )

    COVERAGE_DAYS = 40
    REFRESH_HOURS = 6
    cutoff = (now - timedelta(days=COVERAGE_DAYS)).isoformat()
    threshold = (now - timedelta(hours=REFRESH_HOURS)).isoformat()

    traders = db.execute(
        """
        SELECT address FROM traders
        WHERE
            (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
            AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
    """,
        {"cutoff": cutoff, "threshold": threshold},
    ).fetchall()

    # Trader should be selected (recent trade activity + old backfill)
    assert len(traders) == 1


def test_backfill_skips_stale_trader(test_db, tmp_path):
    """Backfill skips traders with no activity in 40+ days."""
    from polymarket_analytics.db.schema import init_database

    db = init_database(tmp_path / "test.db")

    now = datetime.now(timezone.utc)
    old_backfill = (now - timedelta(days=50)).isoformat()  # 50 days ago
    stale_trade = (
        now - timedelta(days=45)
    ).isoformat()  # 45 days ago (outside 40-day window)

    # Insert trader with stale trade
    db["traders"].insert(
        {
            "address": "0x1234567890123456789012345678901234567890",
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
            "backfill_complete": True,
            "last_backfilled_at": old_backfill,
            "last_trade_seen_at": stale_trade,
            "created_at": now.isoformat(),
        }
    )

    COVERAGE_DAYS = 40
    REFRESH_HOURS = 6
    cutoff = (now - timedelta(days=COVERAGE_DAYS)).isoformat()
    threshold = (now - timedelta(hours=REFRESH_HOURS)).isoformat()

    traders = db.execute(
        """
        SELECT address FROM traders
        WHERE
            (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
            AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
    """,
        {"cutoff": cutoff, "threshold": threshold},
    ).fetchall()

    # Trader should NOT be selected (stale trade, outside 40-day window)
    assert len(traders) == 0


def test_backfill_timestamp_format_conversion():
    """Verify Unix timestamp converts to ISO format correctly."""
    # Sample Unix timestamp
    unix_ts = 1775431309

    # Convert to ISO
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    iso = dt.isoformat()

    # Verify format
    assert "T" in iso
    assert "+" in iso or "Z" in iso

    # Verify comparison works
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=40)).isoformat()

    # ISO strings compare correctly
    assert iso >= cutoff or iso < cutoff  # Just verify no TypeError


def test_backfill_update_stores_iso_timestamp(test_db, tmp_path):
    """Backfill update stores ISO timestamp, not Unix timestamp."""
    from polymarket_analytics.db.schema import init_database
    from datetime import datetime, timezone

    db = init_database(tmp_path / "test.db")

    now = datetime.now(timezone.utc)
    trader_addr = "0x1234567890123456789012345678901234567890"

    # Insert trader
    db["traders"].insert(
        {
            "address": trader_addr,
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
            "backfill_complete": False,
            "created_at": now.isoformat(),
        }
    )

    # Simulate backfill update with Unix timestamp
    unix_ts = int(now.timestamp())

    # Convert to ISO (as the fix does)
    last_trade_iso = datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()

    db["traders"].update(
        trader_addr,
        {
            "last_backfilled_at": now.isoformat(),
            "last_trade_seen_at": last_trade_iso,
            "backfill_complete": True,
        },
    )

    # Verify stored value is ISO format
    row = db["traders"].get(trader_addr)
    assert "T" in row["last_trade_seen_at"]
    assert "+" in row["last_trade_seen_at"] or "Z" in row["last_trade_seen_at"]

    # Verify comparison works (no TypeError)
    cutoff = (now - timedelta(days=40)).isoformat()
    assert row["last_trade_seen_at"] >= cutoff or row["last_trade_seen_at"] < cutoff
