# Phase 30 Plan 01 Summary: Token Catalog Expansion

## What Was Built

Implemented an enhanced token catalog builder that can fetch events from ALL categories (not just eSports) from the Gamma API, dramatically increasing token catalog coverage from 11.4% to 90%+ target.

### Files Modified

1. **`src/catalog/builder.py`** — Enhanced TokenCatalogBuilder class
   - Added `esports_only` parameter to constructor (default: False for all-categories mode)
   - Updated `_fetch_all_events()` to conditionally filter by tag_id=64 for eSports-only mode
   - Added `_extract_category()` method to extract category from event tags or category field
   - Updated `build()` method to populate niche_slug, node_path, depth, and market_type from event data
   - Changed from eSports-only hardcoded to configurable mode

2. **`src/cli/commands.py`** — Added `build-token-catalog` CLI command
   - New command: `polymarket build-token-catalog`
   - Options: `--esports-only`, `--batch-size`, `--verbose`
   - Fetches all events (active + closed) from Gamma API
   - Extracts token_id → condition_id mappings with category information
   - Idempotent — clears and rebuilds catalog each run
   - Progress logging for large builds

3. **`tests/test_catalog_builder.py`** — Complete test suite rewrite (12 tests)
   - Tests for eSports-only mode
   - Tests for all-categories mode  
   - Tests for category extraction from tags and category field
   - Tests for zero token ID skipping
   - Tests for idempotency
   - Tests for string vs list clobTokenIds format

## Problem Solved

**The bottleneck:** Only 136K tokens in catalog (11.4% coverage) because the builder only fetched eSports events (tag_id=64). This caused 72% of trades to be orphaned with `graph_` placeholders.

**Root cause:** Token catalog lookup fails for non-eSports markets, forcing fallback to synthetic `graph_{txHash}_{assetId}` IDs that cannot be matched to real markets for resolution.

**Solution:** 
- Fetch ALL events from Gamma API (not just eSports)
- Extract category information from event tags
- Build comprehensive token catalog across all categories
- Expected coverage: 136K → 900K+ tokens (11.4% → 90%+)

## Key Decisions

1. **Use Gamma API (not CLOB API)** — The roadmap mentioned CLOB API `/tokens` endpoint, but it returns 404. Gamma API `/events` endpoint provides complete market + token data for all categories.

2. **All-categories mode as default** — Changed default behavior from eSports-only to all-categories to maximize catalog coverage. eSports-only mode kept for backwards compatibility.

3. **Category from tags** — Extract category from event tags (authoritative Polymarket classification) with fallback to category field.

4. **Clear and rebuild** — Catalog is cleared on each build run (not incremental) to handle category changes and ensure consistency.

5. **Store category as niche_slug** — Each token gets its event's category as niche_slug (e.g., "sports", "politics", "crypto", "esports").

## Test Results

```
12 passed, 0 failed
```

All 12 new tests pass:
- Builder initialization (2 tests)
- is_built() checks (2 tests)
- eSports-only mode (1 test)
- All-categories mode (1 test)
- Category extraction (2 tests)
- Edge cases (4 tests)

## Usage

```bash
# Build complete catalog from all categories (NEW DEFAULT)
polymarket build-token-catalog

# Build eSports-only catalog (legacy mode)
polymarket build-token-catalog --esports-only

# With verbose logging
polymarket build-token-catalog --verbose

# Custom batch size
polymarket build-token-catalog --batch-size 100
```

## Expected Impact

**Before:**
- Token catalog: 136K rows (eSports only)
- Coverage: 11.4%
- Trades with `graph_` placeholders: 72.8%

**After (this plan):**
- Token catalog: 900K+ rows (all categories)
- Coverage: 90%+ (target)
- Graph_ placeholder rate: Will drop after migration in Phase 30-02

**Next phase impact:**
- Phase 30-02 will migrate 1.8M `graph_` trades to real `condition_id`s
- Expected matched trades: 500K-1M (from 27% → 80%+)

## Known Issues / Limitations

1. **Category granularity** — Currently stores root category only (e.g., "sports"), not subcategory taxonomy. Can be enhanced later with market question pattern matching.

2. **No market_type detection** — Defaults all markets to "prop" type. Could be improved by parsing market question structure.

3. **Large API response** — Fetching all events may take several minutes. No progress bar yet (only logging).

4. **Rate limiting** — Uses 0.1s delay between API calls. May need tuning based on API behavior.

## Follow-up Recommendations

1. **Run against production DB** — Execute `polymarket build-token-catalog` to see actual token count

2. **Phase 30-02: Migration script** — Build script to update `graph_` trades with resolved `condition_id`s from new catalog

3. **Progress bar** — Add rich.progress bar for better UX during large builds

4. **Incremental updates** — Consider incremental mode (only fetch new events) instead of full rebuild

5. **Validate catalog coverage** — Measure what % of `graph_` trades can now be matched

## Files Changed Summary

| File | Lines Changed | Type |
|------|---------------|------|
| src/catalog/builder.py | ~150 modified | Enhanced builder |
| src/cli/commands.py | +80 | New CLI command |
| tests/test_catalog_builder.py | Complete rewrite | 12 tests |

**Total:** ~230 lines of production code, 162 lines of tests

## Next Plan

**Phase 30-02:** Migration script to update `Trade.market_id` from `graph_...` → real `condition_id` using the expanded token catalog.

---

**Status:** Ready for review  
**Branch:** worker/30-graph-trade-resolution-phase1  
**Plan:** 30-01
