---
phase: 03-historical-evaluation
plan: 05
subsystem: evaluation
tags: [validation, walk-forward, temporal-holdout, spearman, decimal, pure-functions]

# Dependency graph
requires:
  - phase: 03-01
    provides: Metrics functions (calculate_win_rate, aggregate_trader_metrics)
  - phase: 03-02
    provides: Timeframe functions (get_timeframe_bounds)
provides:
  - Out-of-sample validation framework with temporal train/test splits
  - Walk-forward validation with expanding training windows
  - Scoring weight evaluation with correlation and rank accuracy metrics
  - Re-runnable validation for periodic weight tuning
affects: [04-expertise-scoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Temporal holdout validation over k-fold to prevent lookahead bias"
    - "Walk-forward expanding windows: fixed test periods, growing training data"
    - "Manual Spearman rank correlation using Decimal (no scipy dependency)"
    - "Duck-typed position inputs for pure functions"

key-files:
  created:
    - src/evaluation/validation.py
    - tests/test_validation.py
  modified: []

key-decisions:
  - "Temporal holdout over k-fold: strict time-based splits prevent lookahead bias per research best practices"
  - "Walk-forward with 90-day test windows and expanding training windows: simulates realistic re-training scenarios"
  - "Manual Spearman correlation implementation: no scipy dependency, uses Decimal for precision"
  - "metric_fn parameter enables Phase 4 scoring engine to plug in custom evaluation logic"
  - "FoldResult and ValidationResult frozen dataclasses: structured output for downstream analysis"

patterns-established:
  - "Validation framework is re-runnable: same inputs produce same outputs (deterministic)"
  - "All datetime operations use timezone-naive UTC per existing codebase"
  - "Weights must sum to 1.0 (validated with 0.001 tolerance)"
  - "Returns empty results for insufficient data rather than raising errors"

# Metrics
duration: 4.1min
completed: 2026-02-06
---

# Phase 03 Plan 05: Out-of-Sample Validation Framework Summary

**Temporal holdout validation with walk-forward testing, Spearman correlation, and expanding training windows for scoring weight tuning**

## Performance

- **Duration:** 4.1 min
- **Started:** 2026-02-06T18:07:36Z
- **Completed:** 2026-02-06T18:11:41Z
- **Tasks:** 2 (TDD: test + feat)
- **Files modified:** 2

## Accomplishments
- Temporal train/test split prevents lookahead bias (strict time ordering)
- Walk-forward validation generates up to 5 folds with expanding training windows
- Scoring weight evaluation computes correlation, rank accuracy, and top-K precision
- Manual Spearman correlation using Decimal (no scipy dependency)
- Re-runnable framework: deterministic outputs for periodic weight re-tuning

## Task Commits

Each task was committed atomically (TDD cycle):

1. **Task 1: RED - Write failing tests** - `c0d4797` (test)
   - Temporal train/test split tests (6 cases)
   - Walk-forward validation tests (8 cases)
   - Scoring weight evaluation tests (8 cases)
   - Run validation orchestrator tests (6 cases)
   - Total: 28 tests

2. **Task 2: GREEN - Implement validation framework** - `6d0b597` (feat)
   - temporal_train_test_split: strict temporal ordering
   - walk_forward_validate: expanding windows, 90-day tests
   - evaluate_scoring_weights: correlation + rank accuracy
   - run_validation: orchestrator with aggregation
   - Manual Spearman correlation with tie handling
   - FoldResult and ValidationResult dataclasses

**Plan metadata:** (pending - will be in final commit)

_Note: No refactor phase needed - implementation was clean on first pass_

## Files Created/Modified
- `src/evaluation/validation.py` - Pure functions for temporal validation, walk-forward fold generation, and weight evaluation with Spearman correlation
- `tests/test_validation.py` - 28 tests covering temporal splits, fold generation, metric computation, and deterministic behavior

## Decisions Made

**1. Temporal holdout over k-fold cross-validation**
- Research recommendation to avoid lookahead bias
- Train sets always come before test sets chronologically
- No position with timestamp >= split_date leaks into training

**2. Walk-forward with expanding training windows**
- Works backwards from latest data: Fold 1 = earliest data, Fold 5 = most recent
- Each fold has 90-day test window (configurable)
- Training window grows: Fold 1 has less history, Fold 5 has maximum history
- Simulates realistic re-training as more data accumulates

**3. Manual Spearman correlation implementation**
- No scipy dependency (keeps codebase lean)
- Uses Decimal throughout for financial precision
- Handles ties via average rank assignment
- Formula: 1 - (6 * sum_d^2) / (n * (n^2 - 1))

**4. metric_fn parameter for extensibility**
- evaluate_scoring_weights accepts optional custom metric function
- Enables Phase 4 scoring engine to provide specialized evaluation logic
- Defaults to simple PnL-based correlation if not provided

**5. Re-runnable validation design**
- Deterministic: same inputs always produce same outputs
- No random seeds, no shuffling
- Essential for monthly/quarterly re-tuning without code changes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test expectation for fold count**
- **Found during:** Task 2 (GREEN phase test run)
- **Issue:** Test expected 5 folds with 450 days of data, but algorithm correctly generated only 3 folds due to min_train_days=90 constraint
- **Fix:** Increased test data to 600 days with 50 positions (12-day spacing) to truly fit 5 folds
- **Files modified:** tests/test_validation.py
- **Verification:** All 28 tests pass
- **Committed in:** 6d0b597 (feat commit - test and implementation together)

---

**Total deviations:** 1 auto-fixed (1 test bug)
**Impact on plan:** Test had incorrect expectation. Algorithm behavior was correct per plan specification. No scope creep.

## Issues Encountered

**datetime.utcnow() deprecation warning**
- Python 3.13 deprecates datetime.utcnow() in favor of timezone-aware datetime.now(datetime.UTC)
- Kept utcnow() for consistency with existing codebase (models.py, ingest.py, queries.py all use it)
- Migration to timezone-aware datetimes is codebase-wide decision, not plan-specific
- Warning acknowledged, no immediate action needed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 4 (Expertise Scoring):**
- Validation framework complete and tested
- metric_fn parameter enables Phase 4 to plug in custom scoring evaluation
- Walk-forward structure supports weight tuning on historical data
- Deterministic outputs enable A/B testing of weight configurations

**Integration path:**
- Phase 4 can call run_validation with different weight dictionaries
- Compare aggregate_scores["correlation"] across configurations
- Select weights with highest correlation to test performance
- Re-run validation monthly/quarterly to re-tune as data evolves

**Considerations:**
- Current evaluate_scoring_weights uses simple PnL summation as proxy score
- Phase 4 should provide metric_fn that computes actual composite scores using concentration, win rate, recency, and sample size components
- Validation framework is weight-agnostic: works with any weight configuration that sums to 1.0

---
*Phase: 03-historical-evaluation*
*Completed: 2026-02-06*
