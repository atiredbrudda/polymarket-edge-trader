# Phase 17-02: Resolution Counter Fix and classify_token_outcome Integration

## Summary

Fixed three code quality issues in resolution.py and test_gamma_resolution.py:
1. Fixed the misleading counter (now shows unique market count, not inflated token count)
2. Integrated classify_token_outcome() instead of inline if/elif logic
3. Replaced weak mock-based idempotency test with in-memory SQLite test

## Changes

### src/gamma/resolution.py

- Added `markets_resolved_set: set[str]` to track unique market condition_ids
- Integrated `classify_token_outcome()` instead of inline if/elif logic
- Updated return dict to include both `"resolved"` (token updates) and `"markets_resolved"` (unique markets)
- Updated logger message to show both counts

### src/cli/commands.py

- Updated `resolve_outcomes` CLI to display both unique market count and token updates

### tests/test_gamma_resolution.py

- Removed `TestClassifyTokenOutcome` class (3 tests removed — function is now implicitly tested)
- Removed `classify_token_outcome` from imports
- Replaced mock-based `test_idempotent_re_run` with in-memory SQLite test that verifies:
  - Market outcome is set to "YES" after first run
  - Market outcome remains "YES" after second run (idempotency)
  - Both runs report same resolution count

## Verification

- All 35 tests pass (19 resolution + 16 classification)
- CLI command shows both unique market count and token updates
