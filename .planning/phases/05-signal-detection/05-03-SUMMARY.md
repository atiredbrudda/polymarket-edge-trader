---
phase: 05-signal-detection
plan: 03
subsystem: signals
tags: [pipeline, orchestration, consensus, confidence, signals, append-only, dataclass]

# Dependency graph
requires:
  - phase: 05-01
    provides: Pure functions for consensus detection and confidence scoring
  - phase: 05-02
    provides: SignalSnapshot model and query layer for signal storage
  - phase: 04-03
    provides: ExpertiseScore model and scoring patterns
provides:
  - Signal detection pipeline orchestration with refresh_market_signal, refresh_all_signals, get_ranked_signals
  - SignalResult dataclass for pipeline output
  - Signal lost detection with inactive snapshot creation
  - Time-window filtered views (1h/6h/24h) for SGNL-04
  - assess_herding stub (deferred per user decision)
  - Integration tests proving end-to-end signal flow
affects: [06-alerting, Phase 6 delivery logic, CLI signal display, webhook consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Orchestration pipeline pattern from scoring_pipeline.py
    - Append-only signal history for Phase 6 delta detection
    - Signal lost detection with inactive snapshots
    - Time-window filtering for ranked signals

key-files:
  created:
    - src/signals/pipeline.py
    - tests/test_signal_pipeline.py
  modified: []

key-decisions:
  - "SignalSnapshot uses expert_addresses_json field for CSV storage"
  - "Signal lost detection creates inactive snapshots when consensus drops"
  - "Herding stub returns 'not_analyzed' - deferred per user decision in CONTEXT.md"
  - "Time-window filtering applied at query layer for 1h/6h/24h views"

patterns-established:
  - "Pipeline orchestration: query → pure functions → confidence → persistence → result dataclass"
  - "Signal lost detection: track previously active directions, create inactive snapshots on consensus drop"
  - "Append-only history: multiple snapshots per market preserved for delta analysis"

# Metrics
duration: 6min
completed: 2026-02-07
---

# Phase 5 Plan 3: Signal Pipeline Summary

**End-to-end signal detection pipeline with consensus detection, confidence scoring, append-only history, and time-window ranking**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-07T01:24:13Z
- **Completed:** 2026-02-07T01:30:05Z
- **Tasks:** 2
- **Files modified:** 2 created

## Accomplishments
- Complete signal detection pipeline orchestrating consensus → confidence → persistence → output
- Signal lost detection creating inactive snapshots when consensus drops below thresholds
- Time-window filtered views (1h/6h/24h) for ranked signals via get_ranked_signals
- 13 integration tests proving end-to-end flow including batch processing and history preservation
- All 362 tests passing (307 existing + 42 Phase 5-01 + 13 Phase 5-03)

## Task Commits

Each task was committed atomically:

1. **Task 1: Signal pipeline orchestration** - `534779d` (feat)
2. **Task 2: Pipeline integration tests** - `0060fb2` (test)

## Files Created/Modified
- `src/signals/pipeline.py` - Orchestration layer connecting pure detection functions to database, with refresh_market_signal, refresh_all_signals, get_ranked_signals, and assess_herding stub
- `tests/test_signal_pipeline.py` - 13 integration tests covering consensus detection, signal lost handling, batch processing, time-window filtering, append-only history

## Decisions Made

**1. SignalSnapshot field naming**
- Database model uses `expert_addresses_json` (not `expert_addresses`)
- CSV string format for expert address storage
- Discovered during testing, fixed in pipeline code

**2. Signal lost detection strategy**
- Query signal history to find previously active directions
- Create inactive snapshot (confidence=0, expert_count=0) when consensus drops
- Preserves append-only pattern for Phase 6 delta detection
- Separate handler for "no expert positions" case

**3. Herding stub implementation**
- assess_herding() always returns "not_analyzed"
- Docstring explains deferral per user decision in Phase 5 CONTEXT.md
- Satisfies SGNL-03 requirement formally with minimal stub
- Full implementation would require temporal clustering analysis

**4. Time-window filtering approach**
- Applied at query layer using get_markets_by_expert_activity
- Filters SignalSnapshot results to markets with recent expert activity
- Supports 1h/6h/24h views per SGNL-04 requirement

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed database field name mismatch**
- **Found during:** Task 2 (integration test execution)
- **Issue:** SignalSnapshot uses expert_addresses_json field, not expert_addresses. Pipeline code used wrong field name causing TypeError on snapshot creation.
- **Fix:** Updated pipeline.py to use expert_addresses_json for all SignalSnapshot instantiation. Updated test fixtures to match. Updated get_ranked_signals to parse from expert_addresses_json.
- **Files modified:** src/signals/pipeline.py, tests/test_signal_pipeline.py
- **Verification:** All 13 integration tests pass
- **Committed in:** 0060fb2 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed test Market model field usage**
- **Found during:** Task 2 (test execution)
- **Issue:** Test fixtures used non-existent Market fields (market_type, detail_categories). Market model only has: condition_id, question, category, end_date, outcome, active, tokens.
- **Fix:** Removed market_type and detail_categories from all Market instantiations in test fixtures
- **Files modified:** tests/test_signal_pipeline.py
- **Verification:** All 13 integration tests pass, full suite passes (362 tests)
- **Committed in:** 0060fb2 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both bugs discovered during testing)
**Impact on plan:** Both fixes necessary for correct database interaction and test execution. No scope changes.

## Issues Encountered

**Database schema inspection needed during testing**
- Checked SignalSnapshot model to discover expert_addresses_json field name
- Checked Market model to confirm valid fields for test fixtures
- Resolved by reading src/db/models.py and adjusting code accordingly
- Standard TDD iteration, no plan changes needed

## Next Phase Readiness

**Phase 5 Signal Detection COMPLETE**
- All 3 plans finished: 05-01 (detection/confidence), 05-02 (database layer), 05-03 (pipeline)
- Total Phase 5 tests: 55 (27 from 05-01, 15 from 05-02, 13 from 05-03)
- Total project tests: 362 (307 pre-Phase 5 + 55 Phase 5)
- All SGNL requirements satisfied:
  - SGNL-01: Consensus detection ✓ (detect_consensus with thresholds)
  - SGNL-02: Confidence scoring ✓ (calculate_confidence_score with weighted formula)
  - SGNL-03: Herding stub ✓ (assess_herding returns "not_analyzed")
  - SGNL-04: Time-window ranking ✓ (get_ranked_signals with 1h/6h/24h)
  - SGNL-05: Confidence formula ✓ (60% agreement + 30% sample + 10% uniformity)

**Ready for Phase 6: Alerting & Delivery**
- SignalSnapshot append-only history ready for delta detection
- get_latest_signals provides current state for alert generation
- get_signal_history enables strength change tracking
- get_ranked_signals provides time-window views for CLI/webhooks
- First-mover and follower classifications tracked as metadata

**Calibration note:**
- Consensus thresholds (min_experts=3, min_agreement_pct=75%) are hypotheses
- Confidence formula weights (60/30/10) are from research
- Validation against historical data needed (Phase 7 backtest opportunity)

---
*Phase: 05-signal-detection*
*Completed: 2026-02-07*
