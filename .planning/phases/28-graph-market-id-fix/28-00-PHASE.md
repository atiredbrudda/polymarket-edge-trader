# Phase 28: Graph Market ID Resolution

**Status:** In Progress  
**Created:** 2026-03-25  
**Goal:** Fix Graph trade market_id linkage to enable position building from 1.6M orphaned trades

## Problem Statement

The Graph backfill successfully ingested 1,610,449 trades covering the gap period (Jan 29 – Mar 21), but **zero positions were built** from them. Root cause: the Graph converter stores trades with synthetic `market_id = f"graph_{txhash}_{asset_id}"` instead of real `condition_id` values.

These synthetic IDs don't match any entries in `markets` or `token_catalog`, causing:
- 665,301 unique market_ids that don't exist anywhere
- Zero joins in build-positions (which requires `market_id == MarketEntity.condition_id`)
- All 1.6M trades effectively orphaned

## Root Cause Analysis

**File:** `src/graph/converters.py:94`
```python
# TODO: Decode condition_id from assetId if needed
market_id = f"graph_{graph_trade['transactionHash']}_{asset_id}"
```

**File:** `src/pipeline/ingest.py:1299-1426`
The `ingest_trader_history_graph()` method:
- Does NOT call `_ensure_catalog_built()`
- Does NOT build a `catalog_token_cache`
- Does NOT look up `asset_id → condition_id` via `token_catalog`
- Stores all trades as "detail trades" without categorization

**Comparison:** The JBecker ingestion path (lines 1560-1610) properly:
1. Calls `_ensure_catalog_built(session)`
2. Builds `catalog_token_cache` from `token_catalog` table
3. Looks up each `token_id` to get `condition_id`
4. Creates proper `Market` and `MarketClassification` entries

The token_catalog has 133,092 entries mapping `token_id → condition_id` — exactly what's needed.

## Solution

### Part 1: Fix Converter (New Trades)
Modify `graph_trade_to_api_response()` to accept and use a `token_to_condition` cache dict. When converting, look up `asset_id` in the cache to get real `condition_id`.

### Part 2: Fix Ingest Path
Modify `ingest_trader_history_graph()` to:
1. Call `_ensure_catalog_built(session)`
2. Build `catalog_token_cache` from `token_catalog` (all niches, not just esports)
3. Pass cache to converter or do lookup inline
4. Route trades through proper categorization like JBecker path

### Part 3: Backpatch Existing Trades
Create migration script to update existing 1.6M trades:
```sql
-- Extract asset_id from market_id (format: graph_{txhash}_{asset_id})
-- Look up in token_catalog
-- Update market_id to real condition_id
```

## Success Criteria

1. **Converter:** Graph trades produce `market_id = condition_id` (not synthetic ID)
2. **Ingest:** New Graph trades are categorized and linked to markets
3. **Backpatch:** 1.6M existing trades updated with real condition_ids
4. **Positions:** build-positions command creates positions from Graph trades
5. **Tests:** All existing tests pass + new tests verify market_id resolution

## Plans

| Plan | Description | Status |
|------|-------------|--------|
| 28-01 | Fix converters.py to resolve condition_id from token_catalog | Pending |
| 28-02 | Fix ingest.py to use catalog cache for Graph trades | Pending |
| 28-03 | Create and run DB migration for existing 1.6M trades | Pending |
| 28-04 | Update tests and validate end-to-end | Pending |

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| token_catalog doesn't have all asset_ids | Some trades may remain orphaned — log unknown tokens for manual review |
| Migration script locks DB for too long | Use batched updates with progress logging |
| Converter signature change breaks tests | Update tests to pass mock token cache |

## Files to Modify

- `src/graph/converters.py` — Fix market_id resolution
- `src/pipeline/ingest.py` — Add catalog cache to Graph ingest
- `tests/test_graph_converters.py` — Add market_id tests
- `scripts/migrate_graph_market_ids.py` (NEW) — Backpatch existing trades
