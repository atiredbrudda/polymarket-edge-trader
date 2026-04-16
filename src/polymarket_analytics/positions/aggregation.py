"""Position aggregation logic using SQL GROUP BY.

This module aggregates raw trades into one position per (trader, market) pair
with direction, size, volume-weighted entry price, and timestamps.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

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


def build_positions_from_trades(
    db: Any,
    niche_slug: str,
    window_days: int = 35,
    dirty_pairs: Optional[set] = None,
) -> int:
    """Build positions from trades using SQL GROUP BY aggregation.

    Three execution paths depending on `dirty_pairs`:

    1. dirty_pairs provided and non-empty (monitor --chain path): load the known
       (trader_address, market_id) pairs into a temp table and re-aggregate only
       those — no DB scan for dirty detection at all (~34s → <1s).
    2. dirty_pairs is an empty set: nothing changed, return 0 immediately.
    3. dirty_pairs is None (cron/CLI path): read last_built_at watermark from
       _migrations and use the timestamp-range dirty CTE (or full scan on first run).

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche slug to scope aggregation (e.g., "esports")
        window_days: Rolling window for position aggregation
        dirty_pairs: Optional set of (trader_address, market_id) tuples that need
            rebuilding. Pass from the monitor's in-memory trade data to skip the
            dirty-detection DB scan. Pass None to use the watermark fallback.

    Returns:
        Count of positions created/updated

    Raises:
        click.ClickException: If dependencies missing (trades empty, no entities)
    """
    # Capture start time before any queries so any trades that arrive during this
    # run are caught on the next pass (their timestamp > our saved last_built_at).
    now_iso = datetime.now(timezone.utc).isoformat()

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

    # Build the aggregation query.
    # Three paths — see docstring for rationale.
    #
    # HAVING MIN(timestamp) ensures we only process positions that started within the
    # window — avoids partial positions where the BUY predates the window but a later
    # SELL falls inside it (which would corrupt avg_entry_price).
    _select_cols = f"""
            t.trader_address,
            t.market_id,
            SUM(CASE WHEN side = 'BUY' THEN size ELSE -size END) as net_size,
            SUM(CASE WHEN side = 'BUY' THEN size * price ELSE 0 END) /
                NULLIF(SUM(CASE WHEN side = 'BUY' THEN size ELSE 0 END), 0) as avg_entry_price,
            SUM(CASE WHEN side = 'SELL' THEN size * price ELSE 0 END) /
                NULLIF(SUM(CASE WHEN side = 'SELL' THEN size ELSE 0 END), 0) as avg_exit_price,
            SUM(CASE WHEN side = 'BUY' THEN size ELSE 0 END) as gross_buy_size,
            MIN(timestamp) as entry_timestamp,
            MAX(timestamp) as last_trade_timestamp,
            COUNT(*) as trade_count"""
    _where = f"""me.game IS NOT NULL
          AND t.timestamp >= datetime('now', '-{window_days} days')"""
    _having = f"""SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) > 0
           AND MIN(timestamp) >= datetime('now', '-{window_days} days')"""

    if dirty_pairs is not None:
        # Monitor path: caller provides the exact dirty pairs in memory.
        # Skip the 7.2M-row dirty CTE scan entirely.
        if not dirty_pairs:
            return 0

        db.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _bp_dirty (
                trader_address TEXT, market_id TEXT
            )
        """)
        db.execute("DELETE FROM _bp_dirty")
        db.conn.executemany("INSERT INTO _bp_dirty VALUES (?, ?)", list(dirty_pairs))

        trades_query = f"""
        SELECT {_select_cols}
        FROM trades t
        JOIN market_entities me ON me.condition_id = t.market_id
        JOIN _bp_dirty d ON d.trader_address = t.trader_address AND d.market_id = t.market_id
        WHERE {_where}
        GROUP BY t.trader_address, t.market_id
        HAVING {_having}
    """
    else:
        # Cron/CLI path: read watermark from _migrations.
        # Falls back to full scan if _migrations key is absent (first run or manual reset).
        last_built_at = None
        if "_migrations" in db.table_names():
            row = db.execute(
                "SELECT value FROM _migrations WHERE key = 'positions_last_built_at' LIMIT 1"
            ).fetchone()
            if row:
                last_built_at = row[0]

        if last_built_at:
            # Incremental: CTE finds dirty (trader, market) pairs (those with at least one
            # trade newer than last_built_at), then re-aggregates ALL their trades within
            # the window (not just new ones — avg_entry_price needs all BUY records).
            # idx_trades_ts_trader_market (timestamp, trader_address, market_id) makes this
            # a range-scan covering index rather than a full table scan.
            trades_query = f"""
        WITH dirty AS (
            SELECT DISTINCT trader_address, market_id
            FROM trades
            WHERE timestamp > '{last_built_at}'
        )
        SELECT {_select_cols}
        FROM trades t
        JOIN market_entities me ON me.condition_id = t.market_id
        JOIN dirty d ON d.trader_address = t.trader_address AND d.market_id = t.market_id
        WHERE {_where}
        GROUP BY t.trader_address, t.market_id
        HAVING {_having}
    """
        else:
            trades_query = f"""
        SELECT {_select_cols}
        FROM trades t
        JOIN market_entities me ON me.condition_id = t.market_id
        WHERE {_where}
        GROUP BY t.trader_address, t.market_id
        HAVING {_having}
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
                "data_incomplete": 0,
            }
        )

    # Upsert positions (idempotent, batched in single transaction)
    if positions:
        db["positions"].upsert_all(positions, pk="id")

    # Persist last_built_at so the next cron/CLI run is incremental.
    # Only update the watermark on the cron/CLI path (dirty_pairs=None).
    # The monitor path passes dirty_pairs and must NOT advance the watermark,
    # because backfill may later import old trades whose timestamps predate
    # the monitor's wall-clock — those would be eclipsed by a fresh watermark.
    if dirty_pairs is None:
        if positions:
            watermark = max(p["last_trade_timestamp"] for p in positions)
        else:
            watermark = now_iso  # no positions processed — keep clock-based fallback

        if "_migrations" not in db.table_names():
            db.execute("CREATE TABLE _migrations (key TEXT PRIMARY KEY, value TEXT)")
        db.execute(
            "INSERT OR REPLACE INTO _migrations VALUES ('positions_last_built_at', ?)",
            [watermark],
        )
        db.conn.commit()

    return len(positions)
