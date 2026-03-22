# Phase 19 Plan 19-01: Self-Healing Token Catalog - Implementation

**Date:** 2026-02-27
**Status:** COMPLETE
**Worker:** Worker model

## Summary

Implemented the 3-tier catalog patcher as a standalone module with full test coverage.

## Files Created

- `src/catalog/patcher.py` — NEW module with `patch_missing_catalog_entries()` function
- `tests/test_catalog_patcher.py` — NEW with 12 TDD tests

## Implementation Details

### 3-Tier Lookup Logic

1. **Tier 1 (local):** Join markets.tokens → gamma_events.clob_token_ids → extract tags
2. **Tier 2 (API):** Call Gamma API `/markets?conditionId=` with batch size 20
3. **Tier 3 (fallback):** Insert with category from markets.category, node_path=NULL

### Key Design Decisions

- Uses `_extract_classification()` from `src.gamma.classification` (no hand-rolled tag parsing)
- Gamma event index built once per patch call for O(1) Tier 1 lookups
- INSERT OR IGNORE pattern for idempotency
- gamma_client=None handled gracefully (Tier 2 skipped, all go to Tier 3)

### Test Coverage

All 12 tests pass:
- test_no_gaps_returns_zero
- test_tier1_local_hit
- test_tier1_null_tokens_falls_to_tier2
- test_tier2_api_hit_with_esports_tags
- test_tier2_api_hit_no_esports_tags
- test_tier3_fallback_on_api_failure
- test_idempotent_second_run_inserts_nothing
- test_both_token_ids_inserted_per_condition
- test_niche_slug_from_category_sports
- test_esports_category_case_insensitive
- test_unknown_category_uses_api_tag
- test_full_patch_flow_integration

## Verification

```bash
python -m pytest tests/test_catalog_patcher.py -v
# 12 passed

python -c "from src.catalog.patcher import patch_missing_catalog_entries; print('OK')"
# OK
```

## Notes

- Pre-existing test failures in test_catalog_builder.py are unrelated (fixture issues)
- All new tests pass, no regressions introduced
