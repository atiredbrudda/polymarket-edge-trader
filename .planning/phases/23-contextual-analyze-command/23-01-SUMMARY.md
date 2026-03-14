# Phase 23 Plan 01 Summary: Entity Alpha Data Layer

## What Was Built

Implemented the data layer for the analyze command (Plan 23-01):

### Files Created/Modified

1. **src/org_mapping/models.py** (MODIFIED)
   - Added `EntityAlpha` ORM model
   - Unique index on (trader_address, entity_type, entity_name, game)
   - Separate indexes on entity_name and trader_address for read performance

2. **src/org_mapping/crawler.py** (NEW)
   - `load_cursor()` - loads batch processing state from `.planning/analyze_cursor.json`
   - `save_cursor()` - persists state with last_trader, last_entity, last_game, processed count
   - `clear_cursor()` - removes cursor file

3. **src/org_mapping/queries.py** (MODIFIED)
   - `get_entity_alpha_for_trader(session, trader_address)` - returns per-entity wins/losses/win_rate across team, tournament, game dimensions
   - `upsert_entity_alpha(session, trader_address)` - idempotent upsert using SELECT-then-UPDATE pattern
   - `build_batch_trader_list(session)` - returns traders whose first_seen is within 60s of max(first_seen)

4. **tests/test_analyze.py** (NEW)
   - 6 unit tests (ANALYZE-01 through ANALYZE-06)
   - All tests passing

## Key Decisions

1. **Direction convention maintained**: LONG=team_a, SHORT=team_b (established Phase 22)
2. **Entity aggregation**: Each market produces up to 3 entity rows (team, tournament, game) from a single position
3. **Cursor file location**: `.planning/analyze_cursor.json` - follows existing pattern for batch state
4. **Idempotent upsert**: Uses SELECT-then-UPDATE pattern consistent with TraderTeamStats implementation

## Test Results

```
tests/org_mapping/ tests/test_analyze.py - 13 passed, 0 regressions
```

All 6 new tests (ANALYZE-01..06) pass:
- ANALYZE-01: Entity alpha basic functionality
- ANALYZE-02: Direction mapping (LONG→team_a, SHORT→team_b)
- ANALYZE-03: Excludes unresolved, void, prop markets
- ANALYZE-04: Upsert idempotency
- ANALYZE-05: Batch mode trader filtering by first_seen
- ANALYZE-06: Crawler cursor save/load/clear round-trip

## Deviations from PLAN.md

None. Implementation follows the plan spec exactly.

## Known Issues / Follow-up

None. Plan 23-01 complete. Plan 23-02 (CLI command) is the next task.
