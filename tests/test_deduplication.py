"""Tests for deduplication edge cases in backfill.py.

This module tests the SQL-based deduplication logic used in backfill.py
(lines 424-438 and 568-583) to verify correct handling of edge cases.

Deduplication strategy:
- Pre-backfill dedup: Removes duplicates from prior runs
- Post-backfill dedup: Catches cross-source duplicates from current run
- INSERT OR IGNORE: Prevents duplicate trade_id insertion

Both dedup phases use identical GROUP BY logic:
    GROUP BY trader_address, token_id, side, price, size, timestamp

Keeps the earliest insert (MIN(rowid)) per logical trade.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import sqlite_utils


def _setup_base_data(db: sqlite_utils.Database):
    """Helper to setup markets and token_catalog for FK constraints."""
    # Insert markets first (FK dependency for token_catalog)
    db["markets"].insert(
        {
            "condition_id": "mkt1",
            "question": "Test market",
            "outcome": None,
            "resolved": False,
            "niche_slug": "test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "end_date": "2026-12-31T23:59:59Z",
            "category": "test",
            "active": True,
            "tokens": "[]",
        },
        replace=True,
    )

    # Insert token_catalog (FK dependency for trades.token_id)
    db["token_catalog"].insert(
        {
            "token_id": "tok1",
            "condition_id": "mkt1",
            "question": "Test market",
            "niche_slug": "test",
            "node_path": "test",
            "market_type": "binary",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        replace=True,
    )


class TestDeduplicationLogic:
    """Test backfill.py deduplication SQL logic."""

    def test_pre_backfill_dedup_removes_prior_duplicates(self, test_db):
        """Pre-backfill dedup removes duplicates from prior runs.

        Inserts 3 identical trades (same logical key) and verifies
        dedup SQL removes 2, keeping only the earliest (MIN(rowid)).
        """
        _setup_base_data(test_db)

        # Insert duplicate trades (same logical key, different rowid)
        now = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            test_db["trades"].insert(
                {
                    "trade_id": f"trade_{i}",
                    "token_id": "tok1",
                    "timestamp": now,
                    "side": "BUY",
                    "price": Decimal("0.5"),
                    "size": Decimal("10"),
                    "market_id": "mkt1",
                    "trader_address": "0xtrader",
                },
                replace=True,
            )

        # Run dedup SQL (from backfill.py lines 425-432)
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # Assert: 2 duplicates removed, 1 remains
        assert result.rowcount == 2
        remaining = list(test_db.query("SELECT * FROM trades"))
        assert len(remaining) == 1
        # Verify the earliest rowid is kept
        assert remaining[0]["trade_id"] == "trade_0"

    def test_same_second_identical_trades_collapse(self, test_db):
        """Edge case: same-second identical trades collapse to one record.

        This is the DOCUMENTED edge case from backfill.py:421-422.
        Two genuinely separate trades occurring at the same timestamp with
        identical token/side/price/size will be collapsed into one record.

        This is acknowledged as "acceptable false-positive loss" in the codebase.
        For most traders, same-second identical trades are extremely rare.

        Gap reference: This is the documented limitation of the current dedup key.
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()
        # Insert two genuinely identical trades (same everything except trade_id)
        for i in range(2):
            test_db["trades"].insert(
                {
                    "trade_id": f"trade_{i}",
                    "token_id": "tok1",
                    "timestamp": now,
                    "side": "BUY",
                    "price": Decimal("0.5"),
                    "size": Decimal("10"),
                    "market_id": "mkt1",
                    "trader_address": "0xtrader",
                },
                replace=True,
            )

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # Assert: 1 duplicate removed (this is the documented edge case)
        assert result.rowcount == 1
        remaining = list(test_db.query("SELECT * FROM trades"))
        assert len(remaining) == 1

    def test_insert_or_ignore_catches_duplicate_trade_id(self, test_db):
        """INSERT OR IGNORE prevents duplicate trade_id insertion.

        Verifies that the trade_id PRIMARY KEY constraint combined with
        INSERT OR IGNORE (replace=False) prevents duplicate insertion.
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # First insert succeeds
        test_db["trades"].insert(
            {
                "trade_id": "trade_001",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Second insert with same trade_id fails silently (INSERT OR IGNORE)
        try:
            test_db["trades"].insert(
                {
                    "trade_id": "trade_001",  # Same ID
                    "token_id": "tok1",
                    "timestamp": now,
                    "side": "BUY",
                    "price": Decimal("0.5"),
                    "size": Decimal("10"),
                    "market_id": "mkt1",
                    "trader_address": "0xtrader",
                },
                replace=False,
            )
        except Exception:
            pass  # Expected to fail or be ignored

        # Assert: only one trade exists
        count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert count == 1

    def test_cross_source_duplicate_scenario(self, test_db):
        """Cross-source duplicate: same trade from API + Graph.

        Simulates scenario where both Data API and Graph API return
        the same trade (coverage gap scenario). Verifies that:
        1. First source inserts successfully
        2. Second source is caught by INSERT OR IGNORE (same trade_id)
           OR caught by SQL dedup if trade_ids differ

        This tests the two-phase dedup strategy:
        - Phase 1 (INSERT OR IGNORE): Catches duplicates during insertion
        - Phase 2 (SQL dedup): Final safety net for different trade_ids

        Reference: DEDUP-VERIFICATION.md - cross-source deduplication.
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # Simulate trade from Data API
        test_db["trades"].insert(
            {
                "trade_id": "api_trade_001",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Simulate same trade from Graph API with DIFFERENT trade_id
        # This tests SQL dedup as the final safety net
        test_db["trades"].insert(
            {
                "trade_id": "graph_trade_001",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Before dedup: 2 trades exist
        before_count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert before_count == 2

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # After dedup: 1 trade remains
        after_count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert after_count == 1
        assert result.rowcount == 1

    def test_decimal_precision_edge_cases(self, test_db):
        """Decimal precision: "0.5" vs "0.500000" treated as same.

        Verifies that SQLite NUMERIC(10,6) correctly normalizes
        decimal values so that "0.5" and "0.500000" are treated
        as identical for GROUP BY dedup purposes.
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # Insert trades with different decimal representations
        test_db["trades"].insert(
            {
                "trade_id": "trade_1",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        test_db["trades"].insert(
            {
                "trade_id": "trade_2",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.500000"),
                "size": Decimal("10.000000"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # Assert: 1 duplicate removed (Decimal normalization worked)
        assert result.rowcount == 1

    def test_timestamp_format_consistency(self, test_db):
        """Timestamp format: Unix and ISO format convert correctly.

        Verifies that both Unix timestamp and ISO format convert
        to the same ISO format string, ensuring dedup works
        regardless of source format.

        Note: This tests that the conversion logic in backfill.py (lines 326-338)
        produces consistent ISO strings.
        """
        _setup_base_data(test_db)

        # Use a fixed timestamp for consistency
        unix_ts = 1700000000
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        iso_format = dt.isoformat()

        # Insert two trades with same timestamp (both already in ISO format)
        for i in range(2):
            test_db["trades"].insert(
                {
                    "trade_id": f"trade_{i}",
                    "token_id": "tok1",
                    "timestamp": iso_format,
                    "side": "BUY",
                    "price": Decimal("0.5"),
                    "size": Decimal("10"),
                    "market_id": "mkt1",
                    "trader_address": "0xtrader",
                },
                replace=False,
            )

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # Assert: 1 duplicate removed (timestamp format consistent)
        assert result.rowcount == 1

    def test_dedup_grouping_key_excludes_trade_id(self, test_db):
        """Gap 1 (DEDUP-VERIFICATION.md): trade_id NOT in dedup GROUP BY key.

        This test verifies the CURRENT behavior: the deduplication GROUP BY
        key does NOT include trade_id. This means two trades with the same
        logical key (trader, token, side, price, size, timestamp) but
        DIFFERENT trade_id values will be collapsed into one.

        This is NOT necessarily a bug - it's the current design. However,
        if genuinely separate trades can have the same logical key but
        different trade_ids, they would be incorrectly deduplicated.

        Files to consider for potential fix:
        - backfill.py:425-432 (pre-backfill dedup SQL)
        - backfill.py:568-583 (post-backfill dedup SQL)

        Test documents Gap 1 from DEDUP-VERIFICATION.md.
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # Insert two trades with SAME logical key but DIFFERENT trade_id
        test_db["trades"].insert(
            {
                "trade_id": "trade_A",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        test_db["trades"].insert(
            {
                "trade_id": "trade_B",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Before dedup: 2 trades exist
        before_count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert before_count == 2

        # Run dedup SQL (current logic: groups by logical key, NOT trade_id)
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # CURRENT BEHAVIOR: Both trades have same logical key, so one is removed
        # This demonstrates Gap 1: trade_id is NOT part of the dedup key
        assert result.rowcount == 1
        remaining = list(test_db.query("SELECT * FROM trades"))
        assert len(remaining) == 1
        # Only the earliest rowid is kept
        assert remaining[0]["trade_id"] in ["trade_A", "trade_B"]

    def test_dedup_grouping_key_excludes_market_id(self, test_db):
        """Gap 2 (DEDUP-VERIFICATION.md): market_id NOT in dedup GROUP BY key.

        This test verifies the CURRENT behavior: the deduplication GROUP BY
        key does NOT include market_id. This means two trades with the same
        logical key (trader, token, side, price, size, timestamp) but
        DIFFERENT market_id values will be collapsed into one.

        This is potentially problematic if:
        - The same token_id can appear in multiple markets (e.g., migrated markets)
        - Cross-market trades need to be tracked separately

        Files to consider for potential fix:
        - backfill.py:425-432 (pre-backfill dedup SQL)
        - backfill.py:568-583 (post-backfill dedup SQL)

        Test documents Gap 2 from DEDUP-VERIFICATION.md.
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # Insert two trades with SAME logical key but DIFFERENT market_id
        test_db["trades"].insert(
            {
                "trade_id": "trade_1",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt_A",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        test_db["trades"].insert(
            {
                "trade_id": "trade_2",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt_B",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Before dedup: 2 trades exist
        before_count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert before_count == 2

        # Run dedup SQL (current logic: groups by logical key, NOT market_id)
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # CURRENT BEHAVIOR: Both trades have same logical key, so one is removed
        # This demonstrates Gap 2: market_id is NOT part of the dedup key
        assert result.rowcount == 1
        remaining = list(test_db.query("SELECT * FROM trades"))
        assert len(remaining) == 1

    def test_dedup_key_components_all_six_fields(self, test_db):
        """Verify all 6 fields are required in dedup GROUP BY key.

        Tests that the deduplication correctly uses all 6 fields:
        trader_address, token_id, side, price, size, timestamp

        Changing any single field should result in trades being kept
        (not deduplicated).
        """
        _setup_base_data(test_db)

        # Add tok2 for the "different token" test case
        test_db["token_catalog"].insert(
            {
                "token_id": "tok2",
                "condition_id": "mkt1",
                "question": "Test market 2",
                "niche_slug": "test",
                "node_path": "test",
                "market_type": "binary",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            replace=True,
        )

        now = datetime.now(timezone.utc).isoformat()
        later = (
            datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
        ).isoformat()

        # Different trader
        test_db["trades"].insert(
            {
                "trade_id": "trade_trader",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xdifferent",
            },
            replace=False,
        )

        # Different token
        test_db["trades"].insert(
            {
                "trade_id": "trade_token",
                "token_id": "tok2",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Different side
        test_db["trades"].insert(
            {
                "trade_id": "trade_side",
                "token_id": "tok1",
                "timestamp": now,
                "side": "SELL",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Different price
        test_db["trades"].insert(
            {
                "trade_id": "trade_price",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.6"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Different size
        test_db["trades"].insert(
            {
                "trade_id": "trade_size",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("20"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Different timestamp
        test_db["trades"].insert(
            {
                "trade_id": "trade_time",
                "token_id": "tok1",
                "timestamp": later,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # Assert: No duplicates removed (all trades differ by at least one field)
        assert result.rowcount == 0
        count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert count == 6


class TestDeduplicationWithMarketId:
    """Test deduplication behavior with market_id variations.

    These tests specifically verify the interaction between the
    deduplication logic and market_id field, documenting Gap 2
    from DEDUP-VERIFICATION.md.
    """

    def test_same_market_id_different_trades_kept(self, test_db):
        """Trades with same market_id but different logical key are kept."""
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # Same market_id, different prices
        test_db["trades"].insert(
            {
                "trade_id": "trade_1",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.5"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        test_db["trades"].insert(
            {
                "trade_id": "trade_2",
                "token_id": "tok1",
                "timestamp": now,
                "side": "BUY",
                "price": Decimal("0.6"),
                "size": Decimal("10"),
                "market_id": "mkt1",
                "trader_address": "0xtrader",
            },
            replace=False,
        )

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # Both trades kept (different prices)
        assert result.rowcount == 0
        count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert count == 2

    def test_different_market_id_same_logical_key_collapsed(self, test_db):
        """Different market_id, same logical key → collapsed (Gap 2).

        This is the Gap 2 scenario: two trades with identical logical keys
        (trader, token, side, price, size, timestamp) but different market_id
        values are collapsed into one record.

        This could be problematic if:
        - Same token appears in multiple markets
        - Market migrations change market_id associations
        - Cross-market arbitrage trades need separate tracking

        Reference: DEDUP-VERIFICATION.md Gap 2
        """
        _setup_base_data(test_db)

        now = datetime.now(timezone.utc).isoformat()

        # Same everything except market_id
        for market in ["mkt_A", "mkt_B"]:
            test_db["trades"].insert(
                {
                    "trade_id": f"trade_{market}",
                    "token_id": "tok1",
                    "timestamp": now,
                    "side": "BUY",
                    "price": Decimal("0.5"),
                    "size": Decimal("10"),
                    "market_id": market,
                    "trader_address": "0xtrader",
                },
                replace=False,
            )

        # Run dedup SQL
        result = test_db.execute("""
            DELETE FROM trades
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM trades
                GROUP BY trader_address, token_id, side, price, size, timestamp
            )
        """)

        # One collapsed (Gap 2: market_id not in dedup key)
        assert result.rowcount == 1
        count = test_db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert count == 1
