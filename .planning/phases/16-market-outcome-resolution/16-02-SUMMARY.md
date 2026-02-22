# Plan 16-02: Resolve Outcomes CLI Command

## Implemented

### 1. Fixed outcome_prices Extraction in persist.py

The Gamma API stores `outcomePrices` at the **market** level, not the event level. The original code was doing:
```python
outcome_prices = json.dumps(event.get("outcomePrices") or [])
```

Which always returned `[]` because `outcomePrices` doesn't exist at event level.

Fixed by adding `_extract_tokens_and_prices()` function that:
- Iterates through all markets in the event
- Extracts both `clobTokenIds` and `outcomePrices` from each market
- Maintains positional correspondence between tokens and prices
- Deduplicates tokens while preserving order (first occurrence wins)

### 2. Added resolve-outcomes CLI Command

Added to `src/cli/commands.py`:
- Command: `polymarket resolve-outcomes`
- Reads gamma_events table and populates markets.outcome
- Resolution logic: token with price closest to 1.0 (> 0.5) wins
- Prints summary: resolved, skipped events, skipped tokens

### 3. Re-ingested Gamma Events

Ran `polymarket ingest-events` after fixing persist.py:
- 8,519 events now have outcome_prices populated (vs 0 before)
- Token-price correspondence verified

## Results

**First run:**
```
Done. 21594 markets resolved.
  Events skipped (no clear winner): 268
  Tokens skipped (not in catalog):  66250
```

**Idempotency (second run):**
```
Done. 21594 markets resolved.
  Events skipped (no clear winner): 268
  Tokens skipped (not in catalog):  66250
```

**Database verification:**
- Markets with outcome=YES: 3,648
- Markets with outcome=NO: 7,149
- Markets with outcome=NULL: 106,401

Total unique markets resolved: 10,797 (3,648 + 7,149)

## Verification

1. Command help: `polymarket resolve-outcomes --help` — correct output
2. First run: 21,594 token updates resolved
3. Idempotency: Second run produces identical counts
4. Database check: Outcomes populated correctly
5. No new test regressions

## Files Changed

- `src/gamma/persist.py` — Fixed outcome_prices extraction (+53/-13 lines)
- `src/cli/commands.py` — Added resolve-outcomes command (+59 lines)

## Bug Fix Note

The original Plan 15-01 incorrectly stated that `outcomePrices` was at the event level. The actual API structure has it at `markets[].outcomePrices`. This was discovered during the 16-02 smoke test when all events showed "no clear winner" because outcome_prices was always empty.
