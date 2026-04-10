#!/usr/bin/env python3
"""Fix remaining SELL-only traders."""

import asyncio
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from polymarket_analytics.api.data import DataAPIClient
from polymarket_analytics.api.graph import GraphAPIClient
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.commands.backfill import backfill_trader

load_dotenv()


async def fix_remaining():
    db_path = Path("data/analytics.db")
    db = init_database(db_path)

    # Get traders with backfill_complete=0
    traders = db.execute(
        "SELECT address FROM traders WHERE backfill_complete = 0"
    ).fetchall()

    if not traders:
        print("No traders remaining!")
        return

    print(f"Processing {len(traders)} traders...")

    data_client = DataAPIClient()
    graph_client = GraphAPIClient()

    try:
        for trader in traders:
            addr = trader[0]
            print(f"\nProcessing {addr[:10]}...")

            stats = await backfill_trader(
                db, addr, data_client, graph_client, since_unix_ts=None
            )

            print(
                f"  Ingested: {stats['ingested']}, Skipped: {stats['skipped']}, Graph fallback: {stats['fallback']}"
            )
    finally:
        await data_client.close()
        await graph_client.close()

    # Check result
    sell_only = db.execute("""
        SELECT COUNT(*) FROM (
            SELECT t.trader_address, t.market_id
            FROM trades t
            JOIN positions p ON p.trader_address = t.trader_address AND p.market_id = t.market_id
            WHERE p.resolved = 0
            GROUP BY t.trader_address, t.market_id
            HAVING SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) = 0
               AND SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) > 0
        )
    """).fetchone()[0]
    print(f"\nSELL-only pairs after fix: {sell_only:,}")


if __name__ == "__main__":
    asyncio.run(fix_remaining())
