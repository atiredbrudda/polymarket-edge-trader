---
phase: 25-lift-based-scoring-v2
plan: 02
subsystem: signals
tags: [lift-score, q5, consensus, signals, cli, analyze, expert-avg-entry]

# Dependency graph
requires:
  - phase: 25-01
    provides: LiftScore model, get_lift_leaderboard, compute_category_scores, MarketConfig

provides:
  - Signal detection using LiftScore Q5 (quintile==5) for expert identification
  - ConsensusResult and SignalResult with expert_avg_entry price context
  - polymarket analyze command: Q5 leaderboard + --signals mode
  - Sizing guidance in signals output (0-2 Q5 = 1%, 3+ Q5 = 2-3% bankroll)

affects: [alerting, CLI, Phase 26]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Caller pre-filters Q5 experts; detect_consensus trusts presence-in-dict"
    - "expert_avg_entry flows: ConsensusResult -> SignalResult for price context"
    - "analyze command is now the primary Q5 surface (leaderboard + signals modes)"

key-files:
  created:
    - tests/test_signal_enrichment.py
    - tests/test_cli_lift.py
  modified:
    - src/signals/queries.py
    - src/signals/pipeline.py
    - src/signals/detection.py
    - src/cli/commands.py
    - src/config/settings.py
    - tests/test_signal_pipeline.py
    - tests/test_signal_queries.py
    - tests/test_cli_deep_scoring.py
    - tests/test_cli.py

key-decisions:
  - "Q5 pre-filtering happens in query layer (queries.py); detect_consensus trusts dict membership — cleaner separation"
  - "expert_avg_entry = avg(avg_entry_price) per consensus direction; None when no prices available"
  - "analyze command fully replaces old entity-alpha batch/crawl mode"
  - "Settings.extra='ignore' added to handle ANTHROPIC_API_KEY in .env without crashing pydantic"

patterns-established:
  - "expert_scores dict passed to detect_consensus is Q5 pre-filtered; any trader in dict = expert"
  - "SignalResult.expert_avg_entry populated from ConsensusResult.expert_avg_entry"

requirements-completed: [LIFT-02, LIFT-03]

# Metrics
duration: 22min
completed: 2026-03-22
---

# Phase 25 Plan 02: Signal Detection Rewire + Analyze Command Summary

**Rewired signal detection from ExpertiseScore raw_score>70 to LiftScore quintile==5, added expert_avg_entry price context to ConsensusResult/SignalResult, and replaced the entity-alpha analyze command with a Q5 leaderboard + signals surface.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-03-22T13:14:13Z
- **Completed:** 2026-03-22T13:36:46Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Signal detection (queries.py, pipeline.py, detection.py) fully rewired from ExpertiseScore to LiftScore Q5; no ExpertiseScore references remain in signals module
- `ConsensusResult` gains `expert_avg_entry` field (avg entry price across Q5 positions in direction); `SignalResult` propagates it
- `polymarket analyze` rewritten: default mode shows Q5 leaderboard (Composite/CLV/ROI/Sharpe table); `--signals` mode shows active Q5 consensus with expert avg entry and sizing guidance
- Fixed `Settings` to accept unknown `.env` fields (`extra="ignore"`) and added `anthropic_api_key` field — this fixed pre-existing test failures affecting all CLI `--help` tests

## Task Commits

1. **Task 1: Rewire signal detection from ExpertiseScore to LiftScore Q5 + price-context enrichment** - `3dc820c` (feat)
2. **Task 2: Rewrite analyze command as Q5 surface + signals mode** - `4d25e83` (feat)
3. **Auto-fix: Settings extra='ignore' + stale CLI test updates** - `75f98d8` (fix)

## Files Created/Modified

- `src/signals/queries.py` - Rewired to LiftScore Q5; `get_expert_positions_for_market` and `get_markets_by_expert_activity` now filter `quintile==5`
- `src/signals/detection.py` - Added `expert_avg_entry` to `ConsensusResult`; changed filtering from `score > 70` to `trader_address in expert_scores`
- `src/signals/pipeline.py` - Rewired to LiftScore; added `expert_avg_entry` to `SignalResult`; `get_ranked_signals` also updated
- `src/cli/commands.py` - `analyze` command fully rewritten: `--crawl` removed, `--category` + `--signals` added; two helper functions `_run_analyze_leaderboard_mode` and `_run_analyze_signals_mode`
- `src/config/settings.py` - Added `anthropic_api_key: str | None = None` field + `extra="ignore"` to model_config
- `tests/test_signal_enrichment.py` - New: Q5 filtering tests, expert_avg_entry tests, pipeline integration
- `tests/test_cli_lift.py` - New: analyze command structure tests + leaderboard/signals logic tests
- `tests/test_signal_pipeline.py` - Updated fixtures: ExpertiseScore -> LiftScore Q5; added `expert_avg_entry=None` to existing SignalResult construction
- `tests/test_signal_queries.py` - Updated fixtures: ExpertiseScore -> LiftScore Q5
- `tests/test_cli_deep_scoring.py` - Updated stale tests: leaderboard --depth -> --category
- `tests/test_cli.py` - Updated stale test: GAME_SLUG -> --category

## Decisions Made

- Q5 pre-filtering in query layer is the right separation: `get_expert_positions_for_market` returns only Q5 positions; `detect_consensus` just trusts that all passed-in traders are experts
- `expert_avg_entry` uses simple arithmetic mean of non-None `avg_entry_price` values; None if no prices available
- The old `analyze` command (entity-alpha batch/crawl) is fully replaced — the functionality it provided is superseded by the Q5 leaderboard and signals surface
- `Settings.extra="ignore"` is the correct fix — the .env has keys like `ANTHROPIC_API_KEY` that pydantic's default strict mode rejects

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test_signal_pipeline.py and test_signal_queries.py fixtures from ExpertiseScore to LiftScore**
- **Found during:** Task 1 (rewire signal detection)
- **Issue:** Existing tests use ExpertiseScore fixtures to set up expert data; after rewiring to LiftScore, these tests would fail
- **Fix:** Updated all ExpertiseScore fixture blocks to LiftScore with quintile=5; added `make_lift_score` helper; updated import lines
- **Files modified:** tests/test_signal_pipeline.py, tests/test_signal_queries.py
- **Verification:** All 43 signal tests pass (previously tested ExpertiseScore behavior now tests LiftScore Q5 equivalent)
- **Committed in:** 3dc820c (Task 1 commit)

**2. [Rule 1 - Bug] Fixed Settings pydantic validation failure from ANTHROPIC_API_KEY in .env**
- **Found during:** Task 2 (writing analyze CLI tests)
- **Issue:** `ANTHROPIC_API_KEY` in `.env` but not in Settings model; `extra_forbidden` (default) caused ValidationError, breaking ALL CLI `--help` tests and any test invoking CLI commands
- **Fix:** Added `anthropic_api_key: str | None = None` field to Settings and `extra="ignore"` to model_config
- **Files modified:** src/config/settings.py
- **Verification:** All CLI tests (test_cli.py, test_cli_deep_scoring.py, test_cli_lift.py) pass
- **Committed in:** 75f98d8

**3. [Rule 1 - Bug] Updated stale CLI test assertions from old leaderboard flags to new ones**
- **Found during:** Task 2 verification
- **Issue:** test_cli_deep_scoring.py tested for --depth/--game in leaderboard (removed in Plan 01); test_cli.py tested for GAME_SLUG
- **Fix:** Updated assertions to match current leaderboard interface (--category, --top-n)
- **Files modified:** tests/test_cli_deep_scoring.py, tests/test_cli.py
- **Committed in:** 75f98d8

---

**Total deviations:** 3 auto-fixed (3 x Rule 1 - bug)
**Impact on plan:** All auto-fixes necessary for correctness. The Settings fix unblocked all CLI testing. The fixture updates ensured existing tests remained valid after the rewire.

## Issues Encountered

- `git stash` was accidentally run during verification, causing a merge conflict in commands.py and settings.py. Resolved by restoring committed versions with `git checkout HEAD -- <files>` and re-applying the `extra="ignore"` fix.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Signal detection is now fully Q5-based; ready for any downstream phase that queries signals
- `polymarket analyze` shows Q5 leaderboard and active consensus signals with price context
- `polymarket analyze --signals` provides the real-time decision tree output
- Prerequisite for any phase that wants to surface expert consensus signals to users

---
*Phase: 25-lift-based-scoring-v2*
*Completed: 2026-03-22*
