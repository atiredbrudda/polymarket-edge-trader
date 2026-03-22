# Plan 22-01 Summary: TraderTeamStats Model + Query Layer

**Phase:** 22 (Org-Team Mapping)
**Plan:** 01
**Date:** 2026-03-14
**Status:** Complete

## What Was Built

Core data model and query functions for per-team trader statistics:

1. **TraderTeamStats ORM model** (`src/org_mapping/models.py`)
   - Schema: id, trader_address, team_name, game, wins, losses, total_resolved, win_rate, computed_at
   - Unique index on (trader_address, team_name, game) to support cross-game teams like "Team Liquid"
   - Follows SQLAlchemy 2.0 declarative style

2. **Query functions** (`src/org_mapping/queries.py`)
   - `get_team_stats_for_trader(session, trader_address)` — returns list of {team_name, game, wins, losses, total_resolved, win_rate}
   - `compute_and_upsert_team_stats(session, trader_address)` — computes and persists stats, returns row count
   - Direction convention documented: LONG=team_a (YES side), SHORT=team_b (NO side)
   - Filters: resolved=True, outcome in (win/loss), market_type='match' only

3. **6 unit tests** (`tests/org_mapping/test_queries.py`)
   - MAP-01: Basic wins/losses aggregation
   - MAP-02: LONG=team_a, SHORT=team_b direction mapping
   - MAP-03: Excludes unresolved/void/flat positions
   - MAP-04: Excludes prop-type markets
   - MAP-05: Upsert idempotency
   - MAP-06: Canonical team names stored

## Key Decisions

1. **Game included in unique key** — Team Liquid CS2 ≠ Team Liquid Dota 2. This prevents merging stats across different games.

2. **Uses existing `calculate_win_rate()` from `src/evaluation/metrics.py`** — No re-implementation of win rate logic.

3. **SELECT-then-UPDATE upsert pattern** — Matches existing project convention (see Phase 21 discover command).

4. **Synthetic position objects for win_rate calculation** — Build `_Pos` wrapper objects with resolved/outcome attributes to reuse metrics.calculate_win_rate().

## Test Results

```
6 passed, 16 warnings in 0.36s
Cross-module: 15 passed (org_mapping + extraction)
```

All warnings are deprecation notices for `datetime.utcnow()` — non-blocking.

## Deviations from Plan

None. Implementation matches PLAN.md spec exactly.

## Files Changed

- `src/org_mapping/__init__.py` (NEW — package marker)
- `src/org_mapping/models.py` (NEW — TraderTeamStats ORM model)
- `src/org_mapping/queries.py` (NEW — query functions)
- `tests/org_mapping/__init__.py` (NEW — package marker)
- `tests/org_mapping/test_queries.py` (NEW — 6 unit tests)

## Known Issues

None.

## Next Steps

Plan 22-02: Wire query layer into `polymarket team-stats` CLI command.
