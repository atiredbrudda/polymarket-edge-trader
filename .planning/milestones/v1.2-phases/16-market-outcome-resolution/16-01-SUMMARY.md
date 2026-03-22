# Plan 16-01: Fix Token Order and Implement Outcome Resolution

## Implemented

### 1. Fixed Order-Destroying Sort in persist.py

Changed line 37 from:
```python
clob_token_ids_json = json.dumps(sorted(set(clob_token_ids)))
```

To:
```python
clob_token_ids_json = json.dumps(list(dict.fromkeys(clob_token_ids)))
```

**Rationale:** `sorted(set(...))` alphabetically reorders token IDs, breaking their positional correspondence with outcome_prices. Resolution logic uses `zip(clob_token_ids, outcome_prices)`, so order is critical. `dict.fromkeys()` deduplicates while preserving insertion order (Python 3.7+).

### 2. Re-ingested Gamma Events

Ran `polymarket ingest-events` after the fix:
- Downloaded: 8,547 events
- Upserted: 8,547 events

### 3. Added src/gamma/resolution.py

Three functions implemented:

**`determine_winner(clob_token_ids, outcome_prices) -> str | None`**
- Returns token_id with outcome_price closest to 1.0 (> 0.5 threshold)
- Returns None if inputs are malformed or no clear winner
- Uses Decimal for precise price comparison

**`classify_token_outcome(token_id, winning_token_id) -> str`**
- Returns "YES" if token_id == winning_token_id
- Returns "NO" otherwise

**`resolve_market_outcomes(session) -> dict[str, int]`**
- Builds in-memory `{token_id: Market}` lookup from markets.tokens JSON
- Iterates through all gamma_events, calls determine_winner for each
- Updates market.outcome for each matched token
- Returns counts: {"resolved": N, "skipped_events": M, "skipped_tokens": K}

### 4. Added TDD Test Suite

Created `tests/test_gamma_resolution.py` with 22 tests:
- 11 tests for `determine_winner()` (including edge cases)
- 3 tests for `classify_token_outcome()`
- 8 tests for `resolve_market_outcomes()`

All tests pass.

## Verification

1. `grep -n "clob_token_ids_json" src/gamma/persist.py` shows `dict.fromkeys(clob_token_ids)`
2. `polymarket ingest-events` completes successfully
3. `python -m pytest tests/test_gamma_resolution.py -v` shows 22 passed
4. No new test regressions

## Files Changed

- `src/gamma/persist.py` — Fixed token ID order (1 line changed)
- `src/gamma/resolution.py` — NEW resolution logic (+114 lines)
- `tests/test_gamma_resolution.py` — NEW TDD tests (+240 lines)
