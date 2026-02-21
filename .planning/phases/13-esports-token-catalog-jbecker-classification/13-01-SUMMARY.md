# Phase 13-01: TokenCatalog ORM Model & Builder

## Summary

Built the token catalog infrastructure — a `token_catalog` SQLite table and `TokenCatalogBuilder` class that scans all 41 JBecker markets parquet files via DuckDB, classifies each market question with the existing `PatternMatcher`, and writes 817k token rows in a single idempotent transaction. This is the bridge between JBecker trade token IDs and Polymarket taxonomy.

## Changes

### src/db/models.py

- Added `TokenCatalog` ORM model with 7 columns: `token_id` (PK), `condition_id`, `question`, `niche_slug`, `node_path`, `depth`, `market_type`
- Two indexes: `ix_catalog_condition` and `ix_catalog_niche`
- Auto-created by existing `Base.metadata.create_all(engine)` call in CLI

### src/catalog/__init__.py

- New package marker file

### src/catalog/builder.py

- `TokenCatalogBuilder` class with `is_built(session)` and `build(session)` methods
- DuckDB scans all `markets_*.parquet` in one SQL query (~0.5s for 408k markets)
- Classifies each question with `PatternMatcher` — esports markets get `niche_slug='esports'`, `node_path`, `depth`; non-esports get `NULL`
- Internal `_scan_parquet()` method extracted for testability
- `INSERT OR IGNORE` makes `build()` fully idempotent

### tests/test_catalog_builder.py

- 6 unit tests using in-memory SQLite and monkeypatched `_scan_parquet()`
- Covers: empty/built detection, esports classification, non-esports classification, idempotency, zero-token-id skipping

## Verification

```
from src.db.models import TokenCatalog  # ✓
from src.catalog.builder import TokenCatalogBuilder  # ✓
pytest tests/test_catalog_builder.py -v  # all 6 tests pass
```
