---
created: 2026-04-06T03:22:35.928Z
title: Fix unstable trade_id fallback + dedup existing trades table
area: pipeline
files:
  - src/polymarket_analytics/commands/backfill.py:254
---

## Problem

When the Polymarket Data API omits both `trade_id` and `txHash`, the fallback ID collapses to `{trader_address}__{timestamp}`. This ID is not stable across runs — if the API returns the same trade with slightly different timestamp precision, or returns `txHash` on a subsequent run, the row gets a different key and bypasses `INSERT OR IGNORE`, inserting a silent duplicate. Position sizes double, PnL/ROI/Sharpe all distort with no error signal. This is worse than missing data — it's corrupt data that looks valid.

Confirmed: after re-backfilling `0x1ac344faa5bc043a4aae6cb0d41fe3cc5b7a8fb0`, a duplicate SELL appeared with trade_id `0x1ac344faa5bc043a4aae6cb0d41fe3cc5b7a8fb0__1775431309` alongside the original. Had to be manually deleted.

## Solution

1. Replace the fallback at `backfill.py:254` with a stable hash:
   ```python
   hashlib.sha256(f"{trader_address}:{market_id}:{side}:{price}:{size}:{timestamp}".encode()).hexdigest()[:32]
   ```
   Use `txHash` when present, fall back to this hash only when absent.

2. Run a one-time dedup pass on the existing `trades` table: for any logical duplicate (same trader_address, market_id, side, price, size, timestamp), keep the row with the earliest `rowid` (original insert) and delete the rest.

**Must be done before any re-fetch strategy (todo #2) is implemented.**
