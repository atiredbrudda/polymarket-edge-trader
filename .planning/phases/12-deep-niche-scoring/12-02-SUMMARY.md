# Plan 12-02 Summary: Scoring Pipeline Extension + Hidden Specialist Detection

**Date:** 2026-02-14
**Branch:** worker/12-01
**Commit:** 14159d1

## Completed Tasks

### Task 1: Multi-depth Scoring Pipeline Function

**Status:** ✅ Complete

**Changes:**
- Added `compute_taxonomy_scores(session, slug, taxonomy_depth, weights, now)` function
- Added `compute_all_taxonomy_scores(session, depth, weights, now)` function
- Added `_get_positions_for_depth` helper for depth-specific position queries
- Extended LeaderboardEntry to include taxonomy_depth field
- Modified compute_game_scores to persist taxonomy_depth=1 for backward compatibility

**Key implementation details:**
- Uses depth-appropriate concentration calculations (tournament vs team)
- Uses slug LIKE pattern to capture descendant nodes
- Percentile normalization runs per-slug-per-depth

### Task 2: Hidden Specialist Detection

**Status:** ✅ Complete

**Changes:**
- Added `identify_hidden_specialists(session, game_slug, game_score_threshold, deep_score_threshold)` function
- Identifies traders with low game scores (default < 60) but high tournament/team scores (default >= 75)
- Returns sorted list by score_delta (deep_score - game_score)
- Each result includes: trader_address, game_slug, game_score, deep_slug, deep_depth, deep_score, score_delta

## Verification

- **New tests:** 6 passed
- **Full suite:** 567 passed, 11 pre-existing failures (unrelated to changes)
- **No regressions** introduced by this plan

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| src/pipeline/scoring_pipeline.py | Modified | Added compute_taxonomy_scores, compute_all_taxonomy_scores, identify_hidden_specialists |
| tests/test_scoring_pipeline_deep.py | New | 6 tests |

## Notes

- Hidden specialists are traders who appear average at game level but have deep expertise in specific tournaments/teams
- The system can now score at three levels: game (depth 1), tournament (depth 2), team (depth 3)
- Depth is stored in ExpertiseScore.taxonomy_depth column for filtering
