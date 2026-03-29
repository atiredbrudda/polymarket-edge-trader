"""Integration tests for signal detection module.

Tests the convergence detection logic for identifying when >=2 Q5 (top quintile)
traders converge on the same market with the same direction.

Verifies:
- Convergence requires exactly >=2 Q5 traders (not Q1-Q4)
- first_seen preserved across multiple detect runs
- FLAT positions (size=0) excluded from signals
- Resolved positions excluded from signals
- Separate signals for LONG vs SHORT on same market
- Upsert resets alerted flag
"""

import pytest
import sqlite_utils
from datetime import datetime, timezone, timedelta

from src.polymarket_analytics.db.schema import init_database
from src.polymarket_analytics.detection.convergence import detect_convergence
from src.polymarket_analytics.detection.writer import upsert_signal


@pytest.fixture
def detection_db(tmp_path):
    """Create in-memory database with full schema for detection tests.

    Args:
        tmp_path: Pytest tmp_path fixture

    Yields:
        sqlite_utils.Database with all tables initialized
    """
    db_path = tmp_path / "detection_test.db"
    db = init_database(db_path)
    yield db


@pytest.fixture
def fixture_traders():
    """Return fixture trader addresses for detection tests.

    Returns:
        dict with trader addresses for test fixtures
    """
    return {
        "q5_trader_a": "0xQ5TraderA_123456789012345678901234567890abcdef",
        "q5_trader_b": "0xQ5TraderB_123456789012345678901234567890abcdef",
        "q5_trader_c": "0xQ5TraderC_123456789012345678901234567890abcdef",
        "q3_trader": "0xQ3Trader_1234567890123456789012345678901234abcd",
        "q1_trader": "0xQ1Trader_1234567890123456789012345678901234abcd",
    }


@pytest.fixture
def fixture_markets():
    """Return fixture market condition IDs.

    Returns:
        dict with market condition IDs for test fixtures
    """
    return {
        "market_a": "0xMarketA_ESports_TeamLiquid_vs_NaVi_CS2",
        "market_b": "0xMarketB_ESports_T1_vs_GenG_LoL_Worlds",
        "market_c": "0xMarketC_Politics_Trump_vs_Biden",
    }


def create_q5_trader(
    db: sqlite_utils.Database,
    trader_address: str,
    niche_slug: str,
    composite_score: float = 1.5,
) -> None:
    """Helper function to create a Q5 trader with lift_scores record.

    Args:
        db: sqlite_utils Database instance
        trader_address: Trader wallet address
        niche_slug: Niche category (e.g., 'esports')
        composite_score: Composite score for the trader

    Returns:
        trader_address for chaining
    """
    # Insert trader record
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db["traders"].insert(
        {
            "address": trader_address,
            "backfill_complete": 1,
            "first_seen": now,
            "last_seen": now,
            "created_at": now,
        },
        replace=True,
    )

    # Insert lift_scores record with quintile=5
    db["lift_scores"].insert(
        {
            "trader_address": trader_address,
            "category": niche_slug,
            "composite_score": composite_score,
            "clv_raw": 0.5,
            "clv_zscore": 1.0,
            "roi_raw": 0.3,
            "roi_zscore": 0.8,
            "sharpe_raw": 1.2,
            "sharpe_zscore": 0.7,
            "quintile": 5,
            "position_count": 10,
            "total_pnl": 500.0,
            "window_start": now,
            "window_end": now,
            "computed_at": now,
        },
        replace=True,
    )

    return trader_address


def create_qn_trader(
    db: sqlite_utils.Database,
    trader_address: str,
    niche_slug: str,
    quintile: int,
    composite_score: float = 0.5,
) -> None:
    """Helper function to create a non-Q5 trader with lift_scores record.

    Args:
        db: sqlite_utils Database instance
        trader_address: Trader wallet address
        niche_slug: Niche category (e.g., 'esports')
        quintile: Quintile value (1-4)
        composite_score: Composite score for the trader
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db["traders"].insert(
        {
            "address": trader_address,
            "backfill_complete": 1,
            "first_seen": now,
            "last_seen": now,
            "created_at": now,
        },
        replace=True,
    )

    db["lift_scores"].insert(
        {
            "trader_address": trader_address,
            "category": niche_slug,
            "composite_score": composite_score,
            "clv_raw": 0.1,
            "clv_zscore": -0.5,
            "roi_raw": 0.05,
            "roi_zscore": -0.3,
            "sharpe_raw": 0.2,
            "sharpe_zscore": -0.2,
            "quintile": quintile,
            "position_count": 5,
            "total_pnl": 50.0,
            "window_start": now,
            "window_end": now,
            "computed_at": now,
        },
        replace=True,
    )


def create_position(
    db: sqlite_utils.Database,
    trader_address: str,
    market_id: str,
    direction: str,
    size: float,
    avg_entry_price: float = 0.5,
    resolved: bool = False,
    outcome: str = None,
    pnl: float = None,
    entry_timestamp: str = None,
    last_trade_timestamp: str = None,
) -> dict:
    """Helper function to create a position record.

    Args:
        db: sqlite_utils Database instance
        trader_address: Trader wallet address
        market_id: Market condition ID
        direction: LONG or SHORT
        size: Position size (use 0 for FLAT)
        avg_entry_price: Average entry price
        resolved: Whether position is resolved
        outcome: WIN/LOSS/None
        pnl: Profit/loss value
        entry_timestamp: Entry timestamp (ISO format)
        last_trade_timestamp: Last trade timestamp (ISO format)

    Returns:
        Position data dict
    """
    now = datetime.now(timezone.utc)
    entry_ts = entry_timestamp or (now - timedelta(days=10)).isoformat().replace(
        "+00:00", "Z"
    )
    last_trade_ts = last_trade_timestamp or now.isoformat().replace("+00:00", "Z")

    import hashlib

    position_id = hashlib.sha256(
        f"{trader_address}{market_id}{direction}".encode()
    ).hexdigest()[:16]

    position_data = {
        "id": position_id,
        "trader_address": trader_address,
        "market_id": market_id,
        "direction": direction,
        "size": size,
        "avg_entry_price": avg_entry_price,
        "entry_timestamp": entry_ts,
        "last_trade_timestamp": last_trade_ts,
        "trade_count": 1,
        "resolved": 1 if resolved else 0,
        "outcome": outcome,
        "pnl": pnl,
    }

    db["positions"].insert(position_data, replace=True)
    return position_data


def create_market(
    db: sqlite_utils.Database, condition_id: str, niche_slug: str, outcome: str = None
) -> None:
    """Helper function to create a market record.

    Args:
        db: sqlite_utils Database instance
        condition_id: Market condition ID
        niche_slug: Niche category
        outcome: Market outcome (YES/NO/None for unresolved)
    """
    now = datetime.now(timezone.utc)
    db["markets"].insert(
        {
            "condition_id": condition_id,
            "question": f"Test market: {condition_id}",
            "category": niche_slug,
            "niche_slug": niche_slug,
            "outcome": outcome,
            "end_date": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "active": outcome is None,
            "tokens": "[]",
            "created_at": (now - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        },
        replace=True,
    )


class TestConvergenceDetection:
    """Tests for convergence detection logic."""

    def test_convergence_detection_basic(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test basic convergence detection with 2 Q5 traders on same market+direction.

        Fixture setup:
        - 2 Q5 traders (A, B) with positions on market_a, direction LONG
        - Both traders have lift_scores with quintile=5

        Expected:
        - detect_convergence returns 1 row with q5_count=2
        """
        db = detection_db

        # Setup: Create markets
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Setup: Create 2 Q5 traders with lift_scores
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )

        # Setup: Create positions for both traders on same market+direction
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q5_trader_b"],
            fixture_markets["market_a"],
            "LONG",
            size=50.0,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: 1 convergence signal found
        assert len(result_df) == 1, (
            f"Expected 1 convergence signal, got {len(result_df)}"
        )

        # Assert: q5_count = 2
        row = result_df.iloc[0]
        assert row["q5_count"] == 2, f"Expected q5_count=2, got {row['q5_count']}"
        assert row["market_id"] == fixture_markets["market_a"]
        assert row["direction"] == "LONG"

        # Assert: avg_score is average of the two Q5 composite scores
        expected_avg_score = (1.5 + 1.2) / 2
        assert abs(row["avg_score"] - expected_avg_score) < 0.001

    def test_convergence_requires_q5_traders(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that convergence requires quintile=5 traders only (not Q1-Q4).

        Fixture setup:
        - 2 Q3 traders (quintile=3) on same market+direction

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Setup: Create 2 Q3 traders (NOT Q5)
        create_qn_trader(db, fixture_traders["q3_trader"], "esports", quintile=3)
        create_qn_trader(db, fixture_traders["q1_trader"], "esports", quintile=1)

        # Setup: Create positions for both traders
        create_position(
            db,
            fixture_traders["q3_trader"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q1_trader"],
            fixture_markets["market_a"],
            "LONG",
            size=50.0,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: No convergence (Q3/Q1 traders don't count)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for Q3 traders, got {len(result_df)}"
        )

    def test_convergence_minimum_two_traders(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that convergence requires >=2 Q5 traders (single trader doesn't trigger).

        Fixture setup:
        - 1 Q5 trader on market

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Setup: Create 1 Q5 trader
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )

        # Setup: Create position
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: No convergence (need >=2 traders)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for 1 trader, got {len(result_df)}"
        )

    def test_separate_signals_per_direction(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that LONG and SHORT are separate signals on same market.

        Fixture setup:
        - 2 Q5 traders LONG on market_a
        - 2 Q5 traders SHORT on market_a

        Expected:
        - detect_convergence returns 2 rows (one per direction)
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Setup: Create 4 Q5 traders (2 for LONG, 2 for SHORT)
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_c"], "esports", composite_score=1.0
        )
        # Add one more for SHORT side
        create_q5_trader(
            db, fixture_traders["q1_trader"], "esports", composite_score=0.8
        )

        # Setup: Create LONG positions (2 traders)
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q5_trader_b"],
            fixture_markets["market_a"],
            "LONG",
            size=50.0,
            resolved=False,
        )

        # Setup: Create SHORT positions (2 traders)
        create_position(
            db,
            fixture_traders["q5_trader_c"],
            fixture_markets["market_a"],
            "SHORT",
            size=75.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q1_trader"],
            fixture_markets["market_a"],
            "SHORT",
            size=60.0,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: 2 convergence signals (one LONG, one SHORT)
        assert len(result_df) == 2, (
            f"Expected 2 convergence signals (LONG+SHORT), got {len(result_df)}"
        )

        # Assert: One row per direction
        directions = set(result_df["direction"].tolist())
        assert directions == {"LONG", "SHORT"}

    def test_upsert_preserves_first_seen(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that upsert_signal preserves first_seen timestamp on updates.

        Fixture setup:
        - Insert signal via upsert_signal
        - Wait briefly, call upsert_signal again with different q5_count

        Expected:
        - first_seen unchanged after update
        - last_updated changed
        - q5_count updated
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Act 1: Insert initial signal
        first_seen = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        upsert_signal(
            db,
            market_id=fixture_markets["market_a"],
            direction="LONG",
            q5_count=2,
            avg_score=1.25,
            first_seen=first_seen,
            last_updated=first_seen,
        )

        # Wait briefly
        import time

        time.sleep(0.1)

        # Act 2: Update signal with new data
        last_updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        upsert_signal(
            db,
            market_id=fixture_markets["market_a"],
            direction="LONG",
            q5_count=3,  # Changed
            avg_score=1.35,  # Changed
            first_seen=last_updated,  # This should be IGNORED (preserve original)
            last_updated=last_updated,
        )

        # Assert: Fetch signal from DB
        rows = list(
            db.query(
                "SELECT id, market_id, direction, q5_count, avg_score, first_seen, last_updated FROM signals WHERE market_id = :market_id AND direction = :direction",
                {"market_id": fixture_markets["market_a"], "direction": "LONG"},
            )
        )

        assert len(rows) == 1, "Expected 1 signal record"
        signal = rows[0]

        # Assert: first_seen preserved from original insert
        assert signal["first_seen"] == first_seen, (
            f"first_seen should be preserved: expected {first_seen}, got {signal['first_seen']}"
        )

        # Assert: last_updated changed to new value
        assert signal["last_updated"] == last_updated, (
            f"last_updated should be updated: expected {last_updated}, got {signal['last_updated']}"
        )

        # Assert: q5_count updated
        assert signal["q5_count"] == 3, (
            f"q5_count should be updated to 3, got {signal['q5_count']}"
        )

        # Assert: avg_score updated
        assert abs(signal["avg_score"] - 1.35) < 0.001, (
            f"avg_score should be updated to 1.35, got {signal['avg_score']}"
        )

    def test_upsert_resets_alerted(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that upsert_signal resets alerted=0 on updates.

        Fixture setup:
        - Insert signal with alerted=1
        - Call upsert_signal again with new data

        Expected:
        - alerted=0 after update (ready for re-alert)
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Act 1: Insert initial signal with alerted=1
        first_seen = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )

        # Insert with alerted=1 manually
        db["signals"].insert(
            {
                "id": "sig_test_alerted",
                "market_id": fixture_markets["market_a"],
                "direction": "LONG",
                "q5_count": 2,
                "avg_score": 1.25,
                "first_seen": first_seen,
                "last_updated": first_seen,
                "alerted": 1,  # Manually set to 1
            }
        )

        # Act 2: Update signal via upsert_signal
        last_updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        upsert_signal(
            db,
            market_id=fixture_markets["market_a"],
            direction="LONG",
            q5_count=2,
            avg_score=1.25,
            first_seen=first_seen,
            last_updated=last_updated,
        )

        # Assert: Fetch signal from DB
        rows = list(
            db.query("SELECT id, alerted FROM signals WHERE id = 'sig_test_alerted'")
        )

        assert len(rows) == 1, "Expected 1 signal record"
        signal = rows[0]

        # Assert: alerted reset to 0
        assert signal["alerted"] == 0, (
            f"alerted should be reset to 0, got {signal['alerted']}"
        )


class TestEdgeCases:
    """Edge case tests for convergence detection."""

    def test_detect_no_q5_traders(self, detection_db, fixture_markets):
        """Test detect_convergence handles zero Q5 traders gracefully.

        Fixture setup:
        - No lift_scores with quintile=5

        Expected:
        - detect_convergence returns empty DataFrame (no crash)
        """
        db = detection_db

        # Setup: Create market but NO traders
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Act: Run convergence detection with no Q5 traders
        result_df = detect_convergence(db, "esports")

        # Assert: Returns empty DataFrame (no crash)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for no Q5 traders, got {len(result_df)}"
        )

    def test_detect_all_positions_resolved(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test detect_convergence returns empty when all positions resolved.

        Fixture setup:
        - 2 Q5 traders with positions
        - All positions have resolved=1

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market with outcome (resolved)
        create_market(db, fixture_markets["market_a"], "esports", outcome="YES")

        # Setup: Create 2 Q5 traders
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )

        # Setup: Create RESOLVED positions (resolved=True)
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            resolved=True,
            outcome="WIN",
            pnl=50.0,
        )
        create_position(
            db,
            fixture_traders["q5_trader_b"],
            fixture_markets["market_a"],
            "LONG",
            size=50.0,
            resolved=True,
            outcome="WIN",
            pnl=25.0,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: No convergence (all positions resolved)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for resolved positions, got {len(result_df)}"
        )

    def test_detect_flat_positions_excluded(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that FLAT (size=0) positions don't generate signals.

        Fixture setup:
        - 2 Q5 traders with FLAT positions (size=0)

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Setup: Create 2 Q5 traders
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )

        # Setup: Create FLAT positions (size=0)
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=0.0,
            resolved=False,  # FLAT position
        )
        create_position(
            db,
            fixture_traders["q5_trader_b"],
            fixture_markets["market_a"],
            "LONG",
            size=0.0,
            resolved=False,  # FLAT position
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: No convergence (size > 0 filter excludes FLAT)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for FLAT positions, got {len(result_df)}"
        )

    def test_detect_niche_scoping(self, detection_db, fixture_traders, fixture_markets):
        """Test that convergence detection is scoped to niche.

        Fixture setup:
        - 2 Q5 traders in "politics" niche
        - Query for "esports" niche

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create markets in different niches
        create_market(db, fixture_markets["market_a"], "esports", None)
        create_market(db, fixture_markets["market_c"], "politics", None)

        # Setup: Create 2 Q5 traders in POLITICS niche (not esports)
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "politics", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "politics", composite_score=1.2
        )

        # Setup: Create positions for politics markets
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_c"],
            "LONG",
            size=100.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q5_trader_b"],
            fixture_markets["market_c"],
            "LONG",
            size=50.0,
            resolved=False,
        )

        # Act: Query for ESPORTS niche (should find nothing)
        result_df = detect_convergence(db, "esports")

        # Assert: No convergence (traders are in politics, not esports)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for wrong niche, got {len(result_df)}"
        )

    def test_detect_dependency_assertions(self, detection_db):
        """Test that missing dependency tables raise clear error messages.

        Fixture setup:
        - Database with schema but lift_scores table dropped

        Expected:
        - click.ClickException with clear message about missing tables
        """
        db = detection_db

        # Drop lift_scores table to simulate missing dependency
        db["lift_scores"].drop()

        # Act & Assert: Should raise ClickException about missing lift_scores
        import click

        with pytest.raises(click.ClickException) as exc_info:
            detect_convergence(db, "esports")

        # Should mention lift_scores table missing
        error_msg = str(exc_info.value)
        assert "lift_scores table does not exist" in error_msg

    def test_convergence_counts_distinct_traders(
        self, detection_db, fixture_traders, fixture_markets
    ):
        """Test that q5_count counts distinct traders, not positions.

        Fixture setup:
        - 1 Q5 trader with 3 positions on same market (same direction)

        Expected:
        - detect_convergence returns empty DataFrame (q5_count=1, not >=2)
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None)

        # Setup: Create 1 Q5 trader
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )

        # Setup: Create 3 positions for SAME trader on same market+direction
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=50.0,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=75.0,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: No convergence (only 1 distinct trader, even with 3 positions)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for 1 trader with multiple positions, got {len(result_df)}"
        )
