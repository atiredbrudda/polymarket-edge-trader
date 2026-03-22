# Plan 23-02 Summary: Analyze CLI Command

**Date:** 2026-03-14  
**Phase:** 23 (Contextual Analyze Command)  
**Plan:** 02  
**Branch:** worker/23-02-analyze-cli-command

---

## What Was Built

Implemented the `polymarket analyze` CLI command with two execution modes:

1. **Batch mode** (`polymarket analyze`): Processes traders from the latest discover batch (first_seen within 60s of max)
2. **Crawler mode** (`polymarket analyze --crawl`): Exhaustively processes all traders in the database with cursor-based resumption

## Key Implementation Details

### Files Changed
- `src/cli/commands.py`: Added analyze command with `_run_batch_mode()` and `_run_crawl_mode()` helper functions
- `tests/test_analyze.py`: Added ANALYZE-07 integration test

### Alpha Threshold (Locked Decision)
- Alpha = `total_resolved >= 5` AND `win_rate >= 60.0%` (Decimal comparison)
- A trader "has alpha" if ANY entity row meets both conditions

### Batch Mode Output
```
  0xABCD1234... — 1 alpha found
  0xEFGH5678... — no alpha
Batch complete: X/Y traders with alpha
```

### Crawler Mode Features
- Loads cursor from `.planning/analyze_cursor.json` on startup
- Skips traders where `address <= cursor["last_trader"]`
- Saves cursor after each trader (last_trader, last_entity, last_game, processed)
- Clears cursor on successful completion
- Progress display: "Processing 33/85: 0xABCD..."

### Dependencies Imported
```python
from src.org_mapping.queries import (
    get_entity_alpha_for_trader,
    upsert_entity_alpha,
    build_batch_trader_list,
)
from src.org_mapping.crawler import load_cursor, save_cursor, clear_cursor
```

## Test Results

All 7 tests in `tests/test_analyze.py` passing:
- ANALYZE-01: `test_entity_alpha_basic` — get_entity_alpha_for_trader returns correct wins/losses
- ANALYZE-02: `test_direction_mapping` — LONG→team_a, SHORT→team_b mapping
- ANALYZE-03: `test_excludes_unresolved` — Excludes resolved=False, outcome=void, market_type!=match
- ANALYZE-04: `test_upsert_idempotent` — upsert_entity_alpha called twice produces exactly 1 row
- ANALYZE-05: `test_batch_mode_filters_by_first_seen` — build_batch_trader_list filters by first_seen within 60s
- ANALYZE-06: `test_crawler_cursor` — save_cursor/load_cursor/clear_cursor round-trip
- ANALYZE-07: `test_analyze_cli` — Integration test for CLI analyze command

## Deviations from PLAN.md

None. Implementation matches the spec exactly.

## Known Issues

None.

## Follow-up Items

None. Phase 23 is complete after this plan.
