"""Integration tests for signal detection module.

Tests the convergence detection logic for identifying when >=2 Q5 (top quintile)
traders converge on the same market with the same direction.

Verifies:
- Convergence requires exactly >=2 Q5 traders (not Q1-Q4)
- first_seen preserved across multiple detect runs
- FLAT positions (size=0) excluded from signals
- Resolved positions excluded from signals
- Separate signals for LONG vs SHORT on same market
- _compute_tier respects ACT thresholds + CLV-dominance gate
"""

import pytest
from datetime import datetime, timezone, timedelta

from polymarket_analytics.db.schema import init_database
from polymarket_analytics.detection.convergence import _compute_tier, detect_convergence
from polymarket_analytics.detection.writer import upsert_signal

# Import helpers from conftest
from tests.conftest import (
    create_q5_trader,
    create_qn_trader,
    create_position,
    create_market,
)


@pytest.fixture
def future_end_date():
    """Return a future end_date 30 days from now for open market tests."""
    return (
        (datetime.now(timezone.utc) + timedelta(days=30))
        .isoformat()
        .replace("+00:00", "Z")
    )


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


# Note: Helper functions (create_q5_trader, create_qn_trader, create_position, create_market)
# are defined in tests/conftest.py for reuse across test modules.


class TestConvergenceDetection:
    """Tests for convergence detection logic."""

    def test_convergence_detection_basic(
        self, detection_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test basic convergence detection with 2 Q5 traders on same market+direction.

        Fixture setup:
        - 2 Q5 traders (A, B) with positions on market_a, direction LONG
        - Both traders have lift_scores with quintile=5

        Expected:
        - detect_convergence returns 1 row with q5_count=2
        """
        db = detection_db

        # Setup: Create markets with future end_date (required for convergence query filter)
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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
        self, detection_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test that convergence requires quintile=5 traders only (not Q1-Q4).

        Fixture setup:
        - 2 Q3 traders (quintile=3) on same market+direction

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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
        self, detection_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test that convergence requires >=2 Q5 traders (single trader doesn't trigger).

        Fixture setup:
        - 1 Q5 trader on market

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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
        self, detection_db, fixture_traders, fixture_markets, future_end_date
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
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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
        self, detection_db, fixture_traders, fixture_markets, future_end_date
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
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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

class TestEdgeCases:
    """Edge case tests for convergence detection."""

    def test_detect_no_q5_traders(self, detection_db, fixture_markets, future_end_date):
        """Test detect_convergence handles zero Q5 traders gracefully.

        Fixture setup:
        - No lift_scores with quintile=5

        Expected:
        - detect_convergence returns empty DataFrame (no crash)
        """
        db = detection_db

        # Setup: Create market but NO traders
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

        # Act: Run convergence detection with no Q5 traders
        result_df = detect_convergence(db, "esports")

        # Assert: Returns empty DataFrame (no crash)
        assert len(result_df) == 0, (
            f"Expected 0 convergence signals for no Q5 traders, got {len(result_df)}"
        )

    def test_detect_all_positions_resolved(
        self, detection_db, fixture_traders, fixture_markets, future_end_date
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
        create_market(db, fixture_markets["market_a"], "esports", outcome="YES", end_date=future_end_date)

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
        self, detection_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test that FLAT (size=0) positions don't generate signals.

        Fixture setup:
        - 2 Q5 traders with FLAT positions (size=0)

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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

    def test_detect_niche_scoping(self, detection_db, fixture_traders, fixture_markets, future_end_date):
        """Test that convergence detection is scoped to niche.

        Fixture setup:
        - 2 Q5 traders in "politics" niche
        - Query for "esports" niche

        Expected:
        - detect_convergence returns empty DataFrame
        """
        db = detection_db

        # Setup: Create markets in different niches
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)
        create_market(db, fixture_markets["market_c"], "politics", None, end_date=future_end_date)

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

    def test_below_threshold_q5_excluded_from_convergence(
        self, detection_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Q5 traders with composite_score below threshold must not count toward convergence.

        Fixture: 2 traders above threshold + 1 trader with quintile=5 but composite_score=-0.20.
        All three hold positions on the same market/direction.
        Expected: q5_count=2, not 3 — the sub-threshold trader is invisible.
        """
        db = detection_db
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

        create_q5_trader(db, fixture_traders["q5_trader_a"], "esports", composite_score=0.5)
        create_q5_trader(db, fixture_traders["q5_trader_b"], "esports", composite_score=-0.05)
        create_qn_trader(db, fixture_traders["q3_trader"], "esports", quintile=5, composite_score=-0.20)

        for addr in (fixture_traders["q5_trader_a"], fixture_traders["q5_trader_b"], fixture_traders["q3_trader"]):
            create_position(db, addr, fixture_markets["market_a"], "LONG", size=100.0, resolved=False)

        result_df = detect_convergence(db, "esports")

        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"
        assert result_df.iloc[0]["q5_count"] == 2, (
            f"Expected q5_count=2 (sub-threshold trader excluded), got {result_df.iloc[0]['q5_count']}"
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
        self, detection_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test that q5_count counts distinct traders, not positions.

        Fixture setup:
        - 1 Q5 trader with 3 positions on same market (same direction)

        Expected:
        - detect_convergence returns empty DataFrame (q5_count=1, not >=2)
        """
        db = detection_db

        # Setup: Create market
        create_market(db, fixture_markets["market_a"], "esports", None, end_date=future_end_date)

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


class TestComputeTier:
    """Unit tests for _compute_tier — ACT/CONSIDER/WATCH thresholds + CLV gate."""

    def test_act_when_majority_clv_dominant(self):
        # 3 Q5, 2 CLV-dominant → not unanimous → ACT
        assert _compute_tier(net_q5_count=3, q5_count=3, clv_dominant_count=2) == "ACT"

    def test_demote_to_consider_when_all_clv_dominant(self):
        # 3 Q5, all 3 CLV-dominant → unanimous → demoted to CONSIDER
        assert _compute_tier(net_q5_count=3, q5_count=3, clv_dominant_count=3) == "CONSIDER"

    def test_act_with_zero_clv_dominant(self):
        # 4 Q5, 0 CLV-dominant → 0<4 → ACT (signal driven by ROI/Sharpe instead)
        assert _compute_tier(net_q5_count=4, q5_count=4, clv_dominant_count=0) == "ACT"

    def test_consider_when_net_below_act_threshold(self):
        # net_q5=2 → never ACT regardless of CLV mix
        assert _compute_tier(net_q5_count=2, q5_count=2, clv_dominant_count=0) == "CONSIDER"
        assert _compute_tier(net_q5_count=2, q5_count=2, clv_dominant_count=2) == "CONSIDER"

    def test_watch_below_consider_threshold(self):
        assert _compute_tier(net_q5_count=1, q5_count=1, clv_dominant_count=0) == "WATCH"
        assert _compute_tier(net_q5_count=0, q5_count=2, clv_dominant_count=2) == "WATCH"

    def test_act_when_q5_exceeds_net_due_to_opposing_cancellation(self):
        # q5=4 (after cancellation net=3 against opposing side); 3 of 4 CLV-dom → not unanimous → ACT
        assert _compute_tier(net_q5_count=3, q5_count=4, clv_dominant_count=3) == "ACT"

    def test_consider_when_all_q5_clv_dom_even_with_opposing_cancellation(self):
        # q5=4, all 4 CLV-dom → unanimous on the q5 axis → demoted regardless of net
        assert _compute_tier(net_q5_count=3, q5_count=4, clv_dominant_count=4) == "CONSIDER"
