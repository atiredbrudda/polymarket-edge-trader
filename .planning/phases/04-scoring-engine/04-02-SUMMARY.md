---
phase: 04-scoring-engine
plan: 02
subsystem: scoring
tags: [python, decimal, composite-scoring, percentile-normalization, tdd]

# Dependency graph
requires:
  - phase: 04-scoring-engine
    plan: 01
    provides: Concentration metrics and specialization classification
  - phase: 03-historical-evaluation
    plan: 01
    provides: Win rate calculation from metrics module
  - phase: 03-historical-evaluation
    plan: 02
    provides: Consistency detection module
affects: [04-03-leaderboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composite scoring with weighted components (win rate 40%, concentration 25%, recency 20%, sample size 15%)"
    - "Consistency multiplier: bonus-only (1.05x for consistent, 1.0x baseline, never below 1.0)"
    - "Percentile normalization for population-relative ranking with tie handling"
    - "Exponential decay for recency weighting (~90-day half-life)"
    - "Exponential growth curve for sample size confidence (0 at min, 1.0 at full)"

key-files:
  created:
    - src/evaluation/scoring.py
    - tests/test_scoring.py
  modified: []

key-decisions:
  - "Recency < 1 day gets full weight 1.0 (same-day edge case handling)"
  - "Sample size confidence uses n - min + 1 to ensure positive value at exactly minimum threshold"
  - "Consistency multiplier is bonus-only: 1.05x for score >= 80 AND stable, 1.0x baseline otherwise (no penalty)"
  - "Percentile rank None in ExpertiseScoreResult until batch normalization via normalize_scores_to_percentiles"
  - "Minimum 5 resolved markets enforced before scoring (returns None below threshold)"
  - "Specialization label format: 'esports_level/game_level' (e.g., 'specialist/specialist')"

patterns-established:
  - "ExpertiseScoreResult frozen dataclass captures all scoring components for transparency"
  - "Component scores stored before weighting for debugging and tuning"
  - "Percentile normalization decoupled from scoring for batch processing efficiency"
  - "DEFAULT_WEIGHTS configurable via function parameter for validation framework integration"

# Metrics
duration: 5.5min
completed: 2026-02-06
---

# Phase 4 Plan 02: Composite Scoring Engine Summary

**JWT auth with refresh rotation using jose library**

## Performance

- **Duration:** 5.5 min (327 seconds)
- **Started:** 2026-02-06T21:00:05Z
- **Completed:** 2026-02-06T21:05:29Z
- **Tasks:** 1 (TDD: RED-GREEN)
- **Files modified:** 2
- **Tests added:** 38 (672 lines)

## Accomplishments
- Implemented composite expertise scoring combining win rate (~40%), concentration (~25%), recency (~20%), and sample size (~15%)
- Created ExpertiseScoreResult dataclass capturing all 11 scoring components for full transparency
- Built recency weighting with exponential decay (< 1 day = full weight, ~90-day half-life)
- Implemented sample size confidence with exponential growth curve (0 below min, 1.0 at/above full confidence)
- Applied consistency multiplier as bonus-only (1.05x for consistent traders, 1.0x baseline for all others, never penalty)
- Developed percentile normalization for population-relative ranking with proper tie handling
- Enforced minimum 5 resolved markets threshold (returns None below threshold)

## Task Commits

Each task was committed atomically following TDD RED-GREEN-REFACTOR:

1. **Task 1 RED: Write failing tests** - `1be89bf` (test)
   - 38 test cases covering all scoring components and edge cases
   - Tests for recency decay, sample size confidence, composite scoring, percentile normalization
   - Integration test for full pipeline with ranking verification

2. **Task 1 GREEN: Implement module** - `d62e26c` (feat)
   - Five pure functions + ExpertiseScoreResult dataclass
   - Recency weight: exponential decay with < 1 day edge case
   - Sample size confidence: exponential growth with n - min + 1 adjustment
   - Composite scoring: weighted sum with consistency multiplier (bonus-only)
   - Percentile normalization: population ranking with tie handling
   - All 294 tests pass (38 new + 256 existing)

_No refactoring needed - implementation already minimal and clean_

## Files Created/Modified
- `src/evaluation/scoring.py` - Pure functions for composite expertise scoring (336 lines)
- `tests/test_scoring.py` - 38 test cases covering all behaviors and edge cases (672 lines)

## Decisions Made

**Recency weighting: < 1 day gets full weight 1.0**
- Rationale: Same-day trading (e.g., 8am to 12pm) should get full recency weight, not partial decay
- Prevents penalizing recent activity due to intraday time differences
- Exponential decay starts after 1 full day elapsed
- 90-day half-life means weight ~0.5 at 90 days, ~0.25 at 180 days

**Sample size confidence: n - min + 1 adjustment**
- Rationale: At exactly minimum threshold (n=5), n - min = 0 gives 1 - exp(0) = 0
- Adding 1 ensures positive confidence at minimum (small but non-zero)
- Exponential growth curve provides smooth increase from min (5 markets) to full confidence (30 markets)
- Above 30 markets: confidence clamped to 1.0

**Consistency multiplier: bonus-only, never penalty**
- Rationale: Inconsistency might indicate insufficient data rather than poor skill
- High consistency (score >= 80 AND signal == "stable") gets 1.05x bonus
- All other cases get 1.0x baseline (no penalty)
- Applied after weighted sum of components, before clamping to [0, 100]
- Aligned with "validate skill, don't punish variance" philosophy

**Percentile rank None until batch normalization**
- Rationale: Percentile ranks are population-relative and must be computed in batch
- ExpertiseScoreResult stores None for percentile_rank initially
- normalize_scores_to_percentiles computes percentiles across all traders
- Enables efficient batch processing and avoids incremental recalculation overhead

**Minimum 5 resolved markets enforced**
- Rationale: Below 5 markets, sample size confidence is 0 and score unreliable
- Function returns None (not ExpertiseScoreResult) below threshold
- Downstream code can filter out None results cleanly
- Consistent with sparse_threshold from Phase 3 consistency analysis

**Specialization label format: "esports_level/game_level"**
- Rationale: Compact string representation of two-tier classification
- Examples: "specialist/specialist", "specialist/generalist", "generalist/specialist", "generalist/generalist"
- Easy to parse downstream for filtering or display logic
- Sourced from classify_specialization with current trader's concentrations

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Test failures during GREEN phase:**
1. Recency same-day test failed: Expected 1.0, got 0.998... (4 hours apart same day)
   - Fix: Changed condition from `days_since <= 0` to `days_since < 1`
   - Now any activity within last 24 hours gets full weight

2. Sample size confidence at minimum returned 0 instead of positive
   - Fix: Adjusted formula to use `n - min_threshold + 1` instead of `n - min_threshold`
   - Ensures positive confidence at exactly minimum threshold

3. High performance trader test expected 1.0x multiplier but got 1.05x
   - Issue: Test comment was wrong - consistency_score=90 AND signal="stable" SHOULD get bonus
   - Fix: Updated test expectation to assert 1.05x (correct behavior)

All issues resolved in GREEN phase commit.

## Next Phase Readiness

**Ready for Phase 4 Plan 03 (Leaderboard Generation):**
- Scoring engine provides 0-100 raw scores with all component breakdowns
- ExpertiseScoreResult includes all metadata needed for leaderboard display
- normalize_scores_to_percentiles enables population-relative ranking
- Minimum sample size enforcement filters out low-confidence traders
- Consistency multiplier applied transparently (visible in consistency_multiplier field)
- Specialization label enables filtering by trader type (specialist vs generalist)

**Imports available:**
```python
from src.evaluation.scoring import (
    ExpertiseScoreResult,
    calculate_recency_weight,
    calculate_sample_size_confidence,
    calculate_expertise_score,
    normalize_scores_to_percentiles,
    DEFAULT_WEIGHTS,
    MIN_RESOLVED_MARKETS,
    RECENCY_HALF_LIFE_DAYS,
)
```

**Typical usage pattern for leaderboard:**
```python
# Score all traders for a game
scores = {}
for trader_address in traders:
    result = calculate_expertise_score(
        positions=trader_positions[trader_address],
        trader_address=trader_address,
        game_slug="esports.cs2",
        esports_concentration=esports_conc[trader_address],
        game_concentration=game_conc[trader_address],
        consistency_score=consistency_scores[trader_address],
        consistency_signal=consistency_signals[trader_address],
    )
    if result:  # Filter out None (below min sample size)
        scores[trader_address] = result.raw_score

# Normalize to percentiles
percentiles = normalize_scores_to_percentiles(scores)

# Build leaderboard
leaderboard = sorted(
    [(addr, percentiles[addr], scores[addr]) for addr in scores],
    key=lambda x: x[1],  # Sort by percentile descending
    reverse=True,
)
```

**Test coverage:**
- Recency weight: same day, future, half-life, double half-life, edge cases (6 tests)
- Sample size confidence: below min, at min, at full, monotonic growth (6 tests)
- Expertise score: min sample, high/low performance, consistency multiplier variants, void exclusion, custom weights (13 tests)
- Percentile normalization: empty, single, ties, identical scores (6 tests)
- Integration: full pipeline with ranking verification (1 test)
- Constants validation (4 tests)
- Dataclass immutability (2 tests)

**Total project tests: 294 (62 Phase 1 + 51 Phase 2 + 121 Phase 3 + 60 Phase 4)**

---
*Phase: 04-scoring-engine*
*Completed: 2026-02-06*
