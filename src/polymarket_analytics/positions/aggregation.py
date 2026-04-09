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

    # 3. Warn on orphan trades (trades without market_entities.game) but don't block.
    # A small number of non-esports markets (chess, streamer bets, etc.) will never
    # have a game — excluding them is correct behaviour for the esports niche.
    orphan_count = db.execute("""
        SELECT COUNT(*) as cnt
        FROM trades t
        LEFT JOIN market_entities me ON me.condition_id = t.market_id
        WHERE me.game IS NULL
    """).fetchone()[0]
    if orphan_count > 0:
        click.echo(
            f"Warning: {orphan_count} trades have no game entity and will be excluded "
            "from positions (non-esports or unresolvable markets)."
        )

    # Get all trades grouped by (trader, market)
    trades_query = """
        SELECT
            trader_address,
            market_id,
            SUM(CASE WHEN side = 'BUY' THEN size ELSE -size END) as net_size,
            SUM(CASE WHEN side = 'BUY' THEN size * price ELSE 0 END) /
                NULLIF(SUM(CASE WHEN side = 'BUY' THEN size ELSE 0 END), 0) as avg_entry_price,
            SUM(CASE WHEN side = 'SELL' THEN size * price ELSE 0 END) /
                NULLIF(SUM(CASE WHEN side = 'SELL' THEN size ELSE 0 END), 0) as avg_exit_price,
            SUM(CASE WHEN side = 'BUY' THEN size ELSE 0 END) as gross_buy_size,
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

        # FLAT positions: size = gross BUY volume (not abs(net)≈0)
        # LONG/SHORT positions: size = abs(net_size) as before
        gross_buy_size = float(row["gross_buy_size"])
        if direction == "FLAT":
            size = gross_buy_size
        else:
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
                "avg_entry_price": float(row["avg_entry_price"])
                if row["avg_entry_price"] is not None
                else None,
                "avg_exit_price": float(row["avg_exit_price"])
                if row["avg_exit_price"] is not None
                else None,
                "entry_timestamp": row["entry_timestamp"],
                "last_trade_timestamp": row["last_trade_timestamp"],
                "trade_count": int(row["trade_count"]),
                "resolved": 0,
                "outcome": None,
                "pnl": None,
            }
        )

    # Upsert positions (idempotent, batched in single transaction)
    with db.conn:
        for position in positions:
            db["positions"].upsert(position, pk="id")

    return len(positions)
