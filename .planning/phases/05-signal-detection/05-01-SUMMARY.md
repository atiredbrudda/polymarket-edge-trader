---
phase: 05-signal-detection
plan: 01
subsystem: signal-detection
tags: [consensus-detection, confidence-scoring, first-mover, python, decimal, tdd]

# Dependency graph
requires:
  - phase: 04-scoring-engine
    provides: ExpertiseScore model with raw_score field for expert identification (score > 70 threshold)
  - phase: 02-classification
    provides: Position tracking with entry_timestamp for first-mover identification
provides:
  - Pure functions for consensus detection among experts (3+ traders with score >70 agreeing on direction)
  - Confidence scoring algorithm (0-100) combining agreement %, sample size, and position uniformity
  - First-mover identification (earliest entry_timestamp) and follower classification (fast/independent)
affects: [05-02-signal-pipeline, 05-03-herding, signal-api, notification-system]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Consensus detection with two-threshold filtering (min_experts AND min_agreement_pct)"
    - "Agreement percentage uses total market experts as denominator (not just one direction)"
    - "Confidence formula: 60% agreement + 30% sample size (asymptotic) + 10% uniformity (CV)"
    - "FLAT positions excluded from consensus calculation (numerator and denominator)"
    - "First-mover metadata classification (fast_follower_hours=6 window)"

key-files:
  created:
    - src/signals/__init__.py
    - src/signals/detection.py
    - src/signals/confidence.py
    - tests/test_detection.py
    - tests/test_confidence.py
  modified: []

key-decisions:
  - "Expert threshold: raw_score > 70 (matches Phase 4 scoring engine convention)"
  - "Consensus thresholds: min_experts=3, min_agreement_pct=75% (configurable, defaults from research)"
  - "Agreement denominator: total experts in market across ALL directions (not just agreeing direction)"
  - "FLAT positions excluded: consensus only for LONG/SHORT directional positions"
  - "Confidence weights: 60% agreement, 30% sample size, 10% uniformity (from user research)"
  - "Sample size asymptotic: (1 - exp(-(n - min_experts) / 10)) * 100 (gradual reward for larger samples)"
  - "Uniformity via CV: coefficient of variation of position volumes, capped at 1.0"
  - "Fast follower window: 6 hours after first mover (metadata only, doesn't affect consensus)"

patterns-established:
  - "Pure function consensus detection: duck-typed inputs, no SQLAlchemy imports"
  - "Two-stage filtering: expert filter (score > 70) then direction filter (LONG/SHORT only)"
  - "ConsensusResult dataclass: frozen=True for immutability, includes first_mover_address"
  - "Volume proxy fallback: abs(size * avg_entry_price) if available, else abs(size)"

# Metrics
duration: 5.5min
completed: 2026-02-07
---

# Phase 5 Plan 1: Consensus Detection & Confidence Scoring

**Pure functions for expert consensus detection (3+ traders score >70, 75% agreement) with 0-100 confidence scoring combining agreement %, sample size, and position uniformity**

## Performance

- **Duration:** 5.5 min
- **Started:** 2026-02-07T01:11:19Z
- **Completed:** 2026-02-07T01:16:51Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 5
- **Tests added:** 27 (16 detection + 11 confidence)
- **Total tests:** 349 (322 existing + 27 new)

## Accomplishments
- Consensus detection with dual thresholds: min_experts=3 AND min_agreement_pct=75%
- Agreement percentage correctly uses total market experts as denominator (not just agreeing direction)
- FLAT positions excluded from both numerator and denominator
- Confidence scoring (0-100) with three weighted components: agreement (60%), sample size (30%), uniformity (10%)
- First-mover identification via earliest entry_timestamp
- Follower classification: first_mover, fast_follower (6-hour window), independent

## Task Commits

Each task was committed atomically following TDD protocol (RED → GREEN):

1. **Task 1: Consensus detection and first-mover identification**
   - RED: `d987064` (test: 16 failing tests)
   - GREEN: `63a86ac` (feat: implementation, all tests pass)

2. **Task 2: Confidence score calculation**
   - RED: `85c07f1` (test: 11 failing tests)
   - GREEN: `b73d682` (feat: implementation, all tests pass)

**Total commits:** 4 (2 RED + 2 GREEN)

## Files Created/Modified

### Created
- `src/signals/__init__.py` - Package exports with conditional imports for parallel plan execution
- `src/signals/detection.py` - detect_consensus, identify_first_mover, classify_followers pure functions
- `src/signals/confidence.py` - calculate_confidence_score with 3-component formula
- `tests/test_detection.py` - 16 tests covering consensus thresholds, FLAT exclusion, denominator logic, first-mover, followers
- `tests/test_confidence.py` - 11 tests covering formula components, edge cases, Decimal precision, asymptotic behavior

### Modified
None

## Decisions Made

1. **Expert threshold: raw_score > 70** - Matches Phase 4 scoring engine convention for expert identification
2. **Agreement denominator includes all directions** - 4 LONG + 1 SHORT = 80% agreement (not 100%), prevents inflated confidence from ignoring opposition
3. **FLAT positions excluded entirely** - Consensus is about directional alignment (LONG vs SHORT), FLAT is neutral exit
4. **Confidence formula weights from research** - 60% agreement (most important), 30% sample size (moderate), 10% uniformity (minor signal)
5. **Asymptotic sample size component** - (1 - exp(-(n - min_experts) / 10)) rewards larger samples but with diminishing returns
6. **Uniformity via coefficient of variation** - CV = std_dev / mean, capped at 1.0, rewards similar position sizes
7. **Fast follower window: 6 hours** - Metadata classification only, doesn't affect consensus or confidence calculations

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - TDD approach with comprehensive test coverage ensured clean implementation on first pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 5 Plan 2 (Signal Pipeline):**
- Pure functions tested and operational
- ConsensusResult dataclass with all required fields (market_id, direction, expert_count, agreement_percentage, first_mover_address)
- Confidence scoring ready for integration
- 349 tests passing, no regressions

**Calibration note:**
- Current thresholds (min_experts=3, min_agreement_pct=75%, fast_follower_hours=6) are configurable defaults
- Phase 5 Plan 3+ may include historical validation to tune these parameters
- Formula weights (60/30/10) are from user research, may benefit from backtesting

---
*Phase: 05-signal-detection*
*Completed: 2026-02-07*
