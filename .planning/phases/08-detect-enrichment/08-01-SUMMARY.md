# Phase 8 Plan 01 Summary - Schema Migration + Convergence Enrichment

## What Was Built

1. **Schema Migration (schema.py)**: Added 4 new columns to signals table via `run_migrations()`:
   - `clv_dominant_count INTEGER` - Count of Q5 traders with clv_zscore > 0
   - `avg_entry_price NUMERIC(10,6)` - Average entry price across converging traders
   - `min_entry_price NUMERIC(10,6)` - Minimum entry price across converging traders  
   - `tier TEXT` - WATCH/CONSIDER/ACT based on q5_count thresholds

2. **Convergence Query Enrichment (convergence.py)**: Updated `detect_convergence()` SQL query to compute all 4 new fields inline:
   - `COUNT(CASE WHEN ls.clv_zscore > 0 THEN 1 END)` for clv_dominant_count
   - `AVG(p.avg_entry_price)` for avg_entry_price
   - `MIN(p.avg_entry_price)` for min_entry_price
   - CASE expression for tier based on COUNT(DISTINCT p.trader_address)

3. **Test Fixture Fixes (conftest.py, test_detection.py)**: Fixed pre-existing bug where `create_market()` helper set end_date to yesterday, causing convergence query filter to exclude test markets. Added `end_date` parameter and `future_end_date` fixture.

## Key Decisions

- Used migration-safe ALTER TABLE pattern (check column exists before adding)
- tier CASE expression uses same COUNT(DISTINCT p.trader_address) as q5_count
- All new fields computed in SQL query (no Python post-processing)
- Docstring updated to document 4 new return columns

## Test Results

```
68 passed in 0.77s
```

All existing tests pass including 12 detection tests.

## Known Issues

(None - all tests passing)

## Follow-up Items

- Plan 02: Update writer.py upsert_signal() to persist 4 new fields
- Plan 03: Write TDD integration tests for enrichment (9 tests)
