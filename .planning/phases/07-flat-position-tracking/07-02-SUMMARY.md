# Phase 07 Plan 02 - FLAT-First Resolution + CLV Fix

## What Was Built

Wired the three computation layers so FLAT positions flow through the full pipeline: resolved by exit price, included in scoring extraction, and scored with correct CLV.

### Key Changes

**resolution.py:**
- Added FLAT-first UPDATE pass before market-outcome pass
- FLAT positions with `avg_exit_price IS NOT NULL` resolve: `pnl = size * (avg_exit_price - avg_entry_price)`
- Outcome determination: WIN if pnl > 0, LOSS if pnl < 0, FLAT if pnl == 0
- Relaxed dependency checks: no longer blocks when markets have no outcomes but FLAT positions are resolvable
- `calculate_pnl()` helper: added optional `avg_exit_price` parameter for FLAT positions
- Return count now includes both FLAT-resolved + market-outcome-resolved

**extraction.py:**
- Added `p.avg_exit_price` to SELECT list
- Added "avg_exit_price" to fallback empty DataFrame columns

**metrics.py:**
- `calculate_clv()` now uses `avg_exit_price` as `resolution_price` for FLAT rows
- Added `direction` and `avg_exit_price` to docstring
- Drops rows where `resolution_price` is still NaN (edge case guard)

**Tests:**
- `test_clv_flat_position_with_exit_price()`: Verifies CLV=0.75 for FLAT trader (entry=0.40, exit=0.70)
- `test_resolve_flat_with_exit_price()`: Verifies FLAT position resolves with correct pnl and outcome
- `test_calculate_pnl_flat_with_exit_price()`: Verifies Python helper matches SQL formula

## Key Decisions

1. **FLAT-first UPDATE order**: FLAT positions are resolved BEFORE market-outcome positions. This ensures FLAT positions with exit trades are excluded from the subsequent market-outcome UPDATE (handled by `WHERE resolved = 0`).

2. **Dependency check relaxation**: The "no market outcomes" check now accounts for FLAT positions. Only fails when NEITHER market-outcome path NOR FLAT path can resolve anything.

3. **Backward compatibility**: `calculate_pnl()` maintains backward compatibility - FLAT without `avg_exit_price` returns 0 (old behavior).

## Test Results

```
tests/test_resolve_positions.py: 7 passed
tests/test_scoring_metrics.py: 14 passed
Total: 21 passed in modified files
```

Full suite: 64 passed, 7 pre-existing failures (unrelated to this plan - empty DataFrame column type coercion issues in detection/scoring integration tests)

## Deviations from PLAN.md

None. Implementation matches spec exactly.

## Known Issues / Follow-up

- Pre-existing test failures in `test_detection.py` and `test_scoring_integration.py` related to empty DataFrame handling (not caused by this plan)
- These will be addressed in Plan 07-03 (tests) or a separate cleanup task

## Checklist

- [x] Tests pass (pytest)
- [x] Linter clean (ruff check src/ tests/) - 28 pre-existing errors, none in modified files
- [x] No debug artifacts
- [x] STATE.md NOT touched (reviewer-only)
- [x] SUMMARY.md written
