# Phase 13-02: Catalog Integration in JBecker Backfill

## Summary

Wired the token catalog into `ingest_trader_history_jbecker()` so esports trades from the JBecker dataset are classified and stored correctly. The pipeline now auto-builds the catalog on first run, looks up each trade's token in the catalog, and creates `Market` + `MarketClassification` records for esports trades without hitting the Gamma API. Non-esports and unknown-token trades fall through to the existing Gamma API lookup path.

## Changes

### src/pipeline/ingest.py

- Added `_catalog_built = False` instance flag on `IngestionPipeline`
- `ingest_trader_history_jbecker()` now auto-builds catalog on first call if `token_catalog` is empty (cached via `_catalog_built` flag — subsequent calls skip the build)
- Catalog lookup: for each JBecker trade, look up `token_id` in `token_catalog`
  - **Esports hit**: create `Market` + `MarketClassification` records using catalog data; `taxonomy_node_id` is `NULL` if `TaxonomyNode` row doesn't exist
  - **Miss / non-esports**: fall through to existing Gamma API lookup
- Check-first pattern prevents duplicate `Market` / `MarketClassification` rows
- Trades with `token_id` not in catalog are logged as warning and skipped (no crash)

### tests/test_catalog_integration.py

- Integration tests for the catalog-backed JBecker backfill path
- Covers: auto-build on first call, skip on subsequent calls, esports trade creates Market + MarketClassification, non-esports falls through to Gamma, no duplicate rows, missing token_id is warned and skipped

## Verification

```
pytest tests/test_catalog_integration.py -v  # all tests pass
```

Key invariants:
- `_catalog_built` flag prevents redundant rebuild on repeated ingest calls ✓
- Esports trades classified entirely from catalog (zero Gamma API calls for known tokens) ✓
- Duplicate Market rows never created (check-first) ✓
