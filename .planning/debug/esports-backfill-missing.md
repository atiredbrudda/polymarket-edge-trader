---
status: resolved
trigger: "After backfilling 200 traders, only 13 had any eSports trades (1 each — from discovery, not backfill). All 18,420 trades routed to trader_category_summaries with non-eSports categories."
created: 2026-02-16T21:00:00Z
updated: 2026-02-16T23:50:00Z
---

## ROOT CAUSE

Multiple issues preventing eSports trade classification during backfill:

1. **JBecker converter used wrong column names**: Expected camelCase (`makerAmountFilled`) but actual parquet uses snake_case (`maker_amount`). Also missing `side`, `price`, `id` fields.

2. **backfill CLI command didn't wire JBecker client**: The `IngestionPipeline` was created without `jbecker_client`, so hybrid method fell back to API-only (100 trade limit).

3. **Token ID to condition ID mapping missing**: JBecker trades use token_ids (e.g., `4777159...`), but classification looks up by condition_id. The 398 eSports markets in DB had no `tokens` JSON column populated.

4. **New markets from Gamma not classified**: When Gamma API lookups discovered new markets, they were saved with `category="Unknown"` instead of being classified against taxonomy.

## EVIDENCE

- Sample address 0x2e3d069c9e8ff1970431244265a9deb8348278e5 is known eSports participant but backfill found 0 eSports trades
- `Tiers used: api` in backfill output (not JBecker) — confirmed JBecker not wired
- 468 eSports markets in DB but 0 token mappings — tokens JSON was NULL
- After fix: 727 eSports markets in taxonomy, 515 detail trades captured for sample trader

## FIX APPLIED

1. **src/datasources/converters.py**: Rewrote `jbecker_trade_to_api_response()` to handle snake_case columns, derive price from amount ratio, handle missing timestamp, create trade_id from tx_hash+log_index.

2. **src/cli/commands.py**: Wired JBecker client into backfill command so hybrid method uses JBecker as primary source.

3. **src/pipeline/ingest.py**: 
   - Fixed `ingest_trader_history_jbecker()` to build token→condition map from DB
   - Added Gamma API lookups for unknown tokens (discovers new markets on-the-fly)
   - Added taxonomy classification lookup to override category to "eSports" for classified markets
   - Added category routing via CategoryFilter (was storing all trades as detail with no routing)

4. **Data fixes**:
   - Backfilled tokens JSON for 398 markets via CLOB API
   - Ran classification pipeline to classify 259 newly discovered markets

## FILES CHANGED

- src/cli/commands.py (+17 lines)
- src/datasources/converters.py (rewrote ~100 lines)
- src/pipeline/ingest.py (+300 lines)

## TEST RESULTS

- Sample trader: 0 eSports trades → 515 eSports detail trades after fix
- 36/200 traders backfilled so far (remaining ~3+ hours)
- 228 eSports detail trades captured (vs 0 before)
- Pre-existing 9 test failures unchanged
