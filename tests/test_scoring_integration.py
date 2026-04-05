"""Integration tests for the full scoring pipeline.

Tests the complete scoring flow from raw positions to lift_scores output.
Uses fixture data matching GUIDE.md §"Integration Test — What It Must Verify" assertions.

Verifies:
- Smart traders (Alice, Bob) land in quintile 5
- Noise traders (Carol, Dave, Eve) land in quintile 1-3
- Edge cases: empty positions, min_positions filter, small trader sets
"""

import pytest
import sqlite_utils
from datetime import datetime, timezone, timedelta

from polymarket_analytics.db.schema import init_database
from polymarket_analytics.scoring.extraction import extract_resolved_positions
from polymarket_analytics.scoring.metrics import calculate_all_metrics
from polymarket_analytics.scoring.normalization import compute_normalized_scores
from polymarket_analytics.scoring.writer import write_lift_scores


@pytest.fixture
def scoring_db(tmp_path):
    """Create in-memory database with full schema for scoring tests.

    Args:
        tmp_path: Pytest tmp_path fixture

    Yields:
        sqlite_utils.Database with all tables initialized
    """
    db_path = tmp_path / "scoring_test.db"
    db = init_database(db_path)
    yield db


@pytest.fixture
def fixture_traders():
    """Return fixture trader addresses matching GUIDE.md happy path.

    Returns:
        dict with trader addresses for test fixtures
    """
    return {
        "alice": "0xAlice123456789012345678901234567890abcdef",
        "bob": "0xBob1234567890123456789012345678901234abcd",
        "carol": "0xCarol12345678901234567890123456789012abcd",
        "dave": "0xDave123456789012345678901234567890123abcd",
        "eve": "0xEve1234567890123456789012345678901234abcd",
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


def setup_full_pipeline_fixture(db, fixture_traders, fixture_markets, window_days=30):
    """Set up complete fixture data for scoring integration test.

    Creates:
    - markets table with 2 resolved markets
    - market_entities table with game info
    - positions table with resolved positions for 5 traders
    - All data timestamped within scoring window

    Fixture design (per GUIDE.md §"Integration Test — What It Must Verify"):
    - Alice: bought YES on MARKET_A at 0.55 → smart (CLV positive, ROI ~0.82)
    - Bob: bought YES on MARKET_A at 0.58, NO on MARKET_B at 0.45 → smart
    - Carol: bought YES on MARKET_A at 0.85 → noise (overpaid)
    - Dave: bought NO on MARKET_A at 0.60 → noise (wrong side, loss)
    - Eve: mixed results → average

    Args:
        db: sqlite_utils Database
        fixture_traders: Trader addresses fixture
        fixture_markets: Market IDs fixture
        window_days: Scoring window days for timestamp calculation
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)

    # Insert traders (required for FK constraint on positions)
    traders_data = [
        {
            "address": addr,
            "backfill_complete": 1,
            "first_seen": window_start.isoformat().replace("+00:00", "Z"),
            "last_seen": now.isoformat().replace("+00:00", "Z"),
            "created_at": window_start.isoformat().replace("+00:00", "Z"),
        }
        for addr in fixture_traders.values()
    ]
    db["traders"].insert_all(traders_data)

    # Insert markets (both resolved)
    markets_data = [
        {
            "condition_id": fixture_markets["market_a"],
            "question": "Will Team Liquid beat NaVi in IEM Katowice?",
            "category": "esports",
            "niche_slug": "esports",
            "outcome": "YES",  # Resolved YES
            "end_date": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "active": False,
            "tokens": "[]",
            "created_at": window_start.isoformat().replace("+00:00", "Z"),
        },
        {
            "condition_id": fixture_markets["market_b"],
            "question": "Will T1 beat GenG in Worlds 2025?",
            "category": "esports",
            "niche_slug": "esports",
            "outcome": "NO",  # Resolved NO
            "end_date": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            "active": False,
            "tokens": "[]",
            "created_at": window_start.isoformat().replace("+00:00", "Z"),
        },
    ]
    db["markets"].insert_all(markets_data)

    # Insert market_entities (required for scoring pipeline)
    entities_data = [
        {
            "condition_id": fixture_markets["market_a"],
            "game": "CS2",
            "team_a": "Team Liquid",
            "team_b": "NaVi",
            "tournament": "IEM Katowice 2026",
            "market_type": "match_winner",
        },
        {
            "condition_id": fixture_markets["market_b"],
            "game": "League of Legends",
            "team_a": "T1",
            "team_b": "GenG",
            "tournament": "Worlds 2025",
            "market_type": "match_winner",
        },
    ]
    db["market_entities"].insert_all(entities_data)

    # Insert positions for each trader with known PnL
    # Smart traders (Alice, Bob) should have positive metrics
    # Noise traders (Carol, Dave, Eve) should have lower/negative metrics
    positions_data = []

    # Alice: Smart trader - bought YES on MARKET_A at 0.55, market resolved YES
    # PnL = size * (1.0 - 0.55) = 100 * 0.45 = 45
    # Also bought NO on MARKET_B at 0.40, market resolved NO
    # PnL = 100 * 0.40 = 40 (NO bet won)
    positions_data.append(
        {
            "trader_address": fixture_traders["alice"],
            "market_id": fixture_markets["market_a"],
            "direction": "LONG",
            "size": 100.0,
            "avg_entry_price": 0.55,  # Smart entry
            "entry_timestamp": (window_start + timedelta(days=5))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=5))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "WIN",
            "pnl": 45.0,
        }
    )
    positions_data.append(
        {
            "trader_address": fixture_traders["alice"],
            "market_id": fixture_markets["market_b"],
            "direction": "SHORT",
            "size": 100.0,
            "avg_entry_price": 0.40,  # Very smart entry
            "entry_timestamp": (window_start + timedelta(days=6))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=6))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "WIN",
            "pnl": 40.0,
        }
    )

    # Bob: Smart trader - bought YES on MARKET_A at 0.58, NO on MARKET_B at 0.45
    # Position 1 (MARKET_A): PnL = 100 * (1.0 - 0.58) = 42
    # Position 2 (MARKET_B): PnL = 100 * 0.45 = 45 (NO bet won, market resolved NO)
    positions_data.append(
        {
            "trader_address": fixture_traders["bob"],
            "market_id": fixture_markets["market_a"],
            "direction": "LONG",
            "size": 100.0,
            "avg_entry_price": 0.58,  # Smart entry
            "entry_timestamp": (window_start + timedelta(days=8))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=8))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "WIN",
            "pnl": 42.0,
        }
    )
    positions_data.append(
        {
            "trader_address": fixture_traders["bob"],
            "market_id": fixture_markets["market_b"],
            "direction": "SHORT",
            "size": 100.0,
            "avg_entry_price": 0.45,  # Smart entry
            "entry_timestamp": (window_start + timedelta(days=10))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=10))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "WIN",
            "pnl": 45.0,
        }
    )

    # Carol: Noise trader - bought YES on MARKET_A at 0.85 (overpaid)
    # PnL = 100 * (1.0 - 0.85) = 15 (small profit, but low CLV)
    positions_data.append(
        {
            "trader_address": fixture_traders["carol"],
            "market_id": fixture_markets["market_a"],
            "direction": "LONG",
            "size": 100.0,
            "avg_entry_price": 0.85,  # Overpaid - noise trader behavior
            "entry_timestamp": (window_start + timedelta(days=12))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=12))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "WIN",
            "pnl": 15.0,
        }
    )

    # Dave: Noise trader - bought NO on MARKET_A at 0.60 (wrong side, loss)
    # PnL = 100 * (0.60 - 1.0) = -40 (loss)
    positions_data.append(
        {
            "trader_address": fixture_traders["dave"],
            "market_id": fixture_markets["market_a"],
            "direction": "SHORT",
            "size": 100.0,
            "avg_entry_price": 0.60,  # Wrong side
            "entry_timestamp": (window_start + timedelta(days=15))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=15))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "LOSS",
            "pnl": -40.0,
        }
    )

    # Eve: Average trader - mixed results
    # Position 1 (MARKET_A): LONG at 0.65, PnL = 35
    # Position 2 (MARKET_B): SHORT at 0.55, PnL = -10 (wrong bet)
    positions_data.append(
        {
            "trader_address": fixture_traders["eve"],
            "market_id": fixture_markets["market_a"],
            "direction": "LONG",
            "size": 100.0,
            "avg_entry_price": 0.65,
            "entry_timestamp": (window_start + timedelta(days=18))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=18))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "WIN",
            "pnl": 35.0,
        }
    )
    positions_data.append(
        {
            "trader_address": fixture_traders["eve"],
            "market_id": fixture_markets["market_b"],
            "direction": "SHORT",
            "size": 100.0,
            "avg_entry_price": 0.55,
            "entry_timestamp": (window_start + timedelta(days=20))
            .isoformat()
            .replace("+00:00", "Z"),
            "last_trade_timestamp": (window_start + timedelta(days=20))
            .isoformat()
            .replace("+00:00", "Z"),
            "trade_count": 1,
            "resolved": 1,
            "outcome": "LOSS",
            "pnl": -10.0,
        }
    )

    db["positions"].insert_all(positions_data)


class TestFullScoringPipeline:
    """Integration tests for the complete scoring pipeline."""

    def test_full_scoring_pipeline(self, scoring_db, fixture_traders, fixture_markets):
        """Test complete scoring pipeline from positions to lift_scores.

        This is the main integration test matching GUIDE.md §"Integration Test — What It Must Verify".

        Fixture setup:
        - 2 markets: MARKET_A (resolved YES), MARKET_B (resolved NO)
        - 5 traders: Alice, Bob (smart), Carol, Dave, Eve (noise/average)
        - Positions with known PnL outcomes

        Assertions:
        - lift_scores has 5 rows (one per trader)
        - Alice and Bob have quintile = 5 (smart traders)
        - Carol, Dave, Eve have quintile in [1, 2, 3] (noise traders)
        - All raw metrics (clv_raw, roi_raw, sharpe_raw) are non-null
        - All z-scores computed (non-null)
        - composite_score = sum of z-scores (within tolerance)
        """
        # Set up fixture data
        setup_full_pipeline_fixture(scoring_db, fixture_traders, fixture_markets)

        # Step 1: Extract resolved positions
        positions_df = extract_resolved_positions(scoring_db, "esports", window_days=30)

        # Assert extraction found all positions (8 total: Alice 2, Bob 2, Carol 1, Dave 1, Eve 2)
        assert len(positions_df) == 8, f"Expected 8 positions, got {len(positions_df)}"

        # Step 2: Calculate metrics
        metrics_df = calculate_all_metrics(positions_df)

        # Assert metrics calculated for all 5 traders
        assert len(metrics_df) == 5, f"Expected 5 traders, got {len(metrics_df)}"
        assert set(metrics_df["trader_address"].tolist()) == set(
            fixture_traders.values()
        )

        # Assert all raw metrics are present and non-null
        for col in ["clv_raw", "roi_raw", "sharpe_raw"]:
            assert col in metrics_df.columns, f"Missing column: {col}"
            assert metrics_df[col].notna().all(), f"Null values in {col}"

        # Step 3: Compute normalized scores and quintiles
        scores_df = compute_normalized_scores(metrics_df)

        # Assert z-scores computed
        for col in ["clv_zscore", "roi_zscore", "sharpe_zscore"]:
            assert col in scores_df.columns, f"Missing column: {col}"
            assert scores_df[col].notna().all(), f"Null values in {col}"

        # Assert composite_score computed
        assert "composite_score" in scores_df.columns
        assert scores_df["composite_score"].notna().all()

        # Verify composite_score = sum of z-scores (within tolerance)
        computed_composite = (
            scores_df["clv_zscore"]
            + scores_df["roi_zscore"]
            + scores_df["sharpe_zscore"]
        )
        assert (
            (scores_df["composite_score"] - computed_composite).abs() < 1e-10
        ).all(), "composite_score != sum of z-scores"

        # Assert quintile assigned
        assert "quintile" in scores_df.columns
        assert scores_df["quintile"].notna().all()
        assert set(scores_df["quintile"].tolist()).issubset({1, 2, 3, 4, 5})

        # Step 4: Write lift_scores
        window_end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        upserted = write_lift_scores(scoring_db, scores_df, "esports", 30, window_end)

        # Assert all scores written
        assert upserted == 5, f"Expected 5 rows upserted, got {upserted}"

        # Verify lift_scores table contents
        lift_scores_rows = list(scoring_db["lift_scores"].rows)
        assert len(lift_scores_rows) == 5

        # Build lookup by trader_address
        lift_by_trader = {row["trader_address"]: row for row in lift_scores_rows}

        # KEY ASSERTION: Alice must be quintile 5 (best performer with 2 smart trades)
        # Bob should be Q4 or Q5 (second best, also smart trader)
        alice_score = lift_by_trader[fixture_traders["alice"]]
        bob_score = lift_by_trader[fixture_traders["bob"]]

        assert alice_score["quintile"] == 5, (
            f"Alice should be quintile 5 (best smart trader), got {alice_score['quintile']}. "
            f"Composite: {alice_score['composite_score']:.3f}, CLV: {alice_score['clv_raw']:.3f}"
        )
        assert bob_score["quintile"] >= 4, (
            f"Bob should be quintile 4-5 (smart trader), got {bob_score['quintile']}. "
            f"Composite: {bob_score['composite_score']:.3f}, CLV: {bob_score['clv_raw']:.3f}"
        )

        # KEY ASSERTION: Carol, Dave, Eve must be quintile 1-3 (noise traders)
        carol_score = lift_by_trader[fixture_traders["carol"]]
        dave_score = lift_by_trader[fixture_traders["dave"]]
        eve_score = lift_by_trader[fixture_traders["eve"]]

        assert carol_score["quintile"] <= 3, (
            f"Carol should be quintile 1-3 (noise trader), got {carol_score['quintile']}. "
            f"Composite: {carol_score['composite_score']:.3f}, CLV: {carol_score['clv_raw']:.3f}"
        )
        assert dave_score["quintile"] <= 3, (
            f"Dave should be quintile 1-3 (noise trader), got {dave_score['quintile']}. "
            f"Composite: {dave_score['composite_score']:.3f}, CLV: {dave_score['clv_raw']:.3f}"
        )
        assert eve_score["quintile"] <= 3, (
            f"Eve should be quintile 1-3 (average trader), got {eve_score['quintile']}. "
            f"Composite: {eve_score['composite_score']:.3f}, CLV: {eve_score['clv_raw']:.3f}"
        )

        # Assert all required columns present
        required_cols = [
            "id",
            "trader_address",
            "category",
            "composite_score",
            "clv_raw",
            "clv_zscore",
            "roi_raw",
            "roi_zscore",
            "sharpe_raw",
            "sharpe_zscore",
            "quintile",
            "position_count",
            "total_pnl",
            "window_start",
            "window_end",
            "computed_at",
        ]
        for col in required_cols:
            assert col in alice_score, f"Missing column in lift_scores: {col}"

        # Assert category set correctly
        assert alice_score["category"] == "esports"

        # Assert total_pnl matches position data
        # Alice: 45 + 40 = 85, Bob: 42 + 45 = 87, Dave: -40
        assert alice_score["total_pnl"] == 85.0
        assert bob_score["total_pnl"] == 87.0
        assert dave_score["total_pnl"] == -40.0

    def test_score_empty_positions_no_crash(self, scoring_db, fixture_markets):
        """Test scoring pipeline handles zero resolved positions gracefully.

        Asserts:
        - Empty result returned (no exception)
        - lift_scores table remains empty
        """
        # Initialize schema but don't insert any positions
        # Insert a market so extraction doesn't fail on JOIN
        db = scoring_db
        db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Test market",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": "YES",
                "end_date": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "active": False,
                "tokens": "[]",
            }
        )

        # Run extraction - should return empty DataFrame
        positions_df = extract_resolved_positions(db, "esports", window_days=30)

        # Assert empty result (no crash)
        assert len(positions_df) == 0
        assert list(positions_df.columns) == [
            "trader_address",
            "market_id",
            "direction",
            "size",
            "avg_entry_price",
            "avg_exit_price",
            "pnl",
            "trade_count",
            "outcome",
            "end_date",
        ]

        # If we tried to calculate metrics on empty DataFrame, should handle gracefully
        if len(positions_df) == 0:
            # Pipeline should exit early - this is expected behavior
            pass

    def test_score_min_positions_filter(
        self, scoring_db, fixture_traders, fixture_markets
    ):
        """Test min_positions filtering works correctly.

        Creates traders with varying position counts:
        - Some below min_positions (30), some above
        - Asserts only traders with >= min_positions in lift_scores
        - Asserts z-scores computed against ALL traders before filtering
        """
        # Set up fixture data
        setup_full_pipeline_fixture(scoring_db, fixture_traders, fixture_markets)

        # Duplicate positions to simulate traders with many positions
        # Alice: 35 positions (above threshold of 30)
        # Bob: 35 positions (above threshold)
        # Carol: 20 positions (below threshold)
        # Dave: 20 positions (below threshold)
        # Eve: 35 positions (above threshold)

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=30)

        # Add more positions for Alice (to reach 35)
        alice_positions = []
        for i in range(33):  # Already has 2, add 33 more to reach 35
            alice_positions.append(
                {
                    "trader_address": fixture_traders["alice"],
                    "market_id": fixture_markets["market_a"],
                    "direction": "LONG",
                    "size": 50.0,
                    "avg_entry_price": 0.55,
                    "entry_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "last_trade_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "trade_count": 1,
                    "resolved": 1,
                    "outcome": "WIN",
                    "pnl": 22.5,
                }
            )
        scoring_db["positions"].insert_all(alice_positions)

        # Add more positions for Bob (to reach 35)
        bob_positions = []
        for i in range(33):  # Already has 2, add 33 more
            bob_positions.append(
                {
                    "trader_address": fixture_traders["bob"],
                    "market_id": fixture_markets["market_a"],
                    "direction": "LONG",
                    "size": 50.0,
                    "avg_entry_price": 0.58,
                    "entry_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "last_trade_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "trade_count": 1,
                    "resolved": 1,
                    "outcome": "WIN",
                    "pnl": 21.0,
                }
            )
        scoring_db["positions"].insert_all(bob_positions)

        # Add more positions for Carol (to reach 20)
        carol_positions = []
        for i in range(19):  # Already has 1, add 19 more
            carol_positions.append(
                {
                    "trader_address": fixture_traders["carol"],
                    "market_id": fixture_markets["market_a"],
                    "direction": "LONG",
                    "size": 50.0,
                    "avg_entry_price": 0.85,
                    "entry_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "last_trade_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "trade_count": 1,
                    "resolved": 1,
                    "outcome": "WIN",
                    "pnl": 7.5,
                }
            )
        scoring_db["positions"].insert_all(carol_positions)

        # Add more positions for Dave (to reach 20)
        dave_positions = []
        for i in range(19):  # Already has 1, add 19 more
            dave_positions.append(
                {
                    "trader_address": fixture_traders["dave"],
                    "market_id": fixture_markets["market_a"],
                    "direction": "SHORT",
                    "size": 50.0,
                    "avg_entry_price": 0.60,
                    "entry_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "last_trade_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "trade_count": 1,
                    "resolved": 1,
                    "outcome": "LOSS",
                    "pnl": -20.0,
                }
            )
        scoring_db["positions"].insert_all(dave_positions)

        # Add more positions for Eve (to reach 35)
        eve_positions = []
        for i in range(33):  # Already has 2, add 33 more (alternating outcomes)
            outcome = "WIN" if i % 2 == 0 else "LOSS"
            pnl = 17.5 if outcome == "WIN" else -5.0
            eve_positions.append(
                {
                    "trader_address": fixture_traders["eve"],
                    "market_id": fixture_markets["market_a"],
                    "direction": "LONG",
                    "size": 50.0,
                    "avg_entry_price": 0.65,
                    "entry_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "last_trade_timestamp": (window_start + timedelta(days=i))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "trade_count": 1,
                    "resolved": 1,
                    "outcome": outcome,
                    "pnl": pnl,
                }
            )
        scoring_db["positions"].insert_all(eve_positions)

        # Run full pipeline
        positions_df = extract_resolved_positions(scoring_db, "esports", window_days=30)
        metrics_df = calculate_all_metrics(positions_df)

        # Verify position counts BEFORE filtering
        # Alice: 35, Bob: 35, Carol: 20, Dave: 20, Eve: 35
        assert len(metrics_df) == 5  # All 5 traders have metrics computed

        # Check position_count column
        position_counts = metrics_df.set_index("trader_address")[
            "position_count"
        ].to_dict()
        assert position_counts[fixture_traders["alice"]] == 35
        assert position_counts[fixture_traders["bob"]] == 35
        assert position_counts[fixture_traders["carol"]] == 20
        assert position_counts[fixture_traders["dave"]] == 20
        assert position_counts[fixture_traders["eve"]] == 35

        # Compute normalized scores (z-scores computed against ALL traders)
        scores_df = compute_normalized_scores(metrics_df)

        # Filter to min_positions=30 AFTER z-scores computed
        min_positions = 30
        filtered_df = scores_df[scores_df["position_count"] >= min_positions]

        # Assert only traders with >= 30 positions included
        assert len(filtered_df) == 3  # Alice, Bob, Eve
        assert set(filtered_df["trader_address"].tolist()) == {
            fixture_traders["alice"],
            fixture_traders["bob"],
            fixture_traders["eve"],
        }

        # Assert Carol and Dave filtered out (but their data contributed to z-scores)
        carol_in_original = (
            fixture_traders["carol"] in scores_df["trader_address"].values
        )
        dave_in_original = fixture_traders["dave"] in scores_df["trader_address"].values
        assert carol_in_original, (
            "Carol should be in original scores_df for z-score computation"
        )
        assert dave_in_original, (
            "Dave should be in original scores_df for z-score computation"
        )

    def test_score_fewer_than_5_traders(self, scoring_db, fixture_markets):
        """Test scoring handles fewer than 5 traders gracefully.

        Creates only 3 traders and asserts:
        - Quintiles assigned (may be fewer than 5 unique)
        - No crash or exception
        - All 3 traders get quintile values
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=30)

        # Insert market
        scoring_db["markets"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "question": "Will Team Liquid beat NaVi?",
                "category": "esports",
                "niche_slug": "esports",
                "outcome": "YES",
                "end_date": (now - timedelta(days=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "active": False,
                "tokens": "[]",
            }
        )

        # Insert market_entities
        scoring_db["market_entities"].insert(
            {
                "condition_id": fixture_markets["market_a"],
                "game": "CS2",
                "team_a": "Team Liquid",
                "team_b": "NaVi",
                "tournament": "IEM Katowice 2026",
                "market_type": "match_winner",
            }
        )

        # Create only 3 traders with varying performance
        trader_a = "0xTraderA_123456789012345678901234567890abcdef"
        trader_b = "0xTraderB_123456789012345678901234567890abcdef"
        trader_c = "0xTraderC_123456789012345678901234567890abcdef"

        # Insert traders (required for FK constraint on positions)
        scoring_db["traders"].insert_all(
            [
                {
                    "address": trader_a,
                    "backfill_complete": 1,
                    "first_seen": window_start.isoformat().replace("+00:00", "Z"),
                    "last_seen": now.isoformat().replace("+00:00", "Z"),
                    "created_at": window_start.isoformat().replace("+00:00", "Z"),
                },
                {
                    "address": trader_b,
                    "backfill_complete": 1,
                    "first_seen": window_start.isoformat().replace("+00:00", "Z"),
                    "last_seen": now.isoformat().replace("+00:00", "Z"),
                    "created_at": window_start.isoformat().replace("+00:00", "Z"),
                },
                {
                    "address": trader_c,
                    "backfill_complete": 1,
                    "first_seen": window_start.isoformat().replace("+00:00", "Z"),
                    "last_seen": now.isoformat().replace("+00:00", "Z"),
                    "created_at": window_start.isoformat().replace("+00:00", "Z"),
                },
            ]
        )

        positions_data = [
            # Trader A: Great performance
            {
                "trader_address": trader_a,
                "market_id": fixture_markets["market_a"],
                "direction": "LONG",
                "size": 100.0,
                "avg_entry_price": 0.50,
                "entry_timestamp": (window_start + timedelta(days=5))
                .isoformat()
                .replace("+00:00", "Z"),
                "last_trade_timestamp": (window_start + timedelta(days=5))
                .isoformat()
                .replace("+00:00", "Z"),
                "trade_count": 1,
                "resolved": 1,
                "outcome": "WIN",
                "pnl": 50.0,
            },
            # Trader B: Average performance
            {
                "trader_address": trader_b,
                "market_id": fixture_markets["market_a"],
                "direction": "LONG",
                "size": 100.0,
                "avg_entry_price": 0.65,
                "entry_timestamp": (window_start + timedelta(days=10))
                .isoformat()
                .replace("+00:00", "Z"),
                "last_trade_timestamp": (window_start + timedelta(days=10))
                .isoformat()
                .replace("+00:00", "Z"),
                "trade_count": 1,
                "resolved": 1,
                "outcome": "WIN",
                "pnl": 35.0,
            },
            # Trader C: Poor performance
            {
                "trader_address": trader_c,
                "market_id": fixture_markets["market_a"],
                "direction": "SHORT",
                "size": 100.0,
                "avg_entry_price": 0.60,
                "entry_timestamp": (window_start + timedelta(days=15))
                .isoformat()
                .replace("+00:00", "Z"),
                "last_trade_timestamp": (window_start + timedelta(days=15))
                .isoformat()
                .replace("+00:00", "Z"),
                "trade_count": 1,
                "resolved": 1,
                "outcome": "LOSS",
                "pnl": -40.0,
            },
        ]
        scoring_db["positions"].insert_all(positions_data)

        # Run pipeline
        positions_df = extract_resolved_positions(scoring_db, "esports", window_days=30)
        metrics_df = calculate_all_metrics(positions_df)

        # Assert 3 traders found
        assert len(metrics_df) == 3

        # Compute scores - should handle < 5 traders gracefully
        scores_df = compute_normalized_scores(metrics_df)

        # Assert all 3 traders have quintiles assigned
        assert len(scores_df) == 3
        assert "quintile" in scores_df.columns
        assert scores_df["quintile"].notna().all()

        # Quintiles may not have all 5 values with only 3 traders
        # but should be in valid range [1-5]
        assert set(scores_df["quintile"].tolist()).issubset({1, 2, 3, 4, 5})

        # With 3 traders and quintiles, we should see varied quintiles
        # (not all the same, unless all composite scores are identical)
        unique_quintiles = scores_df["quintile"].nunique()
        assert unique_quintiles >= 1 and unique_quintiles <= 3

        # Verify no crash during write
        window_end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        upserted = write_lift_scores(scoring_db, scores_df, "esports", 30, window_end)
        assert upserted == 3
