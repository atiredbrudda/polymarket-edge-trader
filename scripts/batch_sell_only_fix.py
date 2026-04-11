#!/usr/bin/env python3
"""Batch backfill fix for SELL-only positions.

Processes traders in batches to avoid timeouts.
Run multiple times until all traders are processed.
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from polymarket_analytics.api.data import DataAPIClient
from polymarket_analytics.api.graph import GraphAPIClient
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.commands.backfill import (
    backfill_trader,
    fetch_trades_with_retry,
)

load_dotenv()

DB_PATH = "data/analytics.db"
BATCH_SIZE = 50  # Process 50 traders per run


async def run_batch():
    db = sqlite3.connect(DB_PATH)
    db_path = Path(DB_PATH)

    # Get traders with SELL-only positions, ordered by most affected
    traders = db.execute("""
        SELECT t.trader_address, COUNT(*) as sell_only_count
        FROM trades t
        JOIN positions p ON p.trader_address = t.trader_address AND p.market_id = t.market_id
        WHERE p.resolved = 0
        GROUP BY t.trader_address, t.market_id
        HAVING SUM(CASE WHEN t.side = 'BUY' THEN 1 ELSE 0 END) = 0
           AND SUM(CASE WHEN t.side = 'SELL' THEN 1 ELSE 0 END) > 0
        ORDER BY sell_only_count DESC
    """).fetchall()

    # Get unique trader addresses (already backfill reset)
    trader_addresses = list(set([t[0] for t in traders]))[:BATCH_SIZE]

    if not trader_addresses:
        print("No SELL-only traders remaining!")
        return

    print(f"Processing {len(trader_addresses)} traders (batch size: {BATCH_SIZE})")

    # Initialize clients
    data_client = DataAPIClient()
    graph_client = GraphAPIClient()

    total_ingested = 0
    total_fallbacks = 0

    try:
        for i, addr in enumerate(trader_addresses, 1):
            print(f"[{i}/{len(trader_addresses)}] Processing {addr[:10]}...")

            # Fetch from API first
            trades = await fetch_trades_with_retry(
                data_client, addr, since_unix_ts=None
            )

            # Backfill with Graph fallback
            stats = await backfill_trader(
                type(
                    "obj",
                    (object,),
                    {
                        "execute": db.execute,
                        "__getitem__": lambda self, key: type(
                            "table",
                            (object,),
                            {
                                "insert_all": lambda *args, **kwargs: None,
                                "update": lambda *args, **kwargs: None,
                            },
                        )(),
                    },
                )(),
                addr,
                data_client,
                graph_client,
                since_unix_ts=None,
                prefetched_trades=trades,
            )

            total_ingested += stats["ingested"]
            if stats["fallback"]:
                total_fallbacks += 1

        print(
            f"\nBatch complete: {total_ingested} trades ingested, {total_fallbacks} Graph fallbacks used"
        )

    finally:
        await data_client.close()
        await graph_client.close()
        db.close()


if __name__ == "__main__":
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting batch backfill fix..."
    )
    asyncio.run(run_batch())
