# Phase 13-03: catalog-stats CLI Command

## Summary

Added `polymarket catalog-stats` command that reports the state of the token catalog — total rows, esports-classified count, per-game breakdown by `node_path`, and unclassified count. Handles empty catalog gracefully (shows zeros). Completes Phase 13 by giving operators visibility into catalog coverage.

## Changes

### src/cli/commands.py

- Added `catalog_stats` Click command registered on the `cli` group as `catalog-stats`
- Queries `token_catalog` table for:
  - Total row count
  - Count where `niche_slug='esports'`
  - Per-game breakdown grouped by `node_path` game segment
  - Count where `niche_slug IS NULL` (unclassified)
- Output rendered via Rich `Table` / `Console`
- Graceful zero output when catalog is empty

### tests/test_cli_catalog.py

- CLI tests for `catalog-stats` using Click test runner and in-memory SQLite
- Covers: empty catalog shows zeros, populated catalog shows correct counts, per-game rows appear in output

## New Command

```
polymarket catalog-stats
```

Example output:
```
Token Catalog Stats
────────────────────
Total tokens:      817,432
Esports tokens:     42,186
Unclassified:      775,246

Esports by game
───────────────
CS:GO              18,204
Valorant            9,112
Dota 2              7,440
League of Legends   4,890
Other               2,540
```

## Verification

```
polymarket catalog-stats  # ✓ runs without error, shows zeros on empty catalog
pytest tests/test_cli_catalog.py -v  # all tests pass
```
