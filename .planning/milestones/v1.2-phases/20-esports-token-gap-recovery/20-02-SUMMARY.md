# Phase 20 Plan 02 Summary

## Objective
Fix the broken populate-tokens block in `src/pipeline/ingest.py` (lines 1764-1804) by replacing the non-functional `GET /markets?conditionId=X` API call with events-based lookup using `_fetch_esports_events_index()` from `src/catalog/recovery.py`.

## Changes Made

### src/pipeline/ingest.py (MODIFIED)
Replaced broken token population block (lines 1765-1804):

**Before (broken):**
- Called `GET /markets?conditionId=X` which ignores the conditionId parameter
- Batch loop with BATCH_SIZE=20, making multiple API calls
- `time.sleep(0.05)` per batch
- Required `self.gamma_client` guard

**After (fixed):**
- Imports and calls `_fetch_esports_events_index()` from `src.catalog.recovery`
- Fetches events index ONCE for all catalog_condition_ids (not per-batch)
- No batch loop — dict lookup is O(1) per condition_id
- No `time.sleep()` needed (single API call inside _fetch_esports_events_index)
- Removed `self.gamma_client` guard (events lookup doesn't require it)
- Wrapped in try/except to avoid breaking backfill if events API fails
- Token format unchanged: `json.dumps(tokens)` where tokens is `[{"token_id": tid, "outcome": ""}]`

## Key Differences
| Aspect | Before | After |
|--------|--------|-------|
| API calls | O(markets/20) per trader | O(1) per trader |
| Endpoint | `/markets?conditionId=X` (broken) | `/events?tag_id=64` (working) |
| Rate limiting | `time.sleep(0.05)` per batch | None needed |
| gamma_client required | Yes | No |

## Verification
- Broken endpoint removed: `grep 'params=\[("conditionId"'` returns empty
- Replacement present: `_fetch_esports_events_index` found at lines 1783, 1785
- No syntax errors: `ingest.py imports OK`
- All catalog tests pass: 26/26 (recovery, patcher, cli_catalog)
- `polymarket score` runs successfully (4 games scored, 15 entries computed)

## Test Results
- 26/26 relevant tests pass (test_catalog_recovery.py, test_catalog_patcher.py, test_cli_catalog.py)
- 5 pre-existing failures in test_catalog_builder.py unrelated to this change

## Notes
- Events index fetched once per trader backfill invocation (not per condition_id)
- Future JBecker backfills will no longer create null-token gaps for eSports catalog-path markets
- After user runs `polymarket recover-catalog` (Plan 20-01) then this fix is merged, `polymarket score` will re-score all traders including the 1,451 affected
- The 156 null-token markets with 3,633 trades will be classifiable after recovery + this fix

## Reviewer Notes
- Plan 20-01 and 20-02 must be merged together (20-01 provides recovery.py, 20-02 uses it)
- Both branches ready: worker/20-esports-token-gap-recovery contains both plans
