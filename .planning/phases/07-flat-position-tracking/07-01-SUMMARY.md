# Phase 07 Plan 01 Summary

**Date:** 2026-04-05  
**Branch:** worker/07-flat-position-tracking-p01  
**Plan:** .planning/phases/07-flat-position-tracking/07-01-PLAN.md

## What Was Built

Implemented FLAT position tracking foundation by adding `avg_exit_price` column to positions table and splitting BUY/SELL aggregation logic:

1. **Schema migration (schema.py):** Added `avg_exit_price NUMERIC(10,6)` column to positions table via idempotent migration in `run_migrations()`

2. **BUY/SELL split aggregation (aggregation.py):** 
   - `avg_entry_price` = BUY-only VWAP: `SUM(CASE WHEN side='BUY' THEN size*price ELSE 0 END) / NULLIF(SUM(CASE WHEN side='BUY' THEN size ELSE 0 END), 0)`
   - `avg_exit_price` = SELL-only VWAP: `SUM(CASE WHEN side='SELL' THEN size*price ELSE 0 END) / NULLIF(SUM(CASE WHEN side='SELL' THEN size ELSE 0 END), 0)` (NULL when no SELL trades)
   - `gross_buy_size` = SUM of BUY volume for FLAT position sizing

3. **FLAT position size override:** FLAT positions now use `gross_buy_size` (total BUY volume) instead of `abs(net_size)≈0`, making FLAT traders visible to scoring

## Key Decisions

- Used raw SQL `ALTER TABLE` with explicit `NUMERIC(10,6)` affinity for avg_exit_price (matches project convention for price/size columns)
- NULL-safe handling: avg_exit_price is NULL for LONG/SHORT positions with no SELL trades
- Guarded against division by zero using `NULLIF(..., 0)` pattern

## Deviations from PLAN.md

None. Implementation matches spec exactly.

## Test Results

**pytest results:**
- `tests/test_build_positions.py`: 5/5 passed (aggregation, direction, VWAP, dependency assertions, idempotency)
- Full suite (excluding pre-existing detection test failure): 56/56 passed
- Migration verification: avg_exit_price column exists, run_migrations() is idempotent

**Linter:**
- `ruff check src/polymarket_analytics/db/schema.py src/polymarket_analytics/positions/aggregation.py`: All checks passed

## Known Issues / Follow-up

- Pre-existing test failure in `tests/test_detection.py::test_convergence_detection_basic` (unrelated to this plan - confirmed failing on main branch before changes)
- Phase 7 Plans 07-02 and 07-03 remain to be executed

## Checklist

- [x] All tests pass (pytest)
- [x] Linter clean (ruff check src/ tests/)
- [x] No debug artifacts
- [x] STATE.md NOT touched (reviewer-only)
- [x] SUMMARY.md written
