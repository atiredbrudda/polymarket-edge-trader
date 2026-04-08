# Pipeline Todo #3 - Incremental Mode for ingest_events

**Completed:** 2026-04-06

## What Was Built

Added incremental mode to `ingest_events` command to avoid fetching the entire 96K+ market catalog from Gamma API on every re-run.

## Implementation

### Changes Made

1. **`src/polymarket_analytics/commands/ingest_events.py`**
   - Added `--full` flag as explicit escape hatch for forced full fetch
   - Added market count check to determine first run vs re-run
   - First run (`existing_count == 0`): fetches all markets with `closed=None`
   - Re-run (`existing_count > 0`): fetches only active markets with `closed=False`
   - `--full` flag: always fetches all markets regardless of existing data

2. **`tests/test_ingest_events_incremental.py`** (NEW)
   - INCR-01: First run fetches all markets (closed=None)
   - INCR-02: Re-run fetches only active markets (closed=False)
   - INCR-03: --full flag forces full fetch regardless of existing data
   - INCR-04: Incremental mode upserts harmlessly without duplicates

## Key Decisions

1. **Branch on market count:** Simple heuristic - zero markets means first run, any existing markets means re-run. This avoids adding state columns to track ingest state separately.

2. **`--full` flag as escape hatch:** Critical for:
   - Partial failure recovery: if previous run crashed mid-way, user can force full fetch
   - Periodic resolution sweep: run weekly to catch markets that resolved since last full fetch
   - Without this, there's no way to recover from partial data gaps

3. **Accepted limitation:** Newly resolved markets won't appear in incremental fetch (closed=False). Resolution updates are `resolve-outcomes` command's responsibility, but it can only resolve what `ingest_events` has stored. Users should run `--full` periodically for complete resolution coverage.

## Test Results

```
pytest tests/test_ingest_events_incremental.py -v
4 passed in 0.42s
```

All 97 total tests pass (4 new + 93 existing).

## Deviations from Plan

None - implementation matches the spec in `.planning/todos/pending/2026-04-06-add-incremental-mode-to-ingest-events-skip-full-fetch-on-re-runs.md` exactly.

## Known Issues

None. The implementation is complete and tested.

## Follow-up

This unblocks **Todo #4** (store clobTokenIds in ingest_events so classify_tokens reads from DB), which depends on incremental mode being in place first.
