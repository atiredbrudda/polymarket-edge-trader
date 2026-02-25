# Phase 17-01: Deep Token Classification from Gamma Event Tags

## Summary

Implemented deep token classification that enriches `token_catalog` with `node_path` and `depth` from Gamma event tags, and wired it to a `classify-tokens` CLI command.

## Changes

### New Files

- **src/gamma/classification.py** — Classification module with:
  - `_extract_classification(tags)` — Extracts node_path and depth from Gamma event tags
  - `classify_tokens_from_gamma_events(session)` — Bulk-updates token_catalog with classifications

- **tests/test_gamma_classification.py** — TDD test suite:
  - 8 unit tests for `_extract_classification` 
  - 7 integration tests for `classify_tokens_from_gamma_events` (mock-based)
  - 1 idempotency test using in-memory SQLite

### Modified Files

- **src/cli/commands.py** — Added `classify-tokens` CLI command

## Key Implementation Details

- `node_path` format: slash-separated lowercase slugs (e.g., 'esports/cs2' or 'esports/cs2/iem-katowice-2024')
- `depth`: 1=game, 2=tournament, 3=team
- Depth is capped at 3 (team level)
- Only updates tokens where new depth > existing depth (idempotent)
- Bulk UPDATE via single `session.execute()` call

## Verification

- All 16 tests pass
- CLI command registered and working: `python -m src.cli.commands classify-tokens --help`
- No regressions in full test suite
