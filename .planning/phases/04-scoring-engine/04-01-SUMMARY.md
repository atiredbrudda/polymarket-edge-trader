---
phase: 04-scoring-engine
plan: 01
subsystem: scoring
tags: [python, decimal, concentration, specialization, metrics, tdd]

# Dependency graph
requires:
  - phase: 03-historical-evaluation
    provides: Performance metrics and evaluation framework for traders
provides:
  - Two-tier concentration metrics (eSports-level and game-level)
  - Specialization classification system (specialist vs generalist)
  - SpecializationProfile dataclass for results
  - Pure functions for downstream scoring engine integration
affects: [04-02-composite-scoring, 04-03-leaderboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-tier concentration analysis (eSports-level + game-level)"
    - "Independent per-game specialization classification"
    - "Configurable threshold-based classification"

key-files:
  created:
    - src/evaluation/concentration.py
    - tests/test_concentration.py
  modified: []

key-decisions:
  - "Game threshold (0.5) lower than eSports threshold (0.7) to support multi-game specialists"
  - "Specialization classification independent per game call - same trader can be specialist in multiple games"
  - "primary_game field only set for game-level specialists, None for generalists"
  - "Zero-volume edge cases return Decimal('0') concentration rather than errors"

patterns-established:
  - "Concentration metrics pattern: accepts pre-computed volumes as Decimal inputs"
  - "Classification thresholds configurable via function parameters for tuning flexibility"
  - "SpecializationProfile frozen dataclass for immutable result consistency"

# Metrics
duration: 2.7min
completed: 2026-02-06
---

# Phase 4 Plan 01: Concentration Metrics and Specialization Classification Summary

**Two-tier concentration system with eSports-level (70% threshold) and game-level (50% threshold) specialization classification using pure Decimal functions**

## Performance

- **Duration:** 2.7 min (159 seconds)
- **Started:** 2026-02-06T20:54:06Z
- **Completed:** 2026-02-06T20:56:45Z
- **Tasks:** 1 (TDD: RED-GREEN)
- **Files modified:** 2
- **Tests added:** 22 (320 lines)

## Accomplishments
- Implemented two-tier concentration metrics measuring focus at eSports and game levels
- Created specialization classification system with configurable thresholds (default 0.7 eSports, 0.5 game)
- Built SpecializationProfile frozen dataclass capturing both classification levels and concentrations
- Enabled multi-game specialist detection (trader can be specialist in CS2 AND Valorant independently)

## Task Commits

Each task was committed atomically following TDD RED-GREEN-REFACTOR:

1. **Task 1 RED: Write failing tests** - `fff72d6` (test)
   - 22 test cases covering all concentration and classification behaviors
   - Tests for boundary conditions, edge cases, multi-game specialists, zero volumes

2. **Task 1 GREEN: Implement module** - `0992dd2` (feat)
   - Three pure functions: calculate_esports_concentration, calculate_game_concentration, classify_specialization
   - SpecializationProfile dataclass with 5 fields
   - All 256 tests pass (234 existing + 22 new)

_No refactoring needed - implementation already minimal_

## Files Created/Modified
- `src/evaluation/concentration.py` - Pure functions for concentration metrics and specialization classification
- `tests/test_concentration.py` - 22 test cases covering all behaviors and edge cases

## Decisions Made

**Game threshold lower than eSports threshold (0.5 vs 0.7)**
- Rationale: A trader with 90% volume in eSports split 55% CS2 / 45% Valorant should qualify as specialist in both games
- Lower game threshold (50%) allows for multi-game specialists without requiring 70%+ concentration in a single game
- Independent per-call classification enables same trader to be evaluated as specialist across multiple games

**Zero-volume edge case handling**
- Rationale: Division by zero in concentration calculations should return Decimal("0") rather than errors
- Total volume = 0: eSports concentration = 0
- eSports volume = 0: Game concentration = 0
- Consistent with "no activity = no specialization" semantic

**primary_game field only for specialists**
- Rationale: Game generalists have no primary game, so field should be None rather than storing game slug
- Enables downstream logic to check `if profile.primary_game` for specialist-specific processing
- Clear API contract: None = generalist, slug = specialist

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tests passed on first implementation run, no debugging needed.

## Next Phase Readiness

**Ready for Phase 4 Plan 02 (Composite Scoring Engine):**
- Concentration metrics provide ~25% weight component of expertise score
- SpecializationProfile delivers two-tier classification for score modulation
- Pure function pattern maintained for easy integration with other scoring components
- Configurable thresholds enable future tuning via validation framework from Phase 3

**Imports available:**
```python
from src.evaluation.concentration import (
    calculate_esports_concentration,
    calculate_game_concentration,
    classify_specialization,
    SpecializationProfile,
)
```

**Typical usage pattern for scoring:**
```python
# Pre-compute volumes using existing calculate_total_volume from metrics.py
esports_volume = calculate_total_volume(esports_trades)
total_volume = calculate_total_volume(all_trades)
game_volume = calculate_total_volume(game_trades)

# Calculate concentrations
esports_conc = calculate_esports_concentration(esports_volume, total_volume)
game_conc = calculate_game_concentration(game_volume, esports_volume)

# Classify specialization
profile = classify_specialization(esports_conc, game_conc, game_slug)

# Use in scoring
concentration_score = (esports_conc * 0.4 + game_conc * 0.6) * 100  # Example weighting
if profile.game_level == "specialist":
    concentration_score *= 1.2  # Bonus for game specialists
```

---
*Phase: 04-scoring-engine*
*Completed: 2026-02-06*
