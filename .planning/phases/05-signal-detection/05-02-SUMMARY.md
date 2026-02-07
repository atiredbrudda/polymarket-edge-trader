---
phase: 05-signal-detection
plan: 02
subsystem: database
tags: [sqlalchemy, signals, queries, orm, sqlite]

# Dependency graph
requires:
  - phase: 04-scoring-engine
    provides: "ExpertiseScore append-only model with computed_at field"
  - phase: 02-classification-discovery
    provides: "Position model with last_trade_timestamp"
provides:
  - "SignalSnapshot append-only model for consensus history tracking"
  - "Signal query functions with max(computed_at) subquery pattern"
  - "Time-windowed expert activity filtering"
affects: [05-signal-detection, 06-alerting-webhooks]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Append-only signal snapshots matching ExpertiseScore pattern"
    - "max(computed_at) subquery for latest signal retrieval"
    - "Conditional imports in __init__.py for parallel plan execution"

key-files:
  created:
    - "src/signals/queries.py"
    - "tests/test_signal_queries.py"
  modified:
    - "src/db/models.py"
    - "src/signals/__init__.py"

key-decisions:
  - "SignalSnapshot uses append-only design with computed_at for history tracking"
  - "Position table ix_position_market_last_trade index for time-window queries"
  - "Conditional imports in signals/__init__.py to support parallel plan execution"
  - "get_markets_by_expert_activity uses datetime.now(UTC) not datetime.utcnow()"

patterns-established:
  - "Pattern 1: Latest signal per market via max(computed_at) subquery (matching ExpertiseScore pattern)"
  - "Pattern 2: Time-window filtering with expert score joins for activity ranking"

# Metrics
duration: 4.5min
completed: 2026-02-07
---

# Phase 05 Plan 02: Signal Database Layer Summary

**SignalSnapshot append-only model with max(computed_at) queries for consensus tracking and time-windowed expert activity filtering**

## Performance

- **Duration:** 4.5 min
- **Started:** 2026-02-07T01:11:52Z
- **Completed:** 2026-02-07T01:16:24Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- SignalSnapshot model with append-only design for consensus signal history
- Position table index optimization for time-window expert activity queries
- Four query functions using max(computed_at) subquery pattern for latest signals
- 15 integration tests covering all query patterns with time-window filtering

## Task Commits

Each task was committed atomically:

1. **Task 1: SignalSnapshot model and Position index** - `2526662` (feat)
2. **Task 2: Signal queries and integration tests** - `6cdc01f` (feat)

## Files Created/Modified
- `src/db/models.py` - SignalSnapshot model with 11 fields, 4 indexes; Position ix_position_market_last_trade index
- `src/signals/__init__.py` - Conditional imports for parallel plan execution (unblocks Plan 05-02)
- `src/signals/queries.py` - 4 query functions (get_latest_signals, get_signal_history, get_expert_positions_for_market, get_markets_by_expert_activity)
- `tests/test_signal_queries.py` - 15 integration tests with in-memory SQLite fixtures

## Decisions Made

**1. Append-only SignalSnapshot design**
- Rationale: Matches ExpertiseScore pattern, enables signal strength trend analysis for Phase 6 alerting
- Implementation: computed_at field with max() subquery for latest retrieval

**2. Position market+timestamp composite index**
- Rationale: get_markets_by_expert_activity needs efficient filtering by market_id + last_trade_timestamp
- Implementation: ix_position_market_last_trade index added to Position.__table_args__

**3. Conditional imports in signals/__init__.py**
- Rationale: Plan 05-01 and 05-02 run in parallel; __init__.py imports detection.py (Plan 05-01) and queries.py (Plan 05-02)
- Implementation: try/except blocks for each module, __all__ extends dynamically
- Benefit: Both plans execute independently without blocking each other

**4. UTC-aware datetime for time-window queries**
- Rationale: Avoid datetime.utcnow() deprecation warnings
- Implementation: datetime.now(UTC) in get_markets_by_expert_activity

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made signals/__init__.py imports conditional**
- **Found during:** Task 1 verification
- **Issue:** Test suite failed to collect due to ImportError - Plan 05-01 created __init__.py importing detection.py which doesn't exist yet (parallel execution)
- **Fix:** Wrapped all imports in try/except blocks, made __all__ extend dynamically based on available modules
- **Files modified:** src/signals/__init__.py
- **Verification:** Full test suite passes (307 existing tests + 15 new)
- **Committed in:** 2526662 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix to unblock parallel plan execution. No scope change.

## Issues Encountered
None - queries followed established patterns from src/pipeline/queries.py and src/pipeline/queries.py::get_game_leaderboard.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Signal database layer complete, ready for consensus detection pipeline (Plan 05-03)
- Query functions tested with 15 integration tests, all passing
- Time-window filtering operational for 1h, 6h, 24h expert activity detection
- Position index optimization in place for efficient market ranking

**Readiness notes:**
- Plan 05-01 (detection functions) running in parallel - completion order independent
- Plan 05-03 (pipeline) will integrate both detection functions and queries

---
*Phase: 05-signal-detection*
*Completed: 2026-02-07*
