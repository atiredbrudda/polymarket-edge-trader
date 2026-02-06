---
phase: 03-historical-evaluation
plan: 03
subsystem: evaluation
tags: [consistency-detection, cross-timeframe-analysis, streak-analysis, decimal, statistics]

# Dependency graph
requires:
  - phase: 03-01
    provides: Performance metrics calculator (calculate_win_rate, PnL functions)
  - phase: 03-02
    provides: Profile classification (get_profile_consistency_bar, selective vs active thresholds)
provides:
  - Cross-timeframe consistency detection (stable vs streaky signals)
  - Streak pattern analysis (alternating vs clustered)
  - Profile-specific consistency bars
  - ConsistencyResult dataclass with complete analysis
affects: [03-04-calibration, 04-expertise-scoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cross-timeframe variance analysis for consistency detection"
    - "Streak length and alternation rate calculation"
    - "Profile-specific thresholds (selective: <100 variance, active: <50)"

key-files:
  created:
    - src/evaluation/consistency.py
    - tests/test_consistency.py
  modified: []

key-decisions:
  - "7d window excluded from consistency analysis (too noisy for meaningful comparison)"
  - "Sparse threshold: 5 resolved markets minimum for confidence"
  - "Min 2 qualifying timeframes required for consistency determination"
  - "Alternation rate threshold: 0.4 (alternating >= 0.4, clustered < 0.4)"
  - "All-wins or all-losses edge case: default to 'alternating' (no streak clustering evidence)"

patterns-established:
  - "Variance-based consistency scoring: 100 - variance, clamped to [0, 100]"
  - "Low confidence windows flagged separately from insufficient data signal"
  - "Primary signal (cross-timeframe) and secondary signal (streaks) kept separate for composability"

# Metrics
duration: 3.75min
completed: 2026-02-06
---

# Phase 3 Plan 3: Consistency Detection Summary

**Cross-timeframe stability and streak analysis distinguish genuine experts from lucky streaks using variance thresholds and alternation rates**

## Performance

- **Duration:** 3.75 min
- **Started:** 2026-02-06T18:06:00Z
- **Completed:** 2026-02-06T18:09:45Z
- **Tasks:** 1 (TDD: test + feat commits)
- **Files modified:** 2
- **Tests:** 20 (all passing)

## Accomplishments

- Cross-timeframe consistency detection via win rate variance across 30d/90d/all-time windows
- Profile-specific consistency bars (selective: variance <100, active: variance <50)
- Streak analysis with alternation rate and max streak tracking
- Low-confidence window detection (< 5 resolved markets)
- ConsistencyResult dataclass with complete analysis output

## Task Commits

TDD cycle for consistency detection:

1. **Task 1 (RED): Add failing tests** - `ea94fd8` (test)
2. **Task 1 (GREEN): Implement consistency detection** - `b91498c` (feat)

**Total:** 2 commits (TDD test + feat)

## Files Created/Modified

### Created
- `src/evaluation/consistency.py` - Pure functions for consistency detection
  - `calculate_consistency()`: Cross-timeframe stability analysis
  - `analyze_streaks()`: Streak pattern detection
  - `ConsistencyResult`: Frozen dataclass with full analysis
- `tests/test_consistency.py` - 20 tests covering all consistency scenarios

### Key Functions

**calculate_consistency(positions_by_timeframe, profile_type, sparse_threshold=5)**
- Calculates win rate variance across 30d/90d/all-time windows (7d excluded)
- Returns `ConsistencyResult` with:
  - `is_consistent`: bool (True if variance < profile bar)
  - `consistency_score`: Decimal (0-100, higher = more consistent)
  - `primary_signal`: "stable", "streaky", or "insufficient_data"
  - `timeframe_win_rates`: dict[str, Decimal | None]
  - `win_rate_variance`: Decimal | None
  - `low_confidence_windows`: list[str] (< 5 resolved markets)
  - `profile_type`: "selective" or "active"

**analyze_streaks(outcomes)**
- Analyzes chronological outcome sequences
- Returns:
  - `max_win_streak`, `max_loss_streak`: int
  - `avg_streak_length`: Decimal
  - `alternation_rate`: Decimal (transitions / total)
  - `signal`: "alternating" or "clustered"

## Decisions Made

**1. 7d window excluded from consistency analysis**
- Rationale: Too noisy for meaningful cross-timeframe comparison
- Implementation: Only 30d/90d/all used for variance calculation
- Impact: More reliable consistency signal, reduces false positives

**2. Sparse threshold: 5 resolved markets**
- Rationale: Research-backed minimum for statistical confidence
- Implementation: Windows with < 5 resolved flagged as low-confidence
- Impact: Avoids drawing conclusions from insufficient data

**3. Minimum 2 qualifying timeframes required**
- Rationale: Need at least 2 data points to calculate meaningful variance
- Implementation: < 2 qualifying → "insufficient_data" signal
- Impact: Honest about data quality, prevents false consistency claims

**4. Alternation rate threshold: 0.4**
- Rationale: 40% alternation is reasonable cutoff between alternating and clustered
- Implementation: >= 0.4 → "alternating", < 0.4 → "clustered"
- Impact: Distinguishes consistent traders from lucky streaks

**5. All-wins/all-losses edge case handling**
- Rationale: Single outcome type shows no clustering evidence
- Implementation: alternation_rate = 0 → default to "alternating"
- Impact: Avoids misclassifying perfect records as clustered streaks

## Deviations from Plan

None - plan executed exactly as written.

Plan specified:
- Cross-timeframe stability as primary signal ✓
- Streak analysis as secondary signal ✓
- Different consistency bars per profile ✓
- Sparse window flagging ✓
- All functions implemented per spec ✓

## Issues Encountered

None - TDD cycle smooth, all tests passed after initial implementation.

## Test Coverage

**Cross-timeframe consistency (10 tests):**
- Stable trader detection (selective and active profiles)
- Streaky trader detection (high variance)
- Low confidence window flagging
- Insufficient data handling (only 1 qualifying window, all low-confidence)
- Empty positions handling
- Voided market exclusion

**Streak analysis (10 tests):**
- Perfect alternation detection
- Clustered streak detection
- Mixed alternation patterns
- Void/flat outcome exclusion
- Empty outcomes handling
- Single outcome handling
- All-wins/all-losses edge cases
- Average streak length calculation
- Long streak detection

## Next Phase Readiness

**Ready for:**
- **03-04 Calibration scoring:** ConsistencyResult provides consistency_score and signals for weighting
- **04-01 Expertise scoring:** Consistency metrics ready for composite score calculation

**Dependencies satisfied:**
- Imports from metrics.py (calculate_win_rate) ✓
- Imports from profiles.py (get_profile_consistency_bar) ✓
- Pure functions, Decimal arithmetic ✓
- Duck-typed inputs ✓

**No blockers.**

---
*Phase: 03-historical-evaluation*
*Completed: 2026-02-06*
