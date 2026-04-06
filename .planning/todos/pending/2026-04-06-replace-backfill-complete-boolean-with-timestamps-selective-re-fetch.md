---
created: 2026-04-06T03:22:35.928Z
title: Replace backfill_complete boolean with timestamps + selective re-fetch
area: pipeline
files:
  - src/polymarket_analytics/commands/backfill.py:327
  - src/polymarket_analytics/db/schema.py
---

## Problem

`backfill_complete` is a one-time boolean flag. Once set to `True`, a trader is never re-fetched regardless of new activity. Any trades that occur after the initial backfill run are never ingested — missing BUY trades cause positions to show wrong direction, wrong `avg_entry_price`, and phantom direction. CLV/ROI/Sharpe scoring distorts because the position history is incomplete.

Confirmed: resetting `backfill_complete=False` for one trader ingested 383 new trades including a missing BUY for market `0xdbaecadd...` that was causing a LONG exit to appear as SHORT.

The Data API has no `since=` parameter — every re-fetch is a full history pull. Re-fetching all traders is expensive (serially, 1 HTTP call per trader, up to 10 retries each). The only optimization lever is choosing *which* traders to re-fetch.

## Solution

1. Add `last_backfilled_at` (TIMESTAMP) and `last_trade_seen_at` (TIMESTAMP) columns to the `traders` table (schema migration in `schema.py`).

2. After each successful backfill, set `last_backfilled_at = now()` and `last_trade_seen_at = max(trade.timestamp)` for that trader.

3. Re-fetch criteria: trader is eligible for re-fetch if:
   - `last_trade_seen_at` is within the 40-day scoring window (still affects scores), AND
   - `last_backfilled_at` is older than a refresh threshold (e.g. 6 hours)

4. Remove the `backfill_complete` boolean or keep it for legacy compatibility but stop using it as the sole gate.

**Depends on todo #1 (stable trade_id) being done first — re-fetching without stable IDs corrupts data.**
