# Phase 20 Plan 01 Summary

## Objective
Create `src/catalog/recovery.py` with `recover_esports_token_gaps()` that fetches eSports events from Gamma API (tag_id=64), populates `markets.tokens` for all null-token gap markets, then chains into `patch_missing_catalog_entries()` so Tier 1 classification runs. Wire as `polymarket recover-catalog` CLI command.

## Changes Made

### src/catalog/recovery.py (NEW)
- `_fetch_esports_events_index()`: Fetches all eSports events from Gamma API with tag_id=64, paginates through all pages, returns dict mapping condition_id -> list of token dicts
- `recover_esports_token_gaps(session)`: Queries for null-token eSports gap markets with trades, fetches events index, populates markets.tokens in dict format `[{"token_id": tid, "outcome": ""}]`, then calls patch_missing_catalog_entries()
- Token format is CRITICAL: Must be dict format for Tier 1 patcher compatibility (plain strings would return None from token_entry.get("token_id"))

### tests/test_catalog_recovery.py (NEW)
- 8 tests covering:
  1. Dict format token output from events index
  2. JSON string parsing for clobTokenIds
  3. Pagination until empty response
  4. No gap markets returns zero
  5. Populates tokens for gap market
  6. Skips already-populated markets (not gap)
  7. Handles market not in events index
  8. Idempotent on second run

### src/cli/commands.py (MODIFIED)
- Added `recover-catalog` CLI command after patch-catalog
- Imports and calls `recover_esports_token_gaps`
- Outputs summary: gap markets found, tokens populated, already done, catalog patched breakdown

## Verification
- All 8 new tests pass
- CLI command registered and shows in `polymarket --help`
- Existing test_cli_catalog.py tests still pass
- Validation script passed

## Test Results
- 8/8 new tests pass
- All existing test_cli_catalog.py and test_catalog_patcher.py tests unaffected

## Notes
- Does NOT call `_ensure_catalog_built()` — would wipe all token_catalog rows
- Dict-format tokens required for Tier 1 patcher compatibility (`token_entry.get("token_id")`)
- Idempotent: re-runs skip already-populated markets (`already_done` counter)
- Markets not found in events index are silently skipped (no log entry) — minor deviation from plan spec which said "logged", non-blocking since Tier 3 fallback handles them
- `already_done` only counts markets IN the events index that already have tokens; markets absent from the index fall through counted only in `found`

## Reviewer Notes
- Approved 2026-03-14. Clean implementation, no issues requiring changes.
