# Phase 28: Graph Market ID Resolution — SUMMARY

**Phase:** 28  
**Status:** Complete  
**Date:** 2026-03-25  
**Branch:** worker/28-graph-market-id-fix

## What Was Built

Fixed the Graph trade market_id linkage issue that caused 1.6M trades to be orphaned with synthetic IDs instead of real condition_ids. The fix enables proper position building from Graph trades.

### Problem

Graph trades were stored with `market_id = f"graph_{txhash}_{asset_id}"` instead of real `condition_id` values. This prevented:
- Joins with `markets` table
- Joins with `token_catalog` table  
- Position building via `build-positions` command
- Trade categorization

### Solution Implemented

**Plan 28-01: Converter Fix**
- Modified `graph_trade_to_api_response()` to accept optional `token_to_condition` dict
- When cache provided and asset_id found, uses real `condition_id`
- Falls back to synthetic ID with debug log when token not in catalog
- Added 3 new tests verifying resolution behavior

**Plan 28-02: Ingest Path Fix**
- Modified `ingest_trader_history_graph()` to call `_ensure_catalog_built(session)`
- Builds `catalog_token_cache` from entire `token_catalog` table (all niches)
- Creates `Market` and `MarketClassification` entries for catalog hits (idempotent)
- Passes `token_to_condition` cache to converter
- Logs unknown tokens for manual review

**Plan 28-03: Database Migration**
- Created `scripts/migrate_graph_market_ids.py` migration script
- Processes 1.6M orphaned trades in batches
- Extracts asset_id from synthetic market_id format
- Looks up in token_catalog and updates to real condition_id
- Batch commits (50K per batch) to avoid DB lock issues

## Results

### Migration Statistics
- **Total orphaned trades:** 1,610,449
- **Successfully migrated:** 182,830 (11.4%)
- **Not found in catalog:** 1,427,619 (88.6%)

### Why Only 11.4% Match Rate?

The token_catalog was built from JBecker markets parquet dataset, which:
- Covers a specific time period (not all markets)
- May not include newer markets created after catalog build
- May not include all niches equally

The 182K migrated trades represent markets that exist in both the Graph data AND the JBecker catalog.

### Remaining Orphaned Trades

The 1.4M unmatched trades are for markets not in the current token_catalog. Future options:
1. Expand token_catalog building to include more data sources
2. Query Polymarket API to resolve unknown asset_ids
3. Accept partial coverage for Graph trades

## Key Decisions

1. **Optional cache parameter:** Made `token_to_condition` optional in converter to maintain backward compatibility and allow fallback behavior.

2. **Batch size:** Used 50K batch size for migration to balance speed vs. DB lock duration. Migration completed in ~2 minutes.

3. **Market creation:** Graph ingest now creates Market entries for catalog hits (matching JBecker pattern), ensuring markets exist for position building.

4. **Idempotency:** Used savepoints for market/classification creation to handle re-runs safely.

## Test Results

- **New tests added:** 3 (test_market_id_resolves_from_catalog, test_market_id_fallback_when_not_in_catalog, test_market_id_no_cache_passed)
- **All Graph converter tests:** 6/6 passing
- **All ingest tests:** 8/8 passing
- **Pre-existing failures:** 5 (test_catalog_builder.py — unrelated to this change)

## Files Changed

| File | Type | Lines Changed |
|------|------|---------------|
| `src/graph/converters.py` | Modified | ~15 |
| `src/pipeline/ingest.py` | Modified | ~100 |
| `tests/test_graph_converters.py` | Modified | ~50 |
| `scripts/migrate_graph_market_ids.py` | New | ~150 |

## Follow-up Items

1. **Position rebuild:** Run `polymarket build-positions` to create positions from newly-linked trades
2. **Catalog expansion:** Investigate adding more markets to token_catalog to improve coverage
3. **API fallback:** Consider adding API-based resolution for unknown tokens during ingest

## Verification

```bash
# Verify migration complete
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM trades WHERE market_id LIKE 'graph_%';"
# Expected: 1427619 (unmatched trades remain)

# Verify migrated trades have real condition_ids
sqlite3 data/polymarket.db "SELECT COUNT(*) FROM trades WHERE market_id LIKE '0x%';"
# Expected: Increased by 182830

# Run tests
source .venv/bin/activate && pytest tests/test_graph_converters.py tests/test_ingest.py -v
# Expected: All pass
```
