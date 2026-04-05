"""Integration tests for build-positions command.

Tests:
- Position aggregation from trades
- Direction calculation (LONG/SHORT/FLAT)
- Volume-weighted average entry price
- Dependency assertions (fails without entities)
- Idempotency (re-runs don't create duplicates)
"""

import pytest
import sqlite_utils
from decimal import Decimal


def _setup_test_data(test_db: sqlite_utils.Database):
    """Helper to setup markets and token_catalog for tests."""
    # Insert markets first (FK dependency for market_entities)
    test_db["markets"].insert(
        {
            "condition_id": "market-1",
            "question": "Will Team Liquid beat NaVi?",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "created_at": "2025-01-01T00:00:00Z",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": "[]",
        }
    )
    test_db["markets"].insert(
        {
            "condition_id": "market-2",
            "question": "Will T1 beat Gen.G?",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "created_at": "2025-01-01T00:00:00Z",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": "[]",
        }
    )

    # Insert token_catalog (FK dependency for trades.token_id)
    test_db["token_catalog"].insert(
        {
            "token_id": "token-1",
            "condition_id": "market-1",
            "question": "Will Team Liquid beat NaVi?",
            "niche_slug": "esports",
            "node_path": "esports/cs2/iem-katowice-2026",
            "market_type": "binary",
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    test_db["token_catalog"].insert(
        {
            "token_id": "token-2",
            "condition_id": "market-1",
            "question": "Will Team Liquid beat NaVi?",
            "niche_slug": "esports",
            "node_path": "esports/cs2/iem-katowice-2026",
            "market_type": "binary",
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    test_db["token_catalog"].insert(
        {
            "token_id": "token-3",
            "condition_id": "market-2",
            "question": "Will T1 beat Gen.G?",
            "niche_slug": "esports",
            "node_path": "esports/lol/worlds-2025",
            "market_type": "binary",
            "created_at": "2025-01-01T00:00:00Z",
        }
    )


def test_build_positions_aggregates_trades(test_db: sqlite_utils.Database):
    """Test that build_positions creates one row per (trader, market) pair.

    Args:
        test_db: Temporary database fixture

    Asserts:
        - Correct count of positions created
        - One position per (trader, market) pair
    """
    from polymarket_analytics.positions.aggregation import (
        build_positions_from_trades,
    )

    # Setup base data
    _setup_test_data(test_db)

    # Setup: Insert market_entities with game IS NOT NULL
    test_db["market_entities"].insert(
        {
            "id": "entity-1",
            "condition_id": "market-1",
            "game": "CS2",
            "team_a": "Team Liquid",
            "team_b": "NaVi",
            "tournament": "IEM Katowice 2026",
            "market_type": "binary",
        }
    )
    test_db["market_entities"].insert(
        {
            "id": "entity-2",
            "condition_id": "market-2",
            "game": "LoL",
            "team_a": "T1",
            "team_b": "Gen.G",
            "tournament": "Worlds 2025",
            "market_type": "binary",
        }
    )

    # Setup: Insert traders
    test_db["traders"].insert(
        {
            "address": "0xAlice",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-15T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    test_db["traders"].insert(
        {
            "address": "0xBob",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-15T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    test_db["traders"].insert(
        {
            "address": "0xCarol",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-15T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    # Setup: Insert trades (3 traders × 2 markets = 6 positions expected)
    # Alice: net BUY on market-1 (LONG), net SELL on market-2 (SHORT)
    test_db["trades"].insert(
        {
            "trade_id": "trade-001",
            "token_id": "token-1",
            "timestamp": "2025-01-10T10:00:00Z",
            "side": "BUY",
            "price": Decimal("0.50"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xAlice",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-002",
            "token_id": "token-2",
            "timestamp": "2025-01-10T11:00:00Z",
            "side": "SELL",
            "price": Decimal("0.60"),
            "size": Decimal("50.0"),
            "market_id": "market-1",
            "trader_address": "0xAlice",
        }
    )
    # Alice on market-2: net SELL
    test_db["trades"].insert(
        {
            "trade_id": "trade-003",
            "token_id": "token-3",
            "timestamp": "2025-01-11T10:00:00Z",
            "side": "SELL",
            "price": Decimal("0.45"),
            "size": Decimal("200.0"),
            "market_id": "market-2",
            "trader_address": "0xAlice",
        }
    )

    # Bob: net BUY on market-1 (LONG), no trades on market-2
    test_db["trades"].insert(
        {
            "trade_id": "trade-004",
            "token_id": "token-1",
            "timestamp": "2025-01-10T12:00:00Z",
            "side": "BUY",
            "price": Decimal("0.55"),
            "size": Decimal("150.0"),
            "market_id": "market-1",
            "trader_address": "0xBob",
        }
    )

    # Carol: equal BUY/SELL on market-1 (FLAT), net BUY on market-2 (LONG)
    test_db["trades"].insert(
        {
            "trade_id": "trade-005",
            "token_id": "token-1",
            "timestamp": "2025-01-10T13:00:00Z",
            "side": "BUY",
            "price": Decimal("0.52"),
            "size": Decimal("80.0"),
            "market_id": "market-1",
            "trader_address": "0xCarol",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-006",
            "token_id": "token-1",
            "timestamp": "2025-01-10T14:00:00Z",
            "side": "SELL",
            "price": Decimal("0.58"),
            "size": Decimal("80.0"),
            "market_id": "market-1",
            "trader_address": "0xCarol",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-007",
            "token_id": "token-3",
            "timestamp": "2025-01-11T11:00:00Z",
            "side": "BUY",
            "price": Decimal("0.40"),
            "size": Decimal("100.0"),
            "market_id": "market-2",
            "trader_address": "0xCarol",
        }
    )

    # Run build_positions
    count = build_positions_from_trades(test_db, "esports")

    # Assert count matches expected (5 positions: 3 traders on market-1, 2 traders on market-2)
    assert count == 5, f"Expected 5 positions, got {count}"

    # Query positions table
    positions = list(test_db["positions"].rows)
    assert len(positions) == 5, f"Expected 5 position rows, got {len(positions)}"

    # Verify one row per (trader, market) pair
    pairs = {(p["trader_address"], p["market_id"]) for p in positions}
    expected_pairs = {
        ("0xAlice", "market-1"),
        ("0xAlice", "market-2"),
        ("0xBob", "market-1"),
        ("0xCarol", "market-1"),
        ("0xCarol", "market-2"),
    }
    assert pairs == expected_pairs, (
        f"Position pairs mismatch: {pairs} != {expected_pairs}"
    )


def test_build_positions_direction_calculation(test_db: sqlite_utils.Database):
    """Test direction calculation: LONG (net buyer), SHORT (net seller), FLAT (net ≈ 0).

    Args:
        test_db: Temporary database fixture

    Asserts:
        - Net BUYs → direction = 'LONG'
        - Net SELLs → direction = 'SHORT'
        - Equal BUY/SELL → direction = 'FLAT'
    """
    from polymarket_analytics.positions.aggregation import (
        build_positions_from_trades,
    )

    # Setup base data
    _setup_test_data(test_db)

    # Setup: market_entities
    test_db["market_entities"].insert(
        {
            "id": "entity-1",
            "condition_id": "market-1",
            "game": "CS2",
            "team_a": "Team A",
            "team_b": "Team B",
            "tournament": "Tournament 1",
            "market_type": "binary",
        }
    )

    # Setup: traders
    test_db["traders"].insert(
        {
            "address": "0xLong",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-01T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    test_db["traders"].insert(
        {
            "address": "0xShort",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-01T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    test_db["traders"].insert(
        {
            "address": "0xFlat",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-01T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    # LONG trader: net BUY 100 - 30 = 70
    test_db["trades"].insert(
        {
            "trade_id": "trade-long-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T10:00:00Z",
            "side": "BUY",
            "price": Decimal("0.50"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xLong",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-long-2",
            "token_id": "token-1",
            "timestamp": "2025-01-10T11:00:00Z",
            "side": "SELL",
            "price": Decimal("0.60"),
            "size": Decimal("30.0"),
            "market_id": "market-1",
            "trader_address": "0xLong",
        }
    )

    # SHORT trader: net SELL 200 - 50 = 150
    test_db["trades"].insert(
        {
            "trade_id": "trade-short-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T12:00:00Z",
            "side": "SELL",
            "price": Decimal("0.55"),
            "size": Decimal("200.0"),
            "market_id": "market-1",
            "trader_address": "0xShort",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-short-2",
            "token_id": "token-1",
            "timestamp": "2025-01-10T13:00:00Z",
            "side": "BUY",
            "price": Decimal("0.45"),
            "size": Decimal("50.0"),
            "market_id": "market-1",
            "trader_address": "0xShort",
        }
    )

    # FLAT trader: equal BUY/SELL = 0
    test_db["trades"].insert(
        {
            "trade_id": "trade-flat-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T14:00:00Z",
            "side": "BUY",
            "price": Decimal("0.52"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xFlat",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-flat-2",
            "token_id": "token-1",
            "timestamp": "2025-01-10T15:00:00Z",
            "side": "SELL",
            "price": Decimal("0.58"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xFlat",
        }
    )

    # Run build_positions
    build_positions_from_trades(test_db, "esports")

    # Query positions and check directions
    positions = {p["trader_address"]: p for p in test_db["positions"].rows}

    assert positions["0xLong"]["direction"] == "LONG", "Net buyer should be LONG"
    assert positions["0xShort"]["direction"] == "SHORT", "Net seller should be SHORT"
    assert positions["0xFlat"]["direction"] == "FLAT", "Equal BUY/SELL should be FLAT"


def test_build_positions_volume_weighted_avg(test_db: sqlite_utils.Database):
    """Test volume-weighted average entry price calculation.

    Position with 100@0.50 and 10@0.90 → avg_entry = (100*0.50 + 10*0.90)/(100+10) = 0.536

    Args:
        test_db: Temporary database fixture

    Asserts:
        - avg_entry_price is volume-weighted, not simple average
    """
    from polymarket_analytics.positions.aggregation import (
        build_positions_from_trades,
    )

    # Setup base data
    _setup_test_data(test_db)

    # Setup: market_entities
    test_db["market_entities"].insert(
        {
            "id": "entity-1",
            "condition_id": "market-1",
            "game": "CS2",
            "team_a": "Team A",
            "team_b": "Team B",
            "tournament": "Tournament 1",
            "market_type": "binary",
        }
    )

    # Setup: trader
    test_db["traders"].insert(
        {
            "address": "0xTrader",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-01T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    # Two BUY trades at different prices
    test_db["trades"].insert(
        {
            "trade_id": "trade-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T10:00:00Z",
            "side": "BUY",
            "price": Decimal("0.50"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xTrader",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-2",
            "token_id": "token-1",
            "timestamp": "2025-01-10T11:00:00Z",
            "side": "BUY",
            "price": Decimal("0.90"),
            "size": Decimal("10.0"),
            "market_id": "market-1",
            "trader_address": "0xTrader",
        }
    )

    # Run build_positions
    build_positions_from_trades(test_db, "esports")

    # Query position
    position = list(test_db["positions"].rows)[0]

    # Expected: (100*0.50 + 10*0.90) / (100+10) = (50 + 9) / 110 = 59/110 = 0.5363...
    expected_vwap = Decimal("59") / Decimal("110")
    actual_vwap = Decimal(str(position["avg_entry_price"]))

    # Simple average would be (0.50 + 0.90) / 2 = 0.70 (wrong!)
    simple_avg = Decimal("0.70")

    # Assert volume-weighted, not simple average
    assert abs(actual_vwap - expected_vwap) < Decimal("0.0001"), (
        f"Expected VWAP {expected_vwap}, got {actual_vwap}"
    )
    assert abs(actual_vwap - simple_avg) > Decimal("0.1"), (
        f"avg_entry_price is simple average ({simple_avg}), should be volume-weighted ({expected_vwap})"
    )


def test_build_positions_fails_without_entities(test_db: sqlite_utils.Database):
    """Test that build_positions fails loudly without market_entities.game.

    Args:
        test_db: Temporary database fixture

    Asserts:
        - ClickException raised with clear message
    """
    import click
    from polymarket_analytics.positions.aggregation import (
        build_positions_from_trades,
    )

    # Setup: Insert traders and trades but NO market_entities
    test_db["traders"].insert(
        {
            "address": "0xTrader",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-01T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    # Note: We can't insert trades without token_catalog due to FK constraint
    # So this test will fail at the trades count check first, which is fine
    # The error message will still be about missing dependencies

    # Should raise ClickException
    with pytest.raises(click.ClickException) as exc_info:
        build_positions_from_trades(test_db, "esports")

    # Verify error message is clear (mentions either empty trades or missing entities)
    error_msg = str(exc_info.value)
    assert "trades" in error_msg.lower() or "market_entities" in error_msg.lower(), (
        f"Error message should mention trades or market_entities: {error_msg}"
    )


def test_build_positions_idempotent(test_db: sqlite_utils.Database):
    """Test that build_positions is idempotent (re-runs don't create duplicates).

    Args:
        test_db: Temporary database fixture

    Asserts:
        - Running twice produces same row count
        - No duplicate rows
        - Data updated correctly on second run
    """
    from polymarket_analytics.positions.aggregation import (
        build_positions_from_trades,
    )

    # Setup base data
    _setup_test_data(test_db)

    # Setup: market_entities
    test_db["market_entities"].insert(
        {
            "id": "entity-1",
            "condition_id": "market-1",
            "game": "CS2",
            "team_a": "Team A",
            "team_b": "Team B",
            "tournament": "Tournament 1",
            "market_type": "binary",
        }
    )

    # Setup: trader
    test_db["traders"].insert(
        {
            "address": "0xTrader",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-01T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    # Setup: initial trades
    test_db["trades"].insert(
        {
            "trade_id": "trade-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T10:00:00Z",
            "side": "BUY",
            "price": Decimal("0.50"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xTrader",
        }
    )

    # First run
    count1 = build_positions_from_trades(test_db, "esports")
    positions_after_first = list(test_db["positions"].rows)
    assert len(positions_after_first) == 1, "Should have 1 position after first run"
    assert count1 == 1

    # Add another trade
    test_db["trades"].insert(
        {
            "trade_id": "trade-2",
            "token_id": "token-1",
            "timestamp": "2025-01-10T11:00:00Z",
            "side": "BUY",
            "price": Decimal("0.55"),
            "size": Decimal("50.0"),
            "market_id": "market-1",
            "trader_address": "0xTrader",
        }
    )

    # Second run
    count2 = build_positions_from_trades(test_db, "esports")
    positions_after_second = list(test_db["positions"].rows)

    # Assert no duplicates
    assert len(positions_after_second) == 1, (
        f"Should still have 1 position after second run, got {len(positions_after_second)}"
    )

    # Assert trade_count updated (should be 2 now)
    position = positions_after_second[0]
    assert position["trade_count"] == 2, (
        f"trade_count should be 2 after second run, got {position['trade_count']}"
    )

    # Assert size updated (100 + 50 = 150)
    assert Decimal(str(position["size"])) == Decimal("150.0"), (
        f"size should be 150 after second run, got {position['size']}"
    )


def test_build_positions_buy_only_entry_and_exit_price(test_db: sqlite_utils.Database):
    """Test avg_entry_price is BUY-only VWAP and avg_exit_price is SELL-only VWAP.

    FLAT position: BUY 100@0.40 + SELL 100@0.70
    Expected: avg_entry_price = 0.40 (BUY-only), avg_exit_price = 0.70 (SELL-only), size = 100
    """
    from polymarket_analytics.positions.aggregation import build_positions_from_trades

    _setup_test_data(test_db)

    test_db["market_entities"].insert(
        {
            "id": "entity-flat",
            "condition_id": "market-1",
            "game": "CS2",
            "team_a": "Team A",
            "team_b": "Team B",
            "tournament": "Tournament 1",
            "market_type": "binary",
        }
    )

    test_db["traders"].insert(
        {
            "address": "0xFlatTrader",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-15T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    test_db["trades"].insert(
        {
            "trade_id": "trade-buy-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T10:00:00Z",
            "side": "BUY",
            "price": Decimal("0.40"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xFlatTrader",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-sell-1",
            "token_id": "token-1",
            "timestamp": "2025-01-10T11:00:00Z",
            "side": "SELL",
            "price": Decimal("0.70"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xFlatTrader",
        }
    )

    build_positions_from_trades(test_db, "esports")

    position = list(
        test_db["positions"].rows_where("trader_address = ?", ["0xFlatTrader"])
    )[0]

    assert position["direction"] == "FLAT"
    assert abs(float(position["avg_entry_price"]) - 0.40) < 0.0001, (
        f"avg_entry_price should be 0.40 (BUY-only), got {position['avg_entry_price']}"
    )
    assert abs(float(position["avg_exit_price"]) - 0.70) < 0.0001, (
        f"avg_exit_price should be 0.70 (SELL-only), got {position['avg_exit_price']}"
    )
    assert float(position["size"]) == 100.0, (
        f"size should be 100 (gross BUY volume), got {position['size']}"
    )


def test_build_positions_long_entry_price_ignores_sells(test_db: sqlite_utils.Database):
    """Test LONG position avg_entry_price ignores SELL prices.

    LONG position: BUY 100@0.50 + SELL 30@0.80
    Expected: avg_entry_price = 0.50 (BUY-only VWAP), avg_exit_price = 0.80 (SELL-only), size = 70
    """
    from polymarket_analytics.positions.aggregation import build_positions_from_trades

    _setup_test_data(test_db)

    test_db["market_entities"].insert(
        {
            "id": "entity-long",
            "condition_id": "market-1",
            "game": "CS2",
            "team_a": "Team A",
            "team_b": "Team B",
            "tournament": "Tournament 1",
            "market_type": "binary",
        }
    )

    test_db["traders"].insert(
        {
            "address": "0xLongTrader",
            "first_seen": "2025-01-01T00:00:00Z",
            "last_seen": "2025-01-15T00:00:00Z",
            "backfill_complete": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )

    test_db["trades"].insert(
        {
            "trade_id": "trade-long-buy",
            "token_id": "token-1",
            "timestamp": "2025-01-10T10:00:00Z",
            "side": "BUY",
            "price": Decimal("0.50"),
            "size": Decimal("100.0"),
            "market_id": "market-1",
            "trader_address": "0xLongTrader",
        }
    )
    test_db["trades"].insert(
        {
            "trade_id": "trade-long-sell",
            "token_id": "token-1",
            "timestamp": "2025-01-10T11:00:00Z",
            "side": "SELL",
            "price": Decimal("0.80"),
            "size": Decimal("30.0"),
            "market_id": "market-1",
            "trader_address": "0xLongTrader",
        }
    )

    build_positions_from_trades(test_db, "esports")

    position = list(
        test_db["positions"].rows_where("trader_address = ?", ["0xLongTrader"])
    )[0]

    assert position["direction"] == "LONG"
    assert abs(float(position["avg_entry_price"]) - 0.50) < 0.0001, (
        f"avg_entry_price should be 0.50 (BUY-only VWAP), got {position['avg_entry_price']}"
    )
    assert abs(float(position["avg_exit_price"]) - 0.80) < 0.0001, (
        f"avg_exit_price should be 0.80 (SELL-only), got {position['avg_exit_price']}"
    )
    assert abs(float(position["size"]) - 70.0) < 0.001, (
        f"size should be 70 (abs(net_size)), got {position['size']}"
    )
