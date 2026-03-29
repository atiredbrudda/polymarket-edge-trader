"""Position aggregation logic using SQL GROUP BY.

This module aggregates raw trades into one position per (trader, market) pair
with direction, size, volume-weighted entry price, and timestamps.
"""

import hashlib
from typing import Any

import click


def _generate_position_id(trader_address: str, market_id: str) -> str:
    """Generate deterministic position ID from trader_address and market_id.

    Args:
        trader_address: Trader wallet address
        market_id: Market condition ID

    Returns:
        SHA256 hash (first 16 chars, lowercase hex) as stable position ID
    """
    combined = f"{trader_address}{market_id}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def build_positions_from_trades(db: Any, niche_slug: str) -> int:
    """Build positions from trades using SQL GROUP BY aggregation.

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche slug to scope aggregation (e.g., "esports")

    Returns:
        Count of positions created/updated

    Raises:
        click.ClickException: If dependencies missing (trades empty, no entities)
    """
    # Dependency assertions - fail loudly if prerequisites missing
    # 1. Assert trades table has data
    trades_count = db.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()[0]
    if trades_count == 0:
        raise click.ClickException("trades table is empty. Run backfill command first.")

    # 2. Assert market_entities has rows with game IS NOT NULL
    entities_count = db.execute(
        "SELECT COUNT(*) as cnt FROM market_entities WHERE game IS NOT NULL"
    ).fetchone()[0]
    if entities_count == 0:
        raise click.ClickException(
            "market_entities table has no rows with game IS NOT NULL. "
            "Run discover command first."
        )

    # 3. Assert zero orphan trades (trades without market_entities.game)
    orphan_count = db.execute("""
        SELECT COUNT(*) as cnt
        FROM trades t
        LEFT JOIN market_entities me ON me.condition_id = t.market_id
        WHERE me.game IS NULL
    """).fetchone()[0]
    if orphan_count > 0:
        raise click.ClickException(
            f"Found {orphan_count} trades without matching market_entities.game. "
            "Run discover command to extract entities for these markets."
        )

    # Get all trades grouped by (trader, market)
    trades_query = """
        SELECT
            trader_address,
            market_id,
            SUM(CASE WHEN side = 'BUY' THEN size ELSE -size END) as net_size,
            SUM(size * price) / SUM(size) as avg_entry_price,
            MIN(timestamp) as entry_timestamp,
            MAX(timestamp) as last_trade_timestamp,
            COUNT(*) as trade_count
        FROM trades t
        JOIN market_entities me ON me.condition_id = t.market_id
        WHERE me.game IS NOT NULL
        GROUP BY trader_address, market_id
    """

    # Process each (trader, market) pair
    positions = []
    for row in db.query(trades_query):
        trader_address = row["trader_address"]
        market_id = row["market_id"]
        net_size = float(row["net_size"])

        # Determine direction with epsilon tolerance
        epsilon = 0.000001
        if net_size > epsilon:
            direction = "LONG"
        elif net_size < -epsilon:
            direction = "SHORT"
        else:
            direction = "FLAT"

        # Size is absolute net size
        size = abs(net_size)

        # Generate deterministic position ID
        position_id = _generate_position_id(trader_address, market_id)

        positions.append(
            {
                "id": position_id,
                "trader_address": trader_address,
                "market_id": market_id,
                "direction": direction,
                "size": size,
                "avg_entry_price": float(row["avg_entry_price"]),
                "entry_timestamp": row["entry_timestamp"],
                "last_trade_timestamp": row["last_trade_timestamp"],
                "trade_count": int(row["trade_count"]),
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            }
        )

    # Upsert positions (idempotent)
    for position in positions:
        db["positions"].upsert(position, pk="id")

    return len(positions)
