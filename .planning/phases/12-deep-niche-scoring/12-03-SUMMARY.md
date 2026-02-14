# Plan 12-03 Summary: CLI Integration

**Date:** 2026-02-14
**Branch:** worker/12-01
**Commit:** 369b7ac

## Completed Tasks

### Task 1: Extend Leaderboard with --depth Flag

**Status:** ✅ Complete

**Changes:**
- Added `--depth` / `-d` option with choices: game, tournament, team (default: game)
- Renamed argument from `game_slug` to `slug` for clarity
- Updated validation to check TaxonomyNode at the specified depth
- When depth != "game", uses `get_taxonomy_leaderboard` instead of `get_game_leaderboard`
- Updated `format_leaderboard_table` to accept `depth_label` parameter for display

### Task 2: Expertise Command

**Status:** ✅ Complete

**Changes:**
- Added `expertise` command to show trader expertise breakdown across all taxonomy depths
- Queries latest ExpertiseScore at depths 1, 2, and 3
- Displays scores in a Rich Panel with tables for each depth level
- Shows slug, score, percentile, and specialization label

### Task 3: Specialists Command

**Status:** ✅ Complete

**Changes:**
- Added `specialists` command to discover hidden niche experts
- Calls `identify_hidden_specialists` with configurable thresholds
- Default thresholds: game_score < 60, deep_score >= 75
- Displays in a Rich Table: Trader, Game Score, Niche, Niche Score, Delta

### Task 4: Formatters

**Status:** ✅ Complete

**Changes:**
- Updated `format_leaderboard_table` to accept `depth_label` parameter
- Added `format_expertise_breakdown` for multi-depth score display
- Added `format_specialists_table` for hidden specialist display

## Verification

- **New tests:** 9 passed
- **Full suite:** 576 passed, 11 pre-existing failures (unrelated to changes)
- **No regressions** introduced by this plan

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| src/cli/commands.py | Modified | Added --depth flag, expertise, specialists commands |
| src/cli/formatters.py | Modified | Added formatters, updated leaderboard table |
| tests/test_cli_deep_scoring.py | New | 9 tests |

## Usage Examples

```bash
# Game leaderboard (default)
polymarket leaderboard esports.cs2

# Tournament leaderboard
polymarket leaderboard esports.cs2.iem-katowice --depth tournament

# Team leaderboard
polymarket leaderboard esports.cs2.iem-katowice.navi --depth team

# Show trader's expertise breakdown
polymarket expertise 0xTrader123

# Discover hidden specialists in a game
polymarket specialists esports.cs2

# With custom thresholds
polymarket specialists esports.cs2 --game-threshold 50 --deep-threshold 80
```

## Notes

- Backward compatible: `polymarket leaderboard esports.cs2` works exactly as before
- Depth values: 1=game, 2=tournament, 3=team
- All new commands use Rich for formatted output
