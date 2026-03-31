"""Integration tests for Polymarket Analytics token catalog and trades.

Tests:
- TCAT-03: Zero synthetic market_ids in trades table
- TCAT-04: classify_tokens CLI uses clobTokenIds from Gamma API
- Token catalog ingestion from fixtures
- Foreign key enforcement for orphan trades
"""

import pytest
import sqlite3
import sqlite_utils

from polymarket_analytics.token_catalog.builder import TokenCatalogBuilder


def test_token_catalog_ingestion(
    test_db: sqlite_utils.Database, sample_token_catalog: list[dict]
):
    """Test token catalog builder can ingest sample data.

    Args:
        test_db: Temporary database fixture
        sample_token_catalog: Sample token data fixture

    Asserts:
        - Correct count of entries inserted
        - All token_ids are queryable
    """
    builder = TokenCatalogBuilder(test_db)

    # Build from sample data (uses fixture path internally)
    count = builder.build(niche="esports")

    # Verify count matches sample data
    assert count == len(sample_token_catalog), (
        f"Expected {len(sample_token_catalog)} entries, got {count}"
    )

    # Verify all token_ids are queryable
    db_token_ids = {row["token_id"] for row in test_db["token_catalog"].rows}
    sample_token_ids = {token["token_id"] for token in sample_token_catalog}

    assert db_token_ids == sample_token_ids, (
        "Token IDs in database don't match sample data"
    )


def test_zero_synthetic_market_ids(
    test_db: sqlite_utils.Database, sample_token_catalog: list[dict]
):
    """TCAT-03: Integration test asserting zero synthetic market_ids in trades.

    This is the critical test that the token catalog prevents synthetic ID poisoning.
    All trades must reference valid token_ids that exist in the token_catalog table.

    Args:
        test_db: Temporary database fixture
        sample_token_catalog: Sample token data fixture

    Test flow:
        1. Ingest sample tokens into token_catalog
        2. Insert sample trades referencing those token_ids
        3. Run SQL LEFT JOIN to find orphan trades
        4. Assert count == 0 (zero synthetic IDs)
    """
    # Step 1: Ingest sample tokens into token_catalog
    builder = TokenCatalogBuilder(test_db)
    builder.build(niche="esports")

    # Step 2: Insert sample trades referencing valid token_ids
    sample_trades = [
        {
            "trade_id": "trade-001",
            "token_id": sample_token_catalog[0]["token_id"],
            "timestamp": "2025-01-15T10:00:00Z",
            "side": "YES",
            "price": 0.45,
            "size": 100.0,
            "market_id": sample_token_catalog[0]["condition_id"],
        },
        {
            "trade_id": "trade-002",
            "token_id": sample_token_catalog[1]["token_id"],
            "timestamp": "2025-01-15T11:00:00Z",
            "side": "NO",
            "price": 0.55,
            "size": 250.0,
            "market_id": sample_token_catalog[1]["condition_id"],
        },
        {
            "trade_id": "trade-003",
            "token_id": sample_token_catalog[2]["token_id"],
            "timestamp": "2025-01-15T12:00:00Z",
            "side": "YES",
            "price": 0.60,
            "size": 150.0,
            "market_id": sample_token_catalog[2]["condition_id"],
        },
    ]

    test_db["trades"].insert_all(sample_trades, pk="trade_id")

    # Step 3: Run SQL to find trades without matching token_catalog entries
    # This LEFT JOIN finds orphan trades (synthetic IDs)
    result = test_db.execute("""
        SELECT COUNT(*) as orphan_count
        FROM trades
        LEFT JOIN token_catalog ON trades.token_id = token_catalog.token_id
        WHERE token_catalog.token_id IS NULL
    """).fetchone()

    # Step 4: TCAT-03 assertion - zero synthetic IDs
    # sqlite3 returns tuple, access by index [0]
    orphan_count = result[0]
    assert orphan_count == 0, (
        f"TCAT-03 FAILED: Found {orphan_count} trades with synthetic token_ids"
    )


def test_foreign_key_enforcement(test_db: sqlite_utils.Database):
    """Test foreign key constraints prevent orphan trades.

    Attempts to insert a trade with a non-existent token_id.
    Should raise IntegrityError due to foreign key constraint.

    Args:
        test_db: Temporary database fixture

    Asserts:
        - Inserting trade with invalid token_id raises IntegrityError
        - PRAGMA foreign_keys = ON is working
    """
    # Attempt to insert trade with non-existent token_id
    invalid_trade = {
        "trade_id": "trade-invalid",
        "token_id": "0xnonexistent",
        "timestamp": "2025-01-15T10:00:00Z",
        "side": "YES",
        "price": 0.50,
        "size": 100.0,
        "market_id": "fake-market",
    }

    # Should raise IntegrityError due to FK constraint
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        test_db["trades"].insert(invalid_trade)

    # Verify the error is about foreign key constraint
    assert "FOREIGN KEY constraint failed" in str(exc_info.value), (
        f"Expected FK constraint error, got: {exc_info.value}"
    )


def test_schema_matches_guide(test_db: sqlite_utils.Database):
    """Verify all tables have columns required by GUIDE.md.

    This test fails immediately if schema diverges from GUIDE.md,
    preventing downstream runtime failures.

    Args:
        test_db: Temporary database fixture

    Asserts:
        - trades has trader_address for build-positions
        - markets has end_date for 30-day scoring window
        - market_entities has team_a/team_b (not team)
        - positions has outcome, trade_count, last_trade_timestamp
        - lift_scores has category, position_count, total_pnl, computed_at
        - gamma_events has outcome, end_date (not data JSON blob)
    """
    # trades must have trader_address for build-positions
    trades_cols = [col.name for col in test_db["trades"].columns]
    assert "trader_address" in trades_cols, "trades missing trader_address"

    # markets must have end_date for score 30-day window and event_slug for parent-child links
    markets_cols = [col.name for col in test_db["markets"].columns]
    assert "end_date" in markets_cols, "markets missing end_date"
    assert "event_slug" in markets_cols, "markets missing event_slug"

    # market_entities must have team_a/team_b (not team)
    entities_cols = [col.name for col in test_db["market_entities"].columns]
    assert "team_a" in entities_cols, "market_entities missing team_a"
    assert "team_b" in entities_cols, "market_entities missing team_b"
    assert "team" not in entities_cols, "market_entities should not have 'team' column"

    # positions must have outcome and trade_count
    positions_cols = [col.name for col in test_db["positions"].columns]
    assert "outcome" in positions_cols, "positions missing outcome"
    assert "trade_count" in positions_cols, "positions missing trade_count"
    assert "last_trade_timestamp" in positions_cols, (
        "positions missing last_trade_timestamp"
    )

    # lift_scores must have category, position_count, total_pnl, computed_at
    lift_cols = [col.name for col in test_db["lift_scores"].columns]
    assert "category" in lift_cols, "lift_scores missing category"
    assert "position_count" in lift_cols, "lift_scores missing position_count"
    assert "total_pnl" in lift_cols, "lift_scores missing total_pnl"
    assert "computed_at" in lift_cols, "lift_scores missing computed_at"

    # gamma_events must have normalized columns (not data JSON blob)
    gamma_cols = [col.name for col in test_db["gamma_events"].columns]
    assert "outcome" in gamma_cols, "gamma_events missing outcome"
    assert "end_date" in gamma_cols, "gamma_events missing end_date"
    assert "data" not in gamma_cols, "gamma_events should not have 'data' JSON blob"


def test_classify_tokens_uses_clob_token_ids(test_db: sqlite_utils.Database, tmp_path):
    """TCAT-04: classify_tokens CLI correctly reads clobTokenIds from Gamma API.

    This test mocks the Gamma API response with realistic clobTokenIds
    and asserts that the stored token IDs match (not synthetic fallback).

    Args:
        test_db: Temporary database fixture
        tmp_path: pytest tmp_path fixture for test database

    Asserts:
        - Token IDs in catalog match clobTokenIds from mock API
        - No synthetic token IDs generated when clobTokenIds present
    """
    from unittest.mock import AsyncMock, patch

    db_path = tmp_path / "test.db"

    # Initialize schema
    from polymarket_analytics.db.schema import init_database

    db = init_database(db_path)

    # Create markets table (dependency for classify_tokens)
    db["markets"].insert(
        {
            "condition_id": "0x123abc",
            "question": "Test market",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "created_at": "2025-01-01T00:00:00Z",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": "[]",
        },
        pk="condition_id",
    )

    # Mock Gamma API response with realistic clobTokenIds
    mock_market = {
        "conditionId": "0x123abc",
        "question": "Team A vs Team B",
        "outcomes": "YES,NO",
        "clobTokenIds": ["12345678901234567890", "98765432109876543210"],
        "category": "esports",
        "tags": [],
    }

    # Mock config object
    class MockConfig:
        slug = "esports"
        tag_id = 3001

    class MockContext:
        obj = {"config": MockConfig()}

    # Run classify_tokens with mocked API
    from polymarket_analytics.commands.classify_tokens import _classify_tokens_async

    async def run_test():
        with patch(
            "src.polymarket_analytics.api.gamma.GammaAPIClient.fetch_markets",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = [mock_market]
            await _classify_tokens_async(MockContext(), str(db_path))

    import asyncio

    asyncio.run(run_test())

    # Assert token IDs match clobTokenIds (not synthetic)
    stored_tokens = [row["token_id"] for row in db["token_catalog"].rows]

    expected_tokens = ["12345678901234567890", "98765432109876543210"]
    assert stored_tokens == expected_tokens, (
        f"Expected real token IDs {expected_tokens}, got {stored_tokens}"
    )

    # Assert no synthetic IDs were generated
    for token_id in stored_tokens:
        assert ":0" not in token_id and ":1" not in token_id, (
            f"Synthetic token ID found: {token_id}"
        )


def test_migration_adds_event_slug_to_existing_db(tmp_path):
    """Migration: init_database adds event_slug column to pre-existing markets table.

    Simulates upgrading a database created before event_slug was introduced.
    Without run_migrations(), the INSERT in ingest-events/discover would crash
    with 'table markets has no column named event_slug'.
    """
    from polymarket_analytics.db.schema import init_database

    db_path = tmp_path / "old.db"

    # Build old-schema markets table without event_slug
    old_db = sqlite_utils.Database(db_path)
    old_db["markets"].create(
        {
            "condition_id": str,
            "question": str,
            "outcome": str,
            "resolved": bool,
            "niche_slug": str,
            "created_at": str,
            "end_date": str,
            "category": str,
            "active": bool,
            "tokens": str,
        },
        pk="condition_id",
    )
    assert "event_slug" not in old_db["markets"].columns_dict

    # Run init_database — migration must add the column
    db = init_database(db_path)
    assert "event_slug" in db["markets"].columns_dict


def test_event_slug_stored_and_retrieved(test_db: sqlite_utils.Database):
    """event_slug is persisted to markets table and queryable."""
    test_db["markets"].insert(
        {
            "condition_id": "0xprop001",
            "question": "Total Kills Over/Under 34.5 in Game 1?",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "created_at": "2025-01-01T00:00:00Z",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": "[]",
            "event_slug": "faze-vs-navi-blast-spring-2025",
        },
        pk="condition_id",
    )
    row = test_db["markets"].get("0xprop001")
    assert row["event_slug"] == "faze-vs-navi-blast-spring-2025"


def test_event_slug_null_when_no_parent_event(test_db: sqlite_utils.Database):
    """event_slug is NULL for standalone markets with no events array."""
    test_db["markets"].insert(
        {
            "condition_id": "0xstandalone",
            "question": "Will FaZe win IEM Katowice 2025?",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "created_at": "2025-01-01T00:00:00Z",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": "[]",
            "event_slug": None,
        },
        pk="condition_id",
    )
    row = test_db["markets"].get("0xstandalone")
    assert row["event_slug"] is None


def test_event_slug_upsert_updates_existing_row(test_db: sqlite_utils.Database):
    """ON CONFLICT upsert correctly refreshes event_slug on re-ingestion."""
    base = {
        "condition_id": "0xupsert",
        "question": "Match winner?",
        "outcome": None,
        "resolved": False,
        "niche_slug": "esports",
        "created_at": "2025-01-01T00:00:00Z",
        "end_date": "2025-12-31T23:59:59Z",
        "category": "esports",
        "active": True,
        "tokens": "[]",
    }

    # First insert: no event_slug
    test_db.conn.execute(
        """
        INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug,
                             created_at, end_date, category, active, tokens, event_slug)
        VALUES (:condition_id, :question, :outcome, :resolved, :niche_slug,
                :created_at, :end_date, :category, :active, :tokens, :event_slug)
        ON CONFLICT(condition_id) DO UPDATE SET event_slug = excluded.event_slug
        """,
        {**base, "event_slug": None},
    )
    test_db.conn.commit()
    assert test_db["markets"].get("0xupsert")["event_slug"] is None

    # Second insert: event_slug now known
    test_db.conn.execute(
        """
        INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug,
                             created_at, end_date, category, active, tokens, event_slug)
        VALUES (:condition_id, :question, :outcome, :resolved, :niche_slug,
                :created_at, :end_date, :category, :active, :tokens, :event_slug)
        ON CONFLICT(condition_id) DO UPDATE SET event_slug = excluded.event_slug
        """,
        {**base, "event_slug": "faze-vs-navi-blast-spring-2025"},
    )
    test_db.conn.commit()
    assert (
        test_db["markets"].get("0xupsert")["event_slug"]
        == "faze-vs-navi-blast-spring-2025"
    )
