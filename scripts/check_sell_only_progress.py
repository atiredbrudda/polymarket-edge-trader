#!/usr/bin/env python3
"""Check SELL-only position progress during backfill fix."""

import sqlite3
import time
from datetime import datetime

DB_PATH = "data/analytics.db"


def check_progress():
    db = sqlite3.connect(DB_PATH)

    # SELL-only count
    sell_only = db.execute("""
        SELECT COUNT(*) FROM (
            SELECT t.trader_address, t.market_id
            FROM trades t
            JOIN positions p ON p.trader_address = t.trader_address AND p.market_id = t.market_id
            WHERE p.resolved = 0
            GROUP BY t.trader_address, t.market_id
            HAVING SUM(CASE WHEN t.side = 'BUY' THEN 1 ELSE 0 END) = 0
               AND SUM(CASE WHEN t.side = 'SELL' THEN 1 ELSE 0 END) > 0
        )
    """).fetchone()[0]

    # Remaining traders to process
    remaining = db.execute(
        "SELECT COUNT(*) FROM traders WHERE backfill_complete = 0"
    ).fetchone()[0]

    # Processed traders
    processed = db.execute(
        "SELECT COUNT(*) FROM traders WHERE backfill_complete = 1"
    ).fetchone()[0]

    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"SELL-only pairs: {sell_only:,} | "
        f"Remaining traders: {remaining:,} | "
        f"Processed traders: {processed:,}"
    )

    db.close()
    return sell_only


if __name__ == "__main__":
    print("Monitoring SELL-only fix progress (Ctrl+C to stop)...\n")
    initial = check_progress()

    try:
        while True:
            time.sleep(300)  # 5 minutes
            check_progress()
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
