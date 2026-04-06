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

**1. Schema migration — add two columns to `traders` table:**

```sql
ALTER TABLE traders ADD COLUMN last_backfilled_at TEXT;
ALTER TABLE traders ADD COLUMN last_trade_seen_at TEXT;
```

Add to `run_migrations()` in `schema.py` with existence check (same pattern as other migrations).

**2. Migration of existing data — prevent mass re-fetch on first run:**

After adding the columns, set `last_backfilled_at = datetime.now()` for all traders where `backfill_complete = True`. Without this, all existing traders have `last_backfilled_at = NULL` and the re-fetch query treats them as "never backfilled" → triggers a full re-fetch of every trader on the first run after migration. This is the exact expensive scenario we're trying to avoid.

```sql
UPDATE traders
SET last_backfilled_at = datetime('now')
WHERE backfill_complete = 1
```

**3. Re-fetch selection query (replaces line 361 in backfill.py):**

```sql
SELECT address FROM traders
WHERE
  (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
  AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
```

NULL handling is explicit:
- `last_trade_seen_at IS NULL` → new trader, never backfilled, include
- `last_backfilled_at IS NULL` → never backfilled (new trader not yet migrated), include
- `last_trade_seen_at < cutoff` → last known trade older than 40 days, skip (doesn't affect scores)
- `last_backfilled_at >= threshold` → recently refreshed, skip

`cutoff` = now - 40 days. `threshold` = now - refresh interval (e.g. 6 hours, hardcoded initially).

**4. After each successful backfill, update both timestamps:**

```python
db["traders"].update(trader_address, {
    "last_backfilled_at": datetime.now(timezone.utc).isoformat(),
    "last_trade_seen_at": max_trade_timestamp,  # max(trade["timestamp"]) from ingested trades
    "backfill_complete": True,  # keep for backwards compatibility
})
```

**Depends on todo #1 (stable trade_id) being done first.**
