# Phase 08 Plan 02 Summary - Writer/Detect Wiring

**Date:** 2026-04-06
**Branch:** worker/08-detect-enrichment-p02
**Depends on:** Plan 08-01 (schema migration + convergence enrichment)

## What Was Built

Updated the signal writer to persist all four enriched fields from the convergence query:
- `clv_dominant_count`: Count of Q5 traders with positive CLV z-score
- `avg_entry_price`: Average entry price across converging traders
- `min_entry_price`: Minimum entry price across converging traders
- `tier`: WATCH/CONSIDER/ACT tier based on q5_count

## Key Changes

### writer.py
- `upsert_signal()`: Added 4 new optional parameters (all default to `None` for backward compatibility)
- INSERT SQL: Added 4 new columns to INSERT statement
- UPDATE SQL: Added 4 new columns to UPDATE SET clause
- `upsert_signals_batch()`: Extract new fields from DataFrame rows with `pd.isna()` guards and `"column" in row` checks

### detect.py
- Updated docstring to reflect enriched signal fields
- No functional changes needed - enriched DataFrame flows through automatically

## Decisions Made

1. **Optional parameters with None defaults**: Ensures existing callers (tests) don't break
2. **Column existence guards in batch function**: `"clv_dominant_count" in row` checks allow the function to work with both old and new DataFrames
3. **avg_score retained**: Per ENRC-09, avg_score is kept in all SQL but not used as quality signal

## Test Results

- **Full suite:** 68/68 tests pass
- **Detection tests:** 12/12 tests pass
- **Verification test:** INSERT and UPDATE with all 4 new fields work correctly

## Known Issues

(None)

## Files Changed

- `src/polymarket_analytics/detection/writer.py` - upsert_signal() signature, INSERT/UPDATE SQL, batch extraction
- `src/polymarket_analytics/commands/detect.py` - docstring update

## Merged from Plan 08-01

This branch also includes Plan 08-01 changes (merged from worker/08-detect-enrichment-p01):
- Schema migration: 4 new signals columns (clv_dominant_count, avg_entry_price, min_entry_price, tier)
- Convergence query: Computes all 4 fields inline via SQL
- Test fixture fix: create_market() accepts future end_date
