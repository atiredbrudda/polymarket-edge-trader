# Phase 08 Plan 03 - Enrichment Test Coverage

## What Was Built

TDD integration tests for Phase 8 signal enrichment fields. Created `tests/test_enrichment.py` with 9 test functions in a `TestEnrichment` class covering all ENRC requirements.

## Test Coverage

| Test | Requirement | Description |
|------|-------------|-------------|
| test_schema_columns_present | ENRC-01 | Verifies signals table has all 4 new columns after init_database() |
| test_clv_dominant_count_positive_and_negative | ENRC-05 | clv_dominant_count=1 when one trader positive, one negative |
| test_clv_dominant_count_all_negative | ENRC-05 | clv_dominant_count=0 when all Q5 traders have negative clv_zscore |
| test_tier_consider | ENRC-08 | tier='CONSIDER' when q5_count=2 |
| test_tier_act | ENRC-08 | tier='ACT' when q5_count>=3 |
| test_entry_prices | ENRC-06/07 | avg_entry_price and min_entry_price calculations |
| test_upsert_signal_all_fields | ENRC-01/02/03/04/09 | upsert persists all 4 fields + avg_score retention |
| test_full_round_trip | ENRC-01/02/03/04/09 | detect → upsert → read preserves all fields |
| test_upsert_update_preserves_first_seen | ENRC-09 | Update overwrites enriched fields, preserves first_seen |

## Key Decisions

1. **Direct SQL for market setup**: Used direct `db["markets"].insert()` with `end_date='2099-01-01T00:00:00Z'` for open market tests instead of `create_market()` helper (which defaults to yesterday's date and fails the convergence query's end_date filter).

2. **Manual lift_scores insertion for custom clv_zscore**: For tests requiring negative clv_zscore values, inserted `lift_scores` directly instead of using `create_q5_trader()` (which defaults to clv_zscore=1.0).

3. **_FIXED_COMPUTED_AT for computed_at**: All `lift_scores.computed_at` use the shared `_FIXED_COMPUTED_AT` constant so the MAX(computed_at) subquery in `detect_convergence()` matches all test traders.

## Test Results

```
tests/test_enrichment.py: 9 passed
Full suite (tests/): 87 passed
```

## Deviations from PLAN.md

None. Implementation matches plan spec exactly.

## Pre-Existing Fix

Fixed `test_extract_empty_result_no_crash` in `tests/test_scoring_extraction.py` — added `avg_exit_price` to expected columns list (missing from Phase 7 avg_exit_price migration). This was a pre-existing gap unrelated to Phase 8.

## Known Issues

None.
