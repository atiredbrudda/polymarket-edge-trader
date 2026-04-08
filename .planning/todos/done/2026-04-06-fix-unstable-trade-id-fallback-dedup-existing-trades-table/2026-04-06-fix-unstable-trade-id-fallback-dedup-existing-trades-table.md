---
created: 2026-04-06T03:22:35.928Z
title: Fix unstable trade_id fallback + dedup existing trades table
area: pipeline
files:
  - src/polymarket_analytics/commands/backfill.py:254
  - src/polymarket_analytics/api/graph.py:114
---

## Problem

When the Polymarket Data API omits both `trade_id` and `txHash`, the fallback ID collapses to `{trader_address}__{timestamp}`. This ID is not stable across runs — if the API returns the same trade with slightly different timestamp precision, or returns `txHash` on a subsequent run, the row gets a different key and bypasses `INSERT OR IGNORE`, inserting a silent duplicate. Position sizes double, PnL/ROI/Sharpe all distort with no error signal.

Secondary issue: when `needs_graph=True` due to partial API coverage (API returns trades but doesn't cover the full 40-day window), API and Graph trades are merged into the same list. The same underlying trade can appear in both sources with different IDs — one API trade_id, one `transactionHash_graphId` from `graph.py:114`. `INSERT OR IGNORE` doesn't catch it because the IDs differ. This is a pre-existing cross-source duplicate.

Confirmed: after re-backfilling `0x1ac344faa5bc043a4aae6cb0d41fe3cc5b7a8fb0`, a duplicate SELL appeared with trade_id `0x1ac344faa5bc043a4aae6cb0d41fe3cc5b7a8fb0__1775431309` alongside the original.

Note: `trades.trade_id` has no FK references from `positions` or other tables — dedup deletes are safe.

## Solution

**1. Fix the fallback ID at `backfill.py:254`.**

Reorder so `token_id` is computed before the fallback ID (currently token_id is on line 255, one line after). Use `txHash` when present, fall back to a stable hash:

```python
token_id = trade.get("asset") or trade.get("asset_id")
trade_id = (
    trade.get("trade_id")
    or trade.get("txHash")
    or hashlib.sha256(
        f"{trader_address}:{token_id}:{side}:{price_str}:{size_str}:{timestamp}".encode()
    ).hexdigest()[:32]
)
```

Use `token_id` (not `market_id`/`condition_id`) — condition_id isn't resolved until the token_catalog lookup at line 266, after the ID is needed.

**2. One-time dedup pass on existing `trades` table.**

Use logical fields to identify duplicates, catching both unstable fallback IDs and cross-source duplicates:

```sql
DELETE FROM trades
WHERE rowid NOT IN (
    SELECT MIN(rowid)
    FROM trades
    GROUP BY trader_address, token_id, side, price, size, timestamp
)
```

`MIN(rowid)` keeps the earliest insert. API trades are inserted before Graph trades in the merge loop, so the API version is preserved where both exist.

Edge case: two legitimate trades with identical (trader_address, token_id, side, price, size, timestamp). Theoretically possible. Mitigated by the fact that same-second same-price same-size same-side trades for one trader on one token are extremely rare. Accept the risk — document it.

**Must be done before todo #2 (selective re-fetch) or re-fetching will re-introduce duplicates.**
