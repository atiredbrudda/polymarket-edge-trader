# Pipeline Todo #5 - Incremental Fetch for Backfill

**Branch:** worker/todo5-incremental-backfill-fetch

**Date:** 2026-04-07

**Plan:** `.planning/todos/pending/2026-04-07-add-incremental-fetch-to-backfill-pass-last-trade-seen-at-as-time-filter.md`

---

## What Was Built

Added incremental fetch capability to both API clients (Graph and Data API) by passing `last_trade_seen_at` as a `since_unix_ts` time filter. This eliminates full re-fetches on every backfill run, dramatically reducing backfill time for traders with existing history.

### Key Changes

1. **`GraphAPIClient.fetch_trader_trades()`** (`src/polymarket_analytics/api/graph.py:175`)
   - Added `since_unix_ts: Optional[int] = None` parameter
   - Builds `timestamp_gte` clause in GraphQL where filter when set
   - Clause applies to both first-page and subsequent-page queries via closure

2. **`DataAPIClient.fetch_user_trades()`** (`src/polymarket_analytics/api/data.py:155`)
   - Added `since_unix_ts: Optional[int] = None` parameter
   - Filters each page to trades >= since_unix_ts
   - Stops pagination early when boundary is hit (assumes newest-first ordering)

3. **`backfill_trader()`** (`src/polymarket_analytics/commands/backfill.py:180`)
   - Added `since_unix_ts: Optional[int] = None` parameter
   - Passes since_unix_ts to both `fetch_trades_with_retry()` and `graph_client.fetch_trader_trades()`

4. **`fetch_trades_with_retry()`** (`src/polymarket_analytics/commands/backfill.py:126`)
   - Added `since_unix_ts: Optional[int] = None` parameter
   - Forwards to `client.fetch_user_trades(since_unix_ts=since_unix_ts)`

5. **`backfill_async()`** (`src/polymarket_analytics/commands/backfill.py:434`)
   - Updated traders query to SELECT `address, last_trade_seen_at`
   - Loop body converts ISO `last_trade_seen_at` → Unix timestamp per trader
   - Passes `since_unix_ts` to `backfill_trader()` call
   - Traders with NULL `last_trade_seen_at` get `since_unix_ts=None` (full fetch, unchanged behavior)

6. **Tests**
   - `tests/test_graph.py::TestFetchTraderTradesTimestampFilter` — 2 tests verifying timestamp_gte in GraphQL query
   - `tests/test_incremental_backfill.py` — 5 tests:
     - `TestDataAPIIncrementalFetch` — 3 tests for early-exit pagination
     - `TestBackfillTraderSinceTs` — 2 tests for since_unix_ts forwarding

---

## Key Decisions

1. **Closure pattern for GraphQL**: The `ts_clause` variable is built in `fetch_trader_trades()` and captured by the `_paginate()` closure. This avoids passing it as an extra parameter and keeps the change minimal.

2. **Early-exit boundary detection**: Data API pagination stops when `hit_boundary` is True (a page contained trades older than since_unix_ts). This assumes newest-first ordering, which is standard for the Polymarket Data API.

3. **NULL handling**: Traders with NULL `last_trade_seen_at` receive `since_unix_ts=None`, which triggers full fetch behavior identical to before. This ensures new traders or migrated traders get complete history.

---

## Test Results

```
.venv/bin/python3.13 -m pytest tests/ -x -q
........................................................................ [ 62%]
...........................................                              [100%]
115 passed in 1.24s
```

All 115 tests pass (7 new tests added).

---

## Deviations from Plan

None. Implementation matches PLAN.md spec exactly.

---

## Known Issues

None. Pre-existing linter warnings in `backfill.py` (E402 import order) are unrelated to this change.

---

## Pre-Submit Checklist

- [x] All tests pass (.venv/bin/python3.13 -m pytest tests/ -x -q → 115 passed)
- [x] Linter clean for modified files (test files clean; backfill.py pre-existing warnings unchanged)
- [x] No debug artifacts
- [x] STATE.md NOT touched (reviewer-only)
- [x] Plan SUMMARY.md written
