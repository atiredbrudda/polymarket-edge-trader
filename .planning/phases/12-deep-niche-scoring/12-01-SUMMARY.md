# Plan 12-01 Summary: Multi-depth Scoring Foundations

**Date:** 2026-02-14
**Branch:** worker/12-01
**Commit:** 263bb7c

## Completed Tasks

### Task 1: Schema Extension and Concentration Functions (TDD)

**Status:** ✅ Complete

**Changes:**
- Added `taxonomy_depth` column to `ExpertiseScore` model with default=1 (backward compatible)
- Added composite index `ix_expertise_game_depth` on (game_slug, taxonomy_depth)
- Added `calculate_tournament_concentration(tournament_volume, game_volume)` pure function
- Added `calculate_team_concentration(team_volume, tournament_volume)` pure function
- 6 new tests for concentration functions — all pass

### Task 2: Multi-depth Position Queries and Leaderboard (TDD)

**Status:** ✅ Complete

**Changes:**
- Added `get_positions_for_slug(session, slug, trader_address=None)` function
- Added `get_taxonomy_leaderboard(session, slug, taxonomy_depth, top_n, min_score)` function
- Added `get_all_slugs_with_positions_at_depth(session, depth)` function
- 8 new tests for query functions — all pass

## Verification

- **New tests:** 14 passed
- **Full suite:** 561 passed, 11 pre-existing failures (unrelated to changes)
- **No regressions** introduced by this plan

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| src/db/models.py | Modified | Added taxonomy_depth column |
| src/evaluation/concentration.py | Modified | Added tournament/team concentration functions |
| src/pipeline/queries.py | Modified | Added multi-depth query functions |
| tests/test_deep_scoring.py | New | 14 tests |

## Notes

- taxonomy_depth defaults to 1 for backward compatibility with existing game-level scores
- Depth values: 1=game, 2=tournament, 3=team
- Query functions use slug LIKE pattern to capture all descendants (e.g., "esports.cs2" matches "esports.cs2.iem-katowice")
