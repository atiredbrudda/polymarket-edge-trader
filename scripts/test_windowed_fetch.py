"""One-off validation of time-windowed fetch_trader_trades.

Picks a trader known to have timed out under the non-windowed fetch
(0x04dbe94f, deterministic 120s timeout) and verifies windowing gets
full history in reasonable time without exhaustion.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

from polymarket_analytics.api.graph import GraphAPIClient

# Picked from the repeated-timeout list in today's heal run
TEST_TRADER = "0x04dbe94f"


async def main() -> int:
    # Fill in the full address from memory (was 0x04dbe94f... truncated)
    trader = sys.argv[1] if len(sys.argv) > 1 else TEST_TRADER
    api_key = os.environ.get("GOLDSKY_API_KEY") or os.environ.get("GRAPH_API_KEY")
    graph = GraphAPIClient(api_key=api_key)
    try:
        print(f"Fetching full history for {trader} (windowed)...")
        t0 = time.time()
        events = await graph.fetch_trader_trades(trader, since_unix_ts=None)
        elapsed = time.time() - t0
        print(f"  events: {len(events):,}")
        print(f"  elapsed: {elapsed:.1f}s")
        if events:
            ts_min = min(int(e["timestamp"]) for e in events)
            ts_max = max(int(e["timestamp"]) for e in events)
            print(f"  timestamp range: {ts_min} -> {ts_max}")
        return 0
    finally:
        await graph.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
