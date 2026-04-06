# Pipeline Todo #4 - Store clobTokenIds in DB for classify_tokens

## What was built

Eliminated redundant 96K Gamma API call from `classify_tokens` command by:
1. Adding `clob_token_ids` column to `markets` table via migration
2. Storing `clobTokenIds` from Gamma API in `ingest_events` command
3. Modifying `classify_tokens` to read from database instead of fetching from API

## Key decisions

- **Store in markets table (not gamma_events)**: Token catalog needs condition_id → clob_token_ids mapping, and markets table is the canonical source for market metadata
- **JSON string storage**: Store as JSON array string (e.g., `'["token1", "token2"]'`) for flexibility
- **Remove async/asyncio from classify_tokens**: No longer needed since we're doing DB reads instead of async API calls
- **Function rename**: `_classify_tokens_async` → `_classify_tokens_from_db` to reflect new behavior

## Deviations from PLAN.md

None - implemented exactly as specified in 99-04-PLAN.md

## Test results

```
100 passed in 1.19s
```

New tests added:
- `test_classify_tokens_db.py` - 3 tests (CTDB-01 through CTDB-03)
- Updated `test_integration.py::test_classify_tokens_uses_clob_token_ids` to use DB-first approach

All tests verify:
- classify_tokens reads from DB, zero Gamma API calls
- classify_tokens fails gracefully if markets table is empty
- classify_tokens handles NULL clob_token_ids with synthetic fallback
- Token IDs match clob_token_ids from database

## Known issues or follow-up items

None - implementation is complete and backwards-compatible. Existing workflows:
1. `ingest-events` → `classify-tokens` still works (now faster, no redundant API calls)
2. Token catalog uses real clobTokenIds from first ingest (no synthetic IDs for real markets)
3. Synthetic fallback still available for markets without clobTokenIds

## Files changed

- `src/polymarket_analytics/db/schema.py` - migration to add `clob_token_ids` column
- `src/polymarket_analytics/commands/ingest_events.py` - store `clob_token_ids` as JSON
- `src/polymarket_analytics/commands/classify_tokens.py` - read from DB, removed async/API calls
- `tests/test_classify_tokens_db.py` (NEW) - 3 tests for DB-first behavior
- `tests/test_integration.py` - updated TCAT-04 test for DB-first approach
