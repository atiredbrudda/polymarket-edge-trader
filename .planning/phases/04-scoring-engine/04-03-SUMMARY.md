---
phase: 04-scoring-engine
plan: 03
subsystem: scoring
tags: [python, database, pipeline, leaderboard, orchestration]

# Dependency graph
requires:
  - phase: 04-scoring-engine
    plan: 01
    provides: Concentration metrics and specialization classification
  - phase: 04-scoring-engine
    plan: 02
    provides: Composite scoring engine with percentile normalization
  - phase: 03-historical-evaluation
    provides: Performance metrics and consistency data
affects: [07-cli-interface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Append-only score history for trend analysis"
    - "Batch processing for population-relative percentile normalization"
    - "Subquery pattern for latest score retrieval per trader"
    - "Volume proxy fallback: abs(size * avg_price) or abs(size)"

key-files:
  created:
    - src/pipeline/scoring_pipeline.py
    - tests/test_scoring_pipeline.py
  modified:
    - src/db/models.py
    - src/pipeline/queries.py

key-decisions:
  - "ExpertiseScore rows append-only: new INSERT on each run, no updates"
  - "Leaderboard queries use max(computed_at) subquery for latest scores"
  - "Volume proxy handles avg_entry_price=None by falling back to abs(size)"
  - "get_game_leaderboard uses COALESCE for percentile_rank fallback to raw_score"
  - "Consistency data retrieved from PerformanceSnapshot timeframe='all'"
  - "Traders without PerformanceSnapshot get defaults: score=50, signal='insufficient_data' -> 1.0x multiplier"

patterns-established:
  - "LeaderboardEntry frozen dataclass for immutable leaderboard entries"
  - "Orchestration layer separates pure scoring logic from database persistence"
  - "get_positions_for_game uses slug LIKE pattern to capture game + sub-nodes"
  - "Batch percentile normalization: compute all scores first, then normalize across population"

# Metrics
duration: 5.2min
completed: 2026-02-06
---

# Phase 4 Plan 03: Scoring Pipeline and Leaderboard Summary

**ExpertiseScore model with append-only history, leaderboard queries, and full scoring pipeline orchestrating positions-to-database flow**

## Performance

- **Duration:** 5.2 min (309 seconds)
- **Started:** 2026-02-06T21:10:06Z
- **Completed:** 2026-02-06T21:15:15Z
- **Tasks:** 3 (standard execution)
- **Files modified:** 4
- **Tests added:** 13 (567 lines)

## Accomplishments
- Created ExpertiseScore model for score history tracking with append-only inserts
- Implemented leaderboard queries: get_game_leaderboard (latest scores), get_trader_score_history (chronological)
- Built scoring pipeline orchestrating full flow: positions -> concentrations -> scores -> percentiles -> database
- Added LeaderboardEntry dataclass with all required fields (rank, scores, PnL, activity, specialization)
- Enabled trend analysis via score history snapshots
- Supported top_n and min_score filtering for leaderboard queries
- Implemented volume proxy fallback for positions with missing avg_entry_price
- Integrated consistency data retrieval from PerformanceSnapshot (defaults for traders without snapshots)

## Task Commits

Each task was committed atomically:

1. **Task 1: ExpertiseScore model and leaderboard queries** - `e574430` (feat)
   - ExpertiseScore model with 13 fields and 3 indexes
   - get_game_leaderboard: retrieve latest scores per trader with filtering
   - get_trader_score_history: retrieve chronological score history
   - get_all_game_slugs_with_positions: query games with position data
   - get_positions_for_game: filter positions by taxonomy game slug

2. **Task 2a: Scoring pipeline core** - `d05cd8a` (feat)
   - LeaderboardEntry dataclass with 11 fields
   - _compute_position_volume helper for volume proxy calculation
   - _get_consistency_data helper to retrieve stored consistency metrics
   - compute_game_scores: full pipeline from positions to leaderboard
   - compute_all_game_scores: batch process all games

3. **Task 2b: Integration tests** - `4938047` (test)
   - 13 test cases covering full pipeline flow
   - Tests for sorted leaderboard, exclusion rules, persistence, append-only history
   - Tests for volume proxy fallback, consistency data retrieval, multi-game processing
   - All 307 tests pass (294 existing + 13 new)

## Files Created/Modified
- `src/db/models.py` - Added ExpertiseScore model (20 lines)
- `src/pipeline/queries.py` - Added 4 leaderboard query functions (147 lines)
- `src/pipeline/scoring_pipeline.py` - Created orchestration layer (322 lines)
- `tests/test_scoring_pipeline.py` - Created integration tests (567 lines)

## Decisions Made

**ExpertiseScore rows append-only (INSERT only, no updates)**
- Rationale: Score history enables trend analysis (rising star detection in Phase 7)
- Each scoring run creates new rows with computed_at timestamp
- Leaderboard queries use max(computed_at) subquery to retrieve latest scores
- Allows comparison of score evolution over time

**Volume proxy fallback for missing avg_entry_price**
- Rationale: Some positions may have avg_entry_price=None (edge case in position calculation)
- Primary: abs(size * avg_entry_price) when avg_entry_price is not None
- Fallback: abs(size) when avg_entry_price is None
- Ensures concentration calculations don't fail on edge cases

**Consistency data from PerformanceSnapshot timeframe='all'**
- Rationale: Consistency metrics are already computed and stored in Phase 3
- Query PerformanceSnapshot for timeframe="all" to retrieve consistency_score and consistency_signal
- Defaults for traders without snapshot: score=50, signal="insufficient_data" -> 1.0x multiplier
- Avoids recomputing consistency on every scoring run (performance optimization)

**get_game_leaderboard uses COALESCE for percentile_rank**
- Rationale: percentile_rank may be None immediately after scoring (before normalization)
- ORDER BY COALESCE(percentile_rank, raw_score) DESC ensures ranking works in both cases
- Primarily sorts by percentile_rank when available, falls back to raw_score

**get_positions_for_game uses slug LIKE pattern**
- Rationale: Game slug captures game and all sub-nodes (tournaments, teams)
- slug LIKE 'esports.cs2%' matches "esports.cs2", "esports.cs2.iem-katowice", "esports.cs2.iem-katowice.navi"
- Enables hierarchical filtering without complex recursive queries

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tests passed on first implementation run, no debugging needed.

## Next Phase Readiness

**Ready for Phase 7 CLI Interface:**
- Leaderboard queries provide ranked trader lists per game
- Score history enables trend analysis (rising stars)
- LeaderboardEntry includes all fields needed for display (rank, score, PnL, activity, specialization)
- Top-N and min-score filtering enable flexible leaderboard views
- ExpertiseScore model captures all scoring component breakdowns for transparency

**Imports available:**
```python
from src.db.models import ExpertiseScore
from src.pipeline.queries import (
    get_game_leaderboard,
    get_trader_score_history,
    get_all_game_slugs_with_positions,
    get_positions_for_game,
)
from src.pipeline.scoring_pipeline import (
    compute_game_scores,
    compute_all_game_scores,
    LeaderboardEntry,
)
```

**Typical usage pattern for Phase 7:**
```python
# Compute scores for all games
session = get_session()
all_leaderboards = compute_all_game_scores(session)

# Get top 20 traders in CS2
cs2_leaderboard = get_game_leaderboard(session, "esports.cs2", top_n=20)

# Get trader's score history across games
trader_history = get_trader_score_history(session, "0xTrader1")

# Filter by minimum score
high_performers = get_game_leaderboard(
    session, "esports.cs2", top_n=50, min_score=Decimal("70")
)
```

**Test coverage:**
- compute_game_scores: sorted leaderboard, exclusion rules, field validation (3 tests)
- ExpertiseScore persistence: database inserts, append-only history (2 tests)
- Empty game handling (1 test)
- Volume proxy fallback (1 test)
- Leaderboard queries: latest scores, min_score filtering, history retrieval (3 tests)
- Consistency data retrieval: with/without PerformanceSnapshot (2 tests)
- Multi-game processing (1 test)

**Total project tests: 307 (62 Phase 1 + 51 Phase 2 + 121 Phase 3 + 60 Phase 4 + 13 Phase 4.03)**

---
*Phase: 04-scoring-engine*
*Completed: 2026-02-06*
