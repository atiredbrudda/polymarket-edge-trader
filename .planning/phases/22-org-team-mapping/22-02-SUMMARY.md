# Plan 22-02 Summary: team-stats CLI Command

**Phase:** 22 (Org-Team Mapping)
**Plan:** 02
**Date:** 2026-03-14
**Status:** Complete

## What Was Built

CLI command `polymarket team-stats <address>` that displays per-team win/loss statistics for a trader.

1. **CLI command** (`src/cli/commands.py:2390-2458`)
   - Calls `compute_and_upsert_team_stats()` to persist stats to `trader_team_stats` table
   - Displays Rich table with columns: Team, Game, Wins, Losses, Resolved, Win Rate%
   - Prints join coverage diagnostic: "X team(s) matched from Y total resolved positions"
   - Handles empty results gracefully: "No team stats found for {address}" with explanatory message
   - Sorted by total_resolved descending

2. **Integration test** (`tests/org_mapping/test_cli.py`)
   - MAP-07: Verifies query layer returns correct data, upsert persists to DB
   - Uses in-memory SQLite (no real DB or API calls)

## Key Decisions

1. **Compute on every call** — `compute_and_upsert_team_stats()` is called on every `team-stats` invocation, ensuring fresh data. The upsert is idempotent so repeated calls are safe.

2. **Join coverage diagnostic** — Shows how many team+game combinations were computed vs total resolved positions. Helps user understand data quality (e.g., if entities weren't extracted for these markets).

3. **Graceful empty handling** — When no stats found, shows trader's resolved position count and suggests running `discover` to extract entities. Exit code 0 (not an error).

## Test Results

```
7 passed, 19 warnings in 0.63s
(MAP-01 through MAP-07)
```

All warnings are deprecation notices for `datetime.utcnow()` — non-blocking.

## Deviations from Plan

None. Implementation matches PLAN.md spec exactly.

## Files Changed

- `src/cli/commands.py` (MODIFIED — team-stats command, +68 lines)
- `tests/org_mapping/test_cli.py` (NEW — integration test)

## Known Issues

None.

## Verification

```bash
# Help text renders correctly
polymarket team-stats --help

# Test suite passes
python -m pytest tests/org_mapping/ -x -q

# CLI import sanity
python -c "from src.cli.commands import cli; print('OK')"
```
