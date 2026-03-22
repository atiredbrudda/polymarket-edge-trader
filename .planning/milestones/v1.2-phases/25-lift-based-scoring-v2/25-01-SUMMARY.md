---
phase: 25-lift-based-scoring-v2
plan: 01
subsystem: scoring
tags: [lift-metrics, clv, roi, sharpe, z-score, quintile, sqlalchemy, decimal, statistics]

# Dependency graph
requires:
  - phase: 24-scoring-rewire
    provides: "MarketEntity-based scoring pipeline with 6,105 traders processable"
provides:
  - "LiftScore ORM model (lift_scores table) replacing ExpertiseScore as active scoring table"
  - "src/evaluation/lift_metrics.py: pure functions compute_clv, compute_roi, compute_sharpe, compute_z_scores, compute_composite, assign_quintiles"
  - "src/config/market_config.py: MarketConfig frozen dataclass, MARKET_CONFIGS with 5 categories, get_market_config()"
  - "compute_category_scores / compute_all_category_scores in scoring_pipeline.py"
  - "get_market_avg_entries / get_positions_for_category / get_lift_leaderboard in queries.py"
  - "polymarket score command: computes lift scores, shows Q5 count per category"
  - "polymarket leaderboard command: shows Q1-Q5 traders with CLV/ROI/Sharpe breakdown"
affects:
  - "signal detection (detection.py still uses ExpertiseScore — needs rewire in next plan)"
  - "25-02 if signal enrichment plan exists"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure lift metric functions (no DB, no state) — all CLV/ROI/Sharpe computed from position lists"
    - "Category-parametric scoring — all functions take category str, category-agnostic by design"
    - "Z-score normalization using Python stdlib statistics.mean/stdev (float), back to Decimal immediately"
    - "DELETE-then-INSERT LiftScore pattern per category (not append-only like ExpertiseScore)"
    - "30-day rolling window via last_trade_timestamp >= window_start filter"

key-files:
  created:
    - src/config/market_config.py
    - src/evaluation/lift_metrics.py
    - tests/test_lift_metrics.py
    - tests/test_lift_scoring_pipeline.py
  modified:
    - src/db/models.py
    - src/pipeline/queries.py
    - src/pipeline/scoring_pipeline.py
    - src/cli/commands.py

key-decisions:
  - "Equal-weight z(CLV)+z(ROI)+z(Sharpe) formula — no tuning needed per 348-experiment backtest"
  - "Single trader -> Q3 (middle quintile) rather than Q1 or Q5 to avoid false signal"
  - "Category match uses LOWER(Market.category) for case-insensitive join (DB has eSports, config has esports)"
  - "DELETE-then-INSERT for LiftScore rows (not append-only) since only latest snapshot is needed for leaderboard"
  - "Old compute_game_scores and compute_all_game_scores preserved but not called by CLI"
  - "ExpertiseScore table kept with existing data — no migration to drop it"

patterns-established:
  - "Pure metric functions in src/evaluation/lift_metrics.py — no DB dependencies, testable in isolation"
  - "MarketConfig frozen dataclass with get_market_config() case-insensitive lookup"
  - "LiftLeaderboardEntry frozen dataclass — returned from scoring pipeline, never modified"

requirements-completed: [LIFT-01, LIFT-03]

# Metrics
duration: 14min
completed: 2026-03-22
---

# Phase 25 Plan 01: Lift-Based Scoring v2 Summary

**Replaced 40%WR+25%concentration+20%recency+15%sample_size composite with z(CLV)+z(ROI)+z(Sharpe) equal-weight lift formula: new LiftScore ORM, pure metric functions, rewired score/leaderboard CLI**

## Performance

- **Duration:** 14 min
- **Started:** 2026-03-22T12:58:54Z
- **Completed:** 2026-03-22T13:12:33Z
- **Tasks:** 2
- **Files modified:** 7 (4 created, 3 modified)

## Accomplishments

- Pure lift metric functions (compute_clv, compute_roi, compute_sharpe, compute_z_scores, compute_composite, assign_quintiles) with 42 unit tests covering all edge cases
- LiftScore ORM model with 4 DB indexes replacing ExpertiseScore as the active scoring table
- Scoring pipeline rewired: compute_category_scores with 30-day window, per-category min_positions threshold, DELETE-then-INSERT persistence, quintile assignment
- polymarket score and polymarket leaderboard CLI commands rewired to lift-based pipeline — old ExpertiseScore pipeline functions preserved but not called

## Task Commits

1. **Task 1: Market config + LiftScore model + pure lift metric functions** - `7af4276` (feat)
2. **Task 2: Scoring pipeline rewire + score/leaderboard CLI rewire with integration tests** - `98922de` (feat)

## Files Created/Modified

- `src/config/market_config.py` - MarketConfig frozen dataclass, MARKET_CONFIGS (5 categories), get_market_config() case-insensitive lookup
- `src/evaluation/lift_metrics.py` - LiftMetrics dataclass + 6 pure functions for CLV/ROI/Sharpe computation and z-score normalization
- `src/db/models.py` - Added LiftScore ORM model with composite_score, clv/roi/sharpe raw+zscore, quintile, window_start/end fields, 4 indexes
- `src/pipeline/queries.py` - Added get_market_avg_entries(), get_positions_for_category(), get_lift_leaderboard()
- `src/pipeline/scoring_pipeline.py` - Added LiftLeaderboardEntry dataclass, compute_category_scores(), compute_all_category_scores()
- `src/cli/commands.py` - Rewired score command (calls compute_all_category_scores), rewired leaderboard command (--category option, Rich table with CLV/ROI/Sharpe/Q columns)
- `tests/test_lift_metrics.py` - 42 unit tests for all pure metric functions
- `tests/test_lift_scoring_pipeline.py` - 20 integration tests for pipeline, window filtering, persistence, leaderboard

## Decisions Made

- Category matching uses LOWER(Market.category) against lowercase config key because DB stores "eSports" while configs use "esports"
- Single-trader edge case in assign_quintiles returns Q3 (middle), not Q1/Q5, to avoid false signals
- DELETE-then-INSERT pattern for LiftScore (vs ExpertiseScore's append-only) because leaderboard only needs latest snapshot
- Old game_slug-based scoring functions kept in codebase unchanged (not called by CLI) to avoid breaking any diagnostic scripts

## Deviations from Plan

None — plan executed exactly as written. One minor observation: the test fixture uses `with session_factory() as session` pattern which required SQLAlchemy context manager support (already available in existing ORM setup).

## Issues Encountered

- Pre-existing test failure in `tests/datasources/test_jbecker.py::test_query_uses_parameterized_sql` confirmed pre-existing before our changes (verified by git stash). Not introduced by this plan.

## Next Phase Readiness

- Lift scoring pipeline fully operational: run `polymarket score` then `polymarket leaderboard --category esports`
- Signal detection (detection.py) still filters experts using ExpertiseScore raw_score > 70 — needs rewiring to LiftScore quintile == 5 (LIFT-02 if scoped in plan 02)
- Category match relies on Market.category containing "eSports" (capital S) — confirmed working via LOWER() in SQL

## Self-Check: PASSED

All expected files created and commits verified:
- src/config/market_config.py: FOUND
- src/evaluation/lift_metrics.py: FOUND
- src/db/models.py (LiftScore): FOUND
- tests/test_lift_metrics.py: FOUND
- tests/test_lift_scoring_pipeline.py: FOUND
- Commit 7af4276: FOUND
- Commit 98922de: FOUND

---
*Phase: 25-lift-based-scoring-v2*
*Completed: 2026-03-22*
