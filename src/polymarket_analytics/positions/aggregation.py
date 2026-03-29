"""Position aggregation logic using SQL GROUP BY.

This module aggregates raw trades into one position per (trader, market) pair
with direction, size, volume-weighted entry price, and timestamps.
"""

import click


def build_positions_from_trades(db, niche_slug: str) -> int:
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

    # Execute SQL INSERT...SELECT with GROUP BY
    query = """
        INSERT INTO positions (
            id, trader_address, market_id, direction, size, avg_entry_price,
            entry_timestamp, last_trade_timestamp, trade_count, resolved, outcome, pnl
        )
        SELECT
            lower(hex(sha256(trader_address || market_id))) AS id,
            trader_address,
            market_id,
            CASE
                WHEN SUM(CASE WHEN side = 'BUY' THEN size ELSE -size END) > 0.000001 THEN 'LONG'
                WHEN SUM(CASE WHEN side = 'BUY' THEN size ELSE -size END) < -0.000001 THEN 'SHORT'
                ELSE 'FLAT'
            END AS direction,
            ABS(SUM(CASE WHEN side = 'BUY' THEN size ELSE -size END)) AS size,
            SUM(size * price) / SUM(size) AS avg_entry_price,
            MIN(timestamp) AS entry_timestamp,
            MAX(timestamp) AS last_trade_timestamp,
            COUNT(*) AS trade_count,
            0 AS resolved,
            NULL AS outcome,
            NULL AS pnl
        FROM trades t
        JOIN market_entities me ON me.condition_id = t.market_id
        WHERE me.game IS NOT NULL
        GROUP BY trader_address, market_id
        ON CONFLICT(id) DO UPDATE SET
            direction = excluded.direction,
            size = excluded.size,
            avg_entry_price = excluded.avg_entry_price,
            entry_timestamp = excluded.entry_timestamp,
            last_trade_timestamp = excluded.last_trade_timestamp,
            trade_count = excluded.trade_count,
            resolved = 0,
            outcome = NULL,
            pnl = NULL
    """

    # Execute query
    db.execute(query)

    # Get count of positions
    position_count = db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

    return position_count
