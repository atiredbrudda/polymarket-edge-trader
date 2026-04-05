"""Integration tests for resolve-positions command.

Tests:
- PnL formulas for all 4 direction/outcome combinations (LONG+YES, LONG+NO, SHORT+NO, SHORT+YES)
- FLAT positions have pnl = 0
- Python helper calculate_pnl() matches SQL formula
- Skips unresolved markets (markets without outcome)
- Idempotency (re-runs don't re-resolve already resolved positions)
- Fails loudly if no market outcomes exist
"""

import pytest
import sqlite_utils
from decimal import Decimal

from polymarket_analytics.db.schema import init_database


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
def resolved_positions_db(test_db):
    """Fixture with unresolved positions and markets with outcomes.

    Creates:
    - Markets with outcomes (YES/NO)
    - Unresolved positions with various directions

    Args:
        test_db: Base database fixture

    Returns:
        Database with fixture data
    """
    # Insert markets with outcomes
    test_db["markets"].insert_all(
        [
            {
                "condition_id": "market-yes",
                "question": "Will Team Liquid win?",
                "outcome": "YES",
                "resolved": True,
                "niche_slug": "esports",
                "created_at": "2025-01-01T00:00:00Z",
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": False,
                "tokens": "[]",
            },
            {
                "condition_id": "market-no",
                "question": "Will T1 win?",
                "outcome": "NO",
                "resolved": True,
                "niche_slug": "esports",
                "created_at": "2025-01-01T00:00:00Z",
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": False,
                "tokens": "[]",
            },
            {
                "condition_id": "market-no-outcome",
                "question": "Will Gen.G win?",
                "outcome": None,
                "resolved": False,
                "niche_slug": "esports",
                "created_at": "2025-01-01T00:00:00Z",
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": True,
                "tokens": "[]",
            },
        ]
    )

    # Insert unresolved positions with various directions
    # Using hash-based IDs for determinism
    import hashlib

    def make_id(trader: str, market: str) -> str:
        return hashlib.sha256(f"{trader}{market}".encode()).hexdigest()[:16]

    test_db["positions"].insert_all(
        [
            # LONG + YES → WIN, pnl = 100 * (1.0 - 0.60) = 40.0
            {
                "id": make_id("trader1", "market-yes"),
                "trader_address": "trader1",
                "market_id": "market-yes",
                "direction": "LONG",
                "size": 100,
                "avg_entry_price": 0.60,
                "entry_timestamp": "2025-01-01T00:00:00Z",
                "last_trade_timestamp": "2025-01-02T00:00:00Z",
                "trade_count": 1,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
            # LONG + NO → LOSS, pnl = 100 * (0.0 - 0.60) = -60.0
            {
                "id": make_id("trader2", "market-no"),
                "trader_address": "trader2",
                "market_id": "market-no",
                "direction": "LONG",
                "size": 100,
                "avg_entry_price": 0.60,
                "entry_timestamp": "2025-01-01T00:00:00Z",
                "last_trade_timestamp": "2025-01-02T00:00:00Z",
                "trade_count": 1,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
            # SHORT + NO → WIN, pnl = 100 * 0.60 = 60.0
            {
                "id": make_id("trader3", "market-no"),
                "trader_address": "trader3",
                "market_id": "market-no",
                "direction": "SHORT",
                "size": 100,
                "avg_entry_price": 0.60,
                "entry_timestamp": "2025-01-01T00:00:00Z",
                "last_trade_timestamp": "2025-01-02T00:00:00Z",
                "trade_count": 1,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
            # SHORT + YES → LOSS, pnl = 100 * (0.60 - 1.0) = -40.0
            {
                "id": make_id("trader4", "market-yes"),
                "trader_address": "trader4",
                "market_id": "market-yes",
                "direction": "SHORT",
                "size": 100,
                "avg_entry_price": 0.60,
                "entry_timestamp": "2025-01-01T00:00:00Z",
                "last_trade_timestamp": "2025-01-02T00:00:00Z",
                "trade_count": 1,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
            # FLAT → FLAT, pnl = 0
            {
                "id": make_id("trader5", "market-yes"),
                "trader_address": "trader5",
                "market_id": "market-yes",
                "direction": "FLAT",
                "size": 0,
                "avg_entry_price": 0.50,
                "entry_timestamp": "2025-01-01T00:00:00Z",
                "last_trade_timestamp": "2025-01-02T00:00:00Z",
                "trade_count": 0,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
            # Position for market without outcome (should NOT be resolved)
            {
                "id": make_id("trader6", "market-no-outcome"),
                "trader_address": "trader6",
                "market_id": "market-no-outcome",
                "direction": "LONG",
                "size": 50,
                "avg_entry_price": 0.55,
                "entry_timestamp": "2025-01-01T00:00:00Z",
                "last_trade_timestamp": "2025-01-02T00:00:00Z",
                "trade_count": 1,
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            },
        ]
    )

    return test_db


def test_resolve_pnl_formulas(resolved_positions_db):
    """Test all 4 PnL formula combinations.

    Verifies:
    - LONG + YES: size * (1.0 - entry) = WIN
    - LONG + NO: size * (0.0 - entry) = LOSS
    - SHORT + NO: size * entry = WIN
    - SHORT + YES: size * (entry - 1.0) = LOSS
    - FLAT: pnl = 0

    Args:
        resolved_positions_db: Database with fixture data
    """
    from polymarket_analytics.positions.resolution import resolve_position_pnl

    # Run resolution
    count = resolve_position_pnl(resolved_positions_db, "esports")

    # Should resolve 5 positions (not the one without market outcome)
    assert count == 5, f"Expected 5 positions resolved, got {count}"

    # Verify LONG + YES → WIN, pnl = 40.0
    row = resolved_positions_db.execute(
        "SELECT outcome, pnl FROM positions WHERE trader_address = 'trader1'"
    ).fetchone()
    assert row[0] == "WIN", f"Expected WIN, got {row[0]}"
    assert abs(float(row[1]) - 40.0) < 0.001, f"Expected pnl 40.0, got {row[1]}"

    # Verify LONG + NO → LOSS, pnl = -60.0
    row = resolved_positions_db.execute(
        "SELECT outcome, pnl FROM positions WHERE trader_address = 'trader2'"
    ).fetchone()
    assert row[0] == "LOSS", f"Expected LOSS, got {row[0]}"
    assert abs(float(row[1]) - (-60.0)) < 0.001, f"Expected pnl -60.0, got {row[1]}"

    # Verify SHORT + NO → WIN, pnl = 60.0
    row = resolved_positions_db.execute(
        "SELECT outcome, pnl FROM positions WHERE trader_address = 'trader3'"
    ).fetchone()
    assert row[0] == "WIN", f"Expected WIN, got {row[0]}"
    assert abs(float(row[1]) - 60.0) < 0.001, f"Expected pnl 60.0, got {row[1]}"

    # Verify SHORT + YES → LOSS, pnl = -40.0
    row = resolved_positions_db.execute(
        "SELECT outcome, pnl FROM positions WHERE trader_address = 'trader4'"
    ).fetchone()
    assert row[0] == "LOSS", f"Expected LOSS, got {row[0]}"
    assert abs(float(row[1]) - (-40.0)) < 0.001, f"Expected pnl -40.0, got {row[1]}"

    # Verify FLAT → FLAT, pnl = 0
    row = resolved_positions_db.execute(
        "SELECT outcome, pnl FROM positions WHERE trader_address = 'trader5'"
    ).fetchone()
    assert row[0] == "FLAT", f"Expected FLAT, got {row[0]}"
    assert abs(float(row[1]) - 0.0) < 0.001, f"Expected pnl 0, got {row[1]}"


def test_resolve_position_pnl_function():
    """Test Python helper calculate_pnl() matches SQL formula.

    Verifies pure Python implementation produces same results as SQL.
    """
    from polymarket_analytics.positions.resolution import calculate_pnl

    # LONG + YES: 100 * (1.0 - 0.60) = 40.0
    result = calculate_pnl("LONG", "YES", Decimal("100"), Decimal("0.60"))
    assert result == Decimal("40.00"), f"Expected 40.00, got {result}"

    # LONG + NO: 100 * (0.0 - 0.60) = -60.0
    result = calculate_pnl("LONG", "NO", Decimal("100"), Decimal("0.60"))
    assert result == Decimal("-60.00"), f"Expected -60.00, got {result}"

    # SHORT + NO: 100 * 0.60 = 60.0
    result = calculate_pnl("SHORT", "NO", Decimal("100"), Decimal("0.60"))
    assert result == Decimal("60.00"), f"Expected 60.00, got {result}"

    # SHORT + YES: 100 * (0.60 - 1.0) = -40.0
    result = calculate_pnl("SHORT", "YES", Decimal("100"), Decimal("0.60"))
    assert result == Decimal("-40.00"), f"Expected -40.00, got {result}"

    # FLAT: 0
    result = calculate_pnl("FLAT", "YES", Decimal("0"), Decimal("0.50"))
    assert result == Decimal("0"), f"Expected 0, got {result}"


def test_resolve_skips_unresolved_markets(resolved_positions_db):
    """Test that positions without market outcomes remain unresolved.

    Args:
        resolved_positions_db: Database with fixture data including market without outcome
    """
    from polymarket_analytics.positions.resolution import resolve_position_pnl

    # Run resolution
    resolve_position_pnl(resolved_positions_db, "esports")

    # Position for market-no-outcome should still be unresolved
    row = resolved_positions_db.execute(
        "SELECT resolved, outcome, pnl FROM positions WHERE trader_address = 'trader6'"
    ).fetchone()

    assert row[0] == 0, "Position should remain unresolved"
    assert row[1] is None, "Outcome should remain None"
    assert row[2] is None, "PnL should remain None"


def test_resolve_idempotent(resolved_positions_db):
    """Test that running resolve twice doesn't re-resolve already resolved positions.

    Args:
        resolved_positions_db: Database with fixture data
    """
    from polymarket_analytics.positions.resolution import resolve_position_pnl

    # First run
    count1 = resolve_position_pnl(resolved_positions_db, "esports")
    assert count1 == 5, f"Expected 5 positions resolved on first run, got {count1}"

    # Second run - should raise exception (no unresolved positions)
    import click

    with pytest.raises(click.ClickException) as exc_info:
        resolve_position_pnl(resolved_positions_db, "esports")

    # After first run, all resolvable positions are done, so second run hits the
    # "no resolvable positions" check before "no unresolved positions" check
    assert "No positions have resolvable markets" in str(
        exc_info.value
    ) or "No unresolved positions found" in str(exc_info.value)

    # Verify positions still have correct values (not doubled or modified)
    row = resolved_positions_db.execute(
        "SELECT outcome, pnl FROM positions WHERE trader_address = 'trader1'"
    ).fetchone()
    assert row[0] == "WIN"
    assert abs(float(row[1]) - 40.0) < 0.001


def test_resolve_fails_without_outcomes(test_db):
    """Test that resolve fails loudly if no market outcomes exist.

    Args:
        test_db: Database with schema but no outcomes
    """
    from polymarket_analytics.positions.resolution import resolve_position_pnl
    import click

    # Insert a market without outcome
    test_db["markets"].insert(
        {
            "condition_id": "market-no-outcome",
            "question": "Will Gen.G win?",
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

    # Insert a position
    import hashlib

    position_id = hashlib.sha256(b"trader1market-no-outcome").hexdigest()[:16]
    test_db["positions"].insert(
        {
            "id": position_id,
            "trader_address": "trader1",
            "market_id": "market-no-outcome",
            "direction": "LONG",
            "size": 100,
            "avg_entry_price": 0.50,
            "entry_timestamp": "2025-01-01T00:00:00Z",
            "last_trade_timestamp": "2025-01-02T00:00:00Z",
            "trade_count": 1,
            "resolved": 0,
            "outcome": None,
            "pnl": None,
        }
    )

    # Should raise ClickException
    with pytest.raises(click.ClickException) as exc_info:
        resolve_position_pnl(test_db, "esports")

    assert "No market outcomes found" in str(exc_info.value)
    assert "Run resolve-outcomes command first" in str(exc_info.value)


def test_resolve_flat_with_exit_price(test_db):
    """Test FLAT positions with avg_exit_price are resolved correctly.

    FLAT trader who bought at 0.40 and sold at 0.70:
    - pnl = size * (0.70 - 0.40) = 100 * 0.30 = 30.0
    - outcome = 'WIN' (pnl > 0)
    """
    from polymarket_analytics.positions.resolution import resolve_position_pnl
    import hashlib

    # Insert a FLAT position with avg_exit_price
    position_id = hashlib.sha256(b"flattradermarket1").hexdigest()[:16]
    test_db["positions"].insert(
        {
            "id": position_id,
            "trader_address": "flattrader",
            "market_id": "market-flat",
            "direction": "FLAT",
            "size": 100,
            "avg_entry_price": 0.40,
            "avg_exit_price": 0.70,
            "entry_timestamp": "2025-01-01T00:00:00Z",
            "last_trade_timestamp": "2025-01-02T00:00:00Z",
            "trade_count": 2,
            "resolved": 0,
            "outcome": None,
            "pnl": None,
        }
    )

    # Run resolution (no market outcomes needed for FLAT)
    count = resolve_position_pnl(test_db, "esports")

    # Should resolve 1 position
    assert count == 1

    # Verify FLAT position resolved correctly
    row = test_db.execute(
        "SELECT outcome, pnl, resolved FROM positions WHERE trader_address = 'flattrader'"
    ).fetchone()
    assert row[0] == "WIN", f"Expected WIN, got {row[0]}"
    assert abs(float(row[1]) - 30.0) < 0.001, f"Expected pnl 30.0, got {row[1]}"
    assert row[2] == 1, "Position should be resolved"


def test_calculate_pnl_flat_with_exit_price():
    """Test Python helper calculate_pnl() for FLAT with exit price.

    FLAT with entry=0.40, exit=0.70, size=100:
    Expected: 100 * (0.70 - 0.40) = 30.0
    """
    from polymarket_analytics.positions.resolution import calculate_pnl
    from decimal import Decimal

    # FLAT with exit price
    result = calculate_pnl(
        "FLAT", "YES", Decimal("100"), Decimal("0.40"), Decimal("0.70")
    )
    assert result == Decimal("30.00"), f"Expected 30.00, got {result}"

    # FLAT without exit price (old behavior)
    result = calculate_pnl("FLAT", "YES", Decimal("100"), Decimal("0.40"))
    assert result == Decimal("0"), f"Expected 0, got {result}"
