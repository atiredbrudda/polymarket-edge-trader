"""Integration tests for signal enrichment (Phase 8).

Tests the enrichment fields added in Phase 8:
- clv_dominant_count: Count of Q5 traders with clv_zscore > 0
- avg_entry_price: Average entry price across converging traders
- min_entry_price: Minimum entry price across converging traders
- tier: WATCH / CONSIDER / ACT based on q5_count thresholds

Verifies:
- Schema migration adds all 4 new columns to signals table
- clv_dominant_count correctly counts only traders with positive clv_zscore
- tier thresholds (ACT >= 3, CONSIDER = 2, WATCH otherwise)
- avg_entry_price and min_entry_price reflect actual position prices
- All enriched fields survive round-trip through detect_convergence → upsert_signals_batch
- avg_score is retained on every upserted signal
"""

import pytest
from datetime import datetime, timezone, timedelta

from polymarket_analytics.db.schema import init_database
from polymarket_analytics.detection.convergence import detect_convergence
from polymarket_analytics.detection.writer import upsert_signal, upsert_signals_batch

# Import helpers from conftest
from tests.conftest import (
    create_q5_trader,
    create_position,
    _FIXED_COMPUTED_AT,
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
def enrichment_db(tmp_path):
    """Create in-memory database with full schema for enrichment tests.

    Args:
        tmp_path: Pytest tmp_path fixture

    Yields:
        sqlite_utils.Database with all tables initialized
    """
    db_path = tmp_path / "enrichment_test.db"
    db = init_database(db_path)
    yield db


@pytest.fixture
def fixture_traders():
    """Return fixture trader addresses for enrichment tests.

    Returns:
        dict with trader addresses for test fixtures
    """
    return {
        "q5_trader_a": "0xQ5TraderA_123456789012345678901234567890abcdef",
        "q5_trader_b": "0xQ5TraderB_123456789012345678901234567890abcdef",
        "q5_trader_c": "0xQ5TraderC_123456789012345678901234567890abcdef",
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
    }


class TestEnrichment:
    """Tests for Phase 8 enrichment fields."""

    def test_schema_columns_present(self, enrichment_db):
        """Test 1: signals table has all 4 new columns after init_database().

        Expected:
        - clv_dominant_count column exists
        - avg_entry_price column exists
        - min_entry_price column exists
        - tier column exists
        """
        db = enrichment_db

        # Get table schema
        columns = [col.name for col in db["signals"].columns]

        # Assert: All 4 new columns present
        assert "clv_dominant_count" in columns, (
            "clv_dominant_count column missing from signals table"
        )
        assert "avg_entry_price" in columns, (
            "avg_entry_price column missing from signals table"
        )
        assert "min_entry_price" in columns, (
            "min_entry_price column missing from signals table"
        )
        assert "tier" in columns, "tier column missing from signals table"

    def test_clv_dominant_count_positive_and_negative(
        self, enrichment_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test 2: clv_dominant_count=1 when one trader has clv_zscore>0 and one has clv_zscore<0.

        Fixture setup:
        - Trader A: Q5 with clv_zscore=1.5 (positive)
        - Trader B: Q5 with clv_zscore=-0.3 (negative)
        - Both LONG on same open market

        Expected:
        - detect_convergence returns clv_dominant_count == 1
        """
        db = enrichment_db

        # Setup: Create market with future end_date
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": future_end_date,
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Setup: Create trader A with positive clv_zscore
        db["traders"].insert(
            {
                "address": fixture_traders["q5_trader_a"],
                "backfill_complete": 1,
                "first_seen": _FIXED_COMPUTED_AT,
                "last_seen": _FIXED_COMPUTED_AT,
                "created_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )
        db["lift_scores"].insert(
            {
                "trader_address": fixture_traders["q5_trader_a"],
                "category": "esports",
                "composite_score": 1.5,
                "clv_raw": 0.5,
                "clv_zscore": 1.5,  # Positive
                "roi_raw": 0.3,
                "roi_zscore": 0.8,
                "sharpe_raw": 1.2,
                "sharpe_zscore": 0.7,
                "quintile": 5,
                "position_count": 10,
                "total_pnl": 500.0,
                "window_start": _FIXED_COMPUTED_AT,
                "window_end": _FIXED_COMPUTED_AT,
                "computed_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )

        # Setup: Create trader B with negative clv_zscore
        db["traders"].insert(
            {
                "address": fixture_traders["q5_trader_b"],
                "backfill_complete": 1,
                "first_seen": _FIXED_COMPUTED_AT,
                "last_seen": _FIXED_COMPUTED_AT,
                "created_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )
        db["lift_scores"].insert(
            {
                "trader_address": fixture_traders["q5_trader_b"],
                "category": "esports",
                "composite_score": 1.2,
                "clv_raw": -0.2,
                "clv_zscore": -0.3,  # Negative
                "roi_raw": 0.1,
                "roi_zscore": 0.2,
                "sharpe_raw": 0.5,
                "sharpe_zscore": 0.3,
                "quintile": 5,
                "position_count": 8,
                "total_pnl": 200.0,
                "window_start": _FIXED_COMPUTED_AT,
                "window_end": _FIXED_COMPUTED_AT,
                "computed_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )

        # Setup: Create positions for both traders
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
        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"

        # Assert: clv_dominant_count == 1 (only trader A has positive clv_zscore)
        row = result_df.iloc[0]
        assert row["clv_dominant_count"] == 1, (
            f"Expected clv_dominant_count=1, got {row['clv_dominant_count']}"
        )

    def test_clv_dominant_count_all_negative(
        self, enrichment_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test 3: clv_dominant_count=0 when all Q5 traders have clv_zscore<0.

        Fixture setup:
        - Trader A: Q5 with clv_zscore=-0.5 (negative)
        - Trader B: Q5 with clv_zscore=-0.3 (negative)
        - Both LONG on same open market

        Expected:
        - detect_convergence returns clv_dominant_count == 0
        """
        db = enrichment_db

        # Setup: Create market with future end_date
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": future_end_date,
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Setup: Create trader A with negative clv_zscore
        db["traders"].insert(
            {
                "address": fixture_traders["q5_trader_a"],
                "backfill_complete": 1,
                "first_seen": _FIXED_COMPUTED_AT,
                "last_seen": _FIXED_COMPUTED_AT,
                "created_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )
        db["lift_scores"].insert(
            {
                "trader_address": fixture_traders["q5_trader_a"],
                "category": "esports",
                "composite_score": 1.5,
                "clv_raw": -0.3,
                "clv_zscore": -0.5,  # Negative
                "roi_raw": 0.2,
                "roi_zscore": 0.4,
                "sharpe_raw": 0.8,
                "sharpe_zscore": 0.5,
                "quintile": 5,
                "position_count": 10,
                "total_pnl": 300.0,
                "window_start": _FIXED_COMPUTED_AT,
                "window_end": _FIXED_COMPUTED_AT,
                "computed_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )

        # Setup: Create trader B with negative clv_zscore
        db["traders"].insert(
            {
                "address": fixture_traders["q5_trader_b"],
                "backfill_complete": 1,
                "first_seen": _FIXED_COMPUTED_AT,
                "last_seen": _FIXED_COMPUTED_AT,
                "created_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )
        db["lift_scores"].insert(
            {
                "trader_address": fixture_traders["q5_trader_b"],
                "category": "esports",
                "composite_score": 1.2,
                "clv_raw": -0.2,
                "clv_zscore": -0.3,  # Negative
                "roi_raw": 0.1,
                "roi_zscore": 0.2,
                "sharpe_raw": 0.5,
                "sharpe_zscore": 0.3,
                "quintile": 5,
                "position_count": 8,
                "total_pnl": 200.0,
                "window_start": _FIXED_COMPUTED_AT,
                "window_end": _FIXED_COMPUTED_AT,
                "computed_at": _FIXED_COMPUTED_AT,
            },
            replace=True,
        )

        # Setup: Create positions for both traders
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
        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"

        # Assert: clv_dominant_count == 0 (all traders have negative clv_zscore)
        row = result_df.iloc[0]
        assert row["clv_dominant_count"] == 0, (
            f"Expected clv_dominant_count=0, got {row['clv_dominant_count']}"
        )

    def test_tier_consider(
        self, enrichment_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test 4: tier = CONSIDER when q5_count = 2.

        Fixture setup:
        - 2 Q5 traders LONG on same open market

        Expected:
        - detect_convergence returns tier == 'CONSIDER'
        """
        db = enrichment_db

        # Setup: Create market with future end_date
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": future_end_date,
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Setup: Create 2 Q5 traders
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )

        # Setup: Create positions for both traders
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
        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"

        # Assert: tier == 'CONSIDER'
        row = result_df.iloc[0]
        assert row["tier"] == "CONSIDER", f"Expected tier='CONSIDER', got {row['tier']}"
        assert row["q5_count"] == 2, f"Expected q5_count=2, got {row['q5_count']}"

    def test_tier_act(
        self, enrichment_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test 5: tier = ACT when q5_count >= 3.

        Fixture setup:
        - 3 Q5 traders LONG on same open market

        Expected:
        - detect_convergence returns tier == 'ACT'
        """
        db = enrichment_db

        # Setup: Create market with future end_date
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": future_end_date,
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Setup: Create 3 Q5 traders
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_c"], "esports", composite_score=1.0
        )

        # Setup: Create positions for all 3 traders
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
        create_position(
            db,
            fixture_traders["q5_trader_c"],
            fixture_markets["market_a"],
            "LONG",
            size=75.0,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: 1 convergence signal found
        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"

        # Assert: tier == 'ACT'
        row = result_df.iloc[0]
        assert row["tier"] == "ACT", f"Expected tier='ACT', got {row['tier']}"
        assert row["q5_count"] == 3, f"Expected q5_count=3, got {row['q5_count']}"

    def test_entry_prices(
        self, enrichment_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test 6: avg_entry_price and min_entry_price reflect actual position prices.

        Fixture setup:
        - Trader A: avg_entry_price=0.30
        - Trader B: avg_entry_price=0.50

        Expected:
        - detect_convergence returns:
          - avg_entry_price == 0.40 (average of 0.30 and 0.50)
          - min_entry_price == 0.30 (minimum of the two)
        """
        db = enrichment_db

        # Setup: Create market with future end_date
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": future_end_date,
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Setup: Create 2 Q5 traders
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )

        # Setup: Create positions with different entry prices
        create_position(
            db,
            fixture_traders["q5_trader_a"],
            fixture_markets["market_a"],
            "LONG",
            size=100.0,
            avg_entry_price=0.30,
            resolved=False,
        )
        create_position(
            db,
            fixture_traders["q5_trader_b"],
            fixture_markets["market_a"],
            "LONG",
            size=50.0,
            avg_entry_price=0.50,
            resolved=False,
        )

        # Act: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert: 1 convergence signal found
        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"

        # Assert: Entry prices are correct
        row = result_df.iloc[0]
        assert abs(row["avg_entry_price"] - 0.40) < 0.001, (
            f"Expected avg_entry_price=0.40, got {row['avg_entry_price']}"
        )
        assert abs(row["min_entry_price"] - 0.30) < 0.001, (
            f"Expected min_entry_price=0.30, got {row['min_entry_price']}"
        )

    def test_upsert_signal_all_fields(self, enrichment_db, fixture_markets):
        """Test 7: upsert_signal persists all 4 new fields + avg_score retained.

        Fixture setup:
        - Call upsert_signal with all 4 new params

        Expected:
        - All 4 fields readable from signals table
        - avg_score also present and correct (retention check)
        """
        db = enrichment_db

        # Setup: Create market (needed for foreign key)
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": (datetime.now(timezone.utc) + timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Act: Insert signal with all 4 new fields
        first_seen = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        last_updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        upsert_signal(
            db=db,
            market_id=fixture_markets["market_a"],
            direction="LONG",
            q5_count=2,
            avg_score=1.25,
            first_seen=first_seen,
            last_updated=last_updated,
            clv_dominant_count=1,
            avg_entry_price=0.40,
            min_entry_price=0.30,
            tier="CONSIDER",
        )

        # Assert: Read back from signals table
        rows = list(
            db.query(
                """
                SELECT clv_dominant_count, avg_entry_price, min_entry_price, tier, avg_score
                FROM signals
                WHERE market_id = :market_id AND direction = :direction
                """,
                {"market_id": fixture_markets["market_a"], "direction": "LONG"},
            )
        )

        assert len(rows) == 1, "Expected 1 signal record"
        signal = rows[0]

        # Assert: All 4 new fields have correct values
        assert signal["clv_dominant_count"] == 1, (
            f"Expected clv_dominant_count=1, got {signal['clv_dominant_count']}"
        )
        assert abs(signal["avg_entry_price"] - 0.40) < 0.001, (
            f"Expected avg_entry_price=0.40, got {signal['avg_entry_price']}"
        )
        assert abs(signal["min_entry_price"] - 0.30) < 0.001, (
            f"Expected min_entry_price=0.30, got {signal['min_entry_price']}"
        )
        assert signal["tier"] == "CONSIDER", (
            f"Expected tier='CONSIDER', got {signal['tier']}"
        )

        # Assert: avg_score retained (ENRC-09)
        assert abs(signal["avg_score"] - 1.25) < 0.001, (
            f"Expected avg_score=1.25, got {signal['avg_score']}"
        )

    def test_full_round_trip(
        self, enrichment_db, fixture_traders, fixture_markets, future_end_date
    ):
        """Test 8: full round-trip detect_convergence → upsert_signals_batch → signals table.

        Fixture setup:
        - 2 Q5 traders LONG on open market (same as Test 4)

        Expected:
        - detect_convergence returns signal with all enriched fields
        - upsert_signals_batch persists all fields
        - signals table has all fields populated
        - avg_score present and non-null (ENRC-09)
        """
        db = enrichment_db

        # Setup: Create market with future end_date
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": future_end_date,
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Setup: Create 2 Q5 traders
        create_q5_trader(
            db, fixture_traders["q5_trader_a"], "esports", composite_score=1.5
        )
        create_q5_trader(
            db, fixture_traders["q5_trader_b"], "esports", composite_score=1.2
        )

        # Setup: Create positions
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

        # Act 1: Run convergence detection
        result_df = detect_convergence(db, "esports")

        # Assert 1: Convergence detected with enriched fields
        assert len(result_df) == 1, f"Expected 1 signal, got {len(result_df)}"
        row = result_df.iloc[0]
        assert row["q5_count"] == 2
        assert row["tier"] == "CONSIDER"
        assert "clv_dominant_count" in row
        assert "avg_entry_price" in row
        assert "min_entry_price" in row

        # Act 2: Upsert signals batch
        count = upsert_signals_batch(db, result_df, "esports")

        # Assert 2: One signal upserted
        assert count == 1, f"Expected 1 signal upserted, got {count}"

        # Act 3: Read back from signals table
        rows = list(
            db.query(
                """
                SELECT clv_dominant_count, avg_entry_price, min_entry_price, tier, avg_score
                FROM signals
                WHERE market_id = :market_id AND direction = :direction
                """,
                {"market_id": fixture_markets["market_a"], "direction": "LONG"},
            )
        )

        # Assert 3: All fields present and populated
        assert len(rows) == 1, "Expected 1 signal record"
        signal = rows[0]

        assert signal["clv_dominant_count"] is not None, (
            "clv_dominant_count should be populated"
        )
        assert signal["avg_entry_price"] is not None, (
            "avg_entry_price should be populated"
        )
        assert signal["min_entry_price"] is not None, (
            "min_entry_price should be populated"
        )
        assert signal["tier"] is not None, "tier should be populated"
        assert signal["avg_score"] is not None, "avg_score should be retained (ENRC-09)"
        assert signal["avg_score"] > 0, "avg_score should be positive"

    def test_upsert_update_preserves_first_seen(self, enrichment_db, fixture_markets):
        """Test 9: upsert update overwrites tier and new fields, preserves first_seen.

        Fixture setup:
        - Insert signal with tier='CONSIDER'
        - Update via upsert_signal with tier='ACT'

        Expected:
        - tier changed to 'ACT'
        - first_seen unchanged
        - All enriched fields updated
        """
        db = enrichment_db

        # Setup: Create market (needed for foreign key)
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": None,
                "end_date": (datetime.now(timezone.utc) + timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
                "active": 1,
                "tokens": "[]",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            replace=True,
        )

        # Act 1: Insert initial signal with tier='CONSIDER'
        first_seen = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        last_updated_1 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        upsert_signal(
            db=db,
            market_id=fixture_markets["market_a"],
            direction="LONG",
            q5_count=2,
            avg_score=1.25,
            first_seen=first_seen,
            last_updated=last_updated_1,
            clv_dominant_count=1,
            avg_entry_price=0.40,
            min_entry_price=0.30,
            tier="CONSIDER",
        )

        # Wait briefly
        import time

        time.sleep(0.1)

        # Act 2: Update signal with new tier and fields
        last_updated_2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        upsert_signal(
            db=db,
            market_id=fixture_markets["market_a"],
            direction="LONG",
            q5_count=3,  # Changed
            avg_score=1.35,  # Changed
            first_seen=last_updated_2,  # Should be IGNORED
            last_updated=last_updated_2,
            clv_dominant_count=2,  # Changed
            avg_entry_price=0.45,  # Changed
            min_entry_price=0.35,  # Changed
            tier="ACT",  # Changed
        )

        # Assert: Read back from signals table
        rows = list(
            db.query(
                """
                SELECT id, first_seen, q5_count, avg_score, clv_dominant_count,
                       avg_entry_price, min_entry_price, tier
                FROM signals
                WHERE market_id = :market_id AND direction = :direction
                """,
                {"market_id": fixture_markets["market_a"], "direction": "LONG"},
            )
        )

        assert len(rows) == 1, "Expected 1 signal record"
        signal = rows[0]

        # Assert: first_seen preserved from original insert
        assert signal["first_seen"] == first_seen, (
            f"first_seen should be preserved: expected {first_seen}, got {signal['first_seen']}"
        )

        # Assert: Fields updated
        assert signal["q5_count"] == 3, f"Expected q5_count=3, got {signal['q5_count']}"
        assert abs(signal["avg_score"] - 1.35) < 0.001, (
            f"Expected avg_score=1.35, got {signal['avg_score']}"
        )
        assert signal["clv_dominant_count"] == 2, (
            f"Expected clv_dominant_count=2, got {signal['clv_dominant_count']}"
        )
        assert abs(signal["avg_entry_price"] - 0.45) < 0.001, (
            f"Expected avg_entry_price=0.45, got {signal['avg_entry_price']}"
        )
        assert abs(signal["min_entry_price"] - 0.35) < 0.001, (
            f"Expected min_entry_price=0.35, got {signal['min_entry_price']}"
        )
        assert signal["tier"] == "ACT", f"Expected tier='ACT', got {signal['tier']}"
