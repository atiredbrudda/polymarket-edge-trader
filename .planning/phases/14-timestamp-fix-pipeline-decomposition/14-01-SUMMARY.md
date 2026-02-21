# Phase 14-01: Block Number Timestamp Fix

## Summary

Fixed JBecker trade timestamps: all 339K stored trades were showing Jan-Feb 2026 (dataset collection date) instead of actual trade dates because the parquet `timestamp` column is NULL for all rows. The real trade dates live in `block_number`.

## Changes

### src/datasources/converters.py

1. Added `_POLYGON_BLOCK_ANCHORS` constant with 5 anchor blocks (40M-80M) and their Unix timestamps
2. Added `block_number_to_timestamp()` function using piecewise linear interpolation
3. Updated `jbecker_trade_to_api_response()` to use `block_number` for timestamp derivation, with `_fetched_at` as fallback

### src/cli/commands.py

1. Added `Trade` to imports from `src.db.models`
2. Added `reset-backfill` CLI command that:
   - Counts JBecker trades (trade_id LIKE 'jbecker_%')
   - Prompts for confirmation
   - Deletes all JBecker trades
   - Resets `backfill_complete=False` for affected traders

## Verification

```
Block 40,000,000: 2023-03-05 OK
Block 50,000,000: 2023-11-16 OK
Block 60,000,000: 2024-07-30 OK
Block 70,000,000: 2025-04-07 OK
Block 80,000,000: 2025-12-07 OK

Converter timestamp year: 2023 OK (block 50M)
```

All 11 ingest tests pass, 0 regressions.

## Usage

After this fix, users should:
1. Run `polymarket reset-backfill` to clear old trades with wrong timestamps
2. Run `polymarket backfill` to re-ingest with correct timestamps
