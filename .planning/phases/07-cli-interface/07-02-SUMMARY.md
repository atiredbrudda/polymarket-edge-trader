---
phase: 07-cli-interface
plan: 02
subsystem: cli-orchestration
tags: [scheduling, polling, sweep, orchestration, signal-handlers]

dependency-graph:
  requires:
    - 07-01 (CLI formatters and commands)
    - 06-03 (Alert delivery pipeline)
    - 05-03 (Signal detection pipeline)
    - 04-03 (Scoring pipeline)
    - 01-04 (Ingestion pipeline)
  provides:
    - run_sweep function (single full pipeline pass)
    - run_polling_loop function (automated repeating sweep)
    - poll CLI command (scheduled sweeps)
  affects:
    - Phase 7 Plan 03 (integration tests will use these functions)

tech-stack:
  added:
    - signal module for SIGINT/SIGTERM handling
    - time module for sleep intervals
  patterns:
    - Global shutdown flag with signal handlers
    - Try/except per stage with continue-on-failure
    - Dense one-line logging for operational monitoring
    - Graceful sleep with 1-second check intervals

key-files:
  created:
    - src/cli/scheduler.py (run_sweep and run_polling_loop functions)
    - tests/test_scheduler.py (9 tests with mocked pipeline functions)
  modified:
    - src/config/settings.py (added poll_interval_minutes)
    - src/cli/commands.py (added poll command)
    - src/cli/__init__.py (export scheduler functions)

decisions:
  - Continue-on-failure per stage: Each pipeline stage wrapped in try/except, failures logged but don't block subsequent stages (enables partial sweep completion)
  - Global shutdown flag: Simple flag-based approach for signal handling (avoids threading complexity)
  - Graceful sleep: Break sleep into 1-second intervals with shutdown check (enables fast shutdown response)
  - Stats dict return: run_sweep returns comprehensive stats dict for monitoring and testing
  - Optional alerter: Alerting optional via alerter=None or skip_alerts=True (enables dry-run mode)

metrics:
  duration: 3.55 minutes
  completed: 2026-02-11T02:42:38Z
  tests-added: 9
  tests-total: 438
  files-created: 2
  files-modified: 3
---

# Phase 7 Plan 02: Scheduled Polling with Orchestration Summary

**One-liner:** Sweep orchestration chains ingest → score → detect → alert stages with graceful shutdown polling loop

## Implementation

### run_sweep Function

Single full pipeline pass connecting all stages:

1. **Ingest Stage:** IngestionPipeline.run_full_sweep() → markets_ingested, traders_discovered
2. **Scoring Stage:** compute_all_game_scores() → scores_computed
3. **Signal Detection Stage:** refresh_all_signals() → signals_detected
4. **Alert Delivery Stage:** deliver_signal_alerts() → alerts_sent, alerts_failed (optional)

Each stage wrapped in try/except - failures logged without blocking subsequent stages.

Returns stats dict:
```python
{
    "markets_ingested": int,
    "traders_discovered": int,
    "scores_computed": int,
    "signals_detected": int,
    "alerts_sent": int,
    "alerts_failed": int,
    "duration_seconds": float,
}
```

### run_polling_loop Function

Repeating sweep with graceful shutdown:

1. Register SIGINT/SIGTERM signal handlers → set global _shutdown_flag
2. While not shutdown:
   - Call run_sweep()
   - Log dense one-line summary: `[Timestamp] Cycle N: X mkts, Y sigs, Z alerts (Ts)`
   - Graceful sleep (1-second intervals checking shutdown flag)
3. Log "Polling stopped gracefully"

### poll CLI Command

```bash
polymarket poll [--interval N] [--no-alerts] [--verbose]
```

- `--interval`: Override default poll_interval_minutes from Settings
- `--no-alerts`: Skip alert delivery (dry-run mode)
- `--verbose`: Enable DEBUG logging

Initializes all pipeline components and delegates to run_polling_loop.

### Settings Extension

Added `poll_interval_minutes: int = 60` to Settings class for configurable default polling interval.

## Test Coverage

**9 new tests** (all passing):

**run_sweep tests:**
- Returns stats dict with all expected keys
- Continues on ingest failure (logs error, proceeds to scoring)
- Continues on scoring failure
- Skips alerts when skip_alerts=True
- Skips alerts when alerter is None
- Delivers alerts when alerter provided

**run_polling_loop tests:**
- Respects shutdown flag (mock signal)
- Logs cycle stats correctly

**Signal handler tests:**
- Sets shutdown flag when called

All tests use mocked pipeline functions to avoid real API calls.

## Verification Results

```bash
# Scheduler tests
pytest tests/test_scheduler.py -v
# ✓ 9 passed in 0.67s

# Full test suite
pytest --tb=short -q
# ✓ 438 passed (429 previous + 9 new)
```

## Deviations from Plan

None - plan executed exactly as written.

## Key Design Choices

1. **Continue-on-failure:** Each stage independent - ingest failure doesn't prevent scoring/detection
2. **Global shutdown flag:** Simple flag-based approach chosen over threading.Event (matches plan signal handling requirements)
3. **Graceful sleep:** 1-second check intervals enable fast shutdown without busy-wait overhead
4. **Optional alerting:** Alerter can be None or skip_alerts=True for dry-run testing
5. **Dense logging:** One-line cycle summaries for operational monitoring (matches plan spec)

## Integration Points

**Upstream dependencies:**
- `IngestionPipeline.run_full_sweep()` from 01-04
- `compute_all_game_scores()` from 04-03
- `refresh_all_signals()` from 05-03
- `deliver_signal_alerts()` from 06-03

**Downstream consumers:**
- Phase 7 Plan 03 (integration tests will validate end-to-end flow)
- Production deployment (poll command for automated signal detection)

## Commits

All commits follow atomic per-task pattern:

- `5e3795a`: feat(07-02): add poll_interval_minutes to Settings
- `fefd2a7`: feat(07-02): implement sweep orchestration and polling loop
- `7e7b174`: feat(07-02): add poll command to CLI
- `4eb2a94`: feat(07-02): export scheduler functions from cli module
- `175379f`: test(07-02): add scheduler tests with mocked pipeline functions

## Self-Check: PASSED

**Created files exist:**
```bash
[ -f "src/cli/scheduler.py" ] && echo "FOUND: src/cli/scheduler.py" || echo "MISSING: src/cli/scheduler.py"
# FOUND: src/cli/scheduler.py

[ -f "tests/test_scheduler.py" ] && echo "FOUND: tests/test_scheduler.py" || echo "MISSING: tests/test_scheduler.py"
# FOUND: tests/test_scheduler.py
```

**Commits exist:**
```bash
git log --oneline --all | grep -q "5e3795a" && echo "FOUND: 5e3795a" || echo "MISSING: 5e3795a"
# FOUND: 5e3795a

git log --oneline --all | grep -q "fefd2a7" && echo "FOUND: fefd2a7" || echo "MISSING: fefd2a7"
# FOUND: fefd2a7

git log --oneline --all | grep -q "7e7b174" && echo "FOUND: 7e7b174" || echo "MISSING: 7e7b174"
# FOUND: 7e7b174

git log --oneline --all | grep -q "4eb2a94" && echo "FOUND: 4eb2a94" || echo "MISSING: 4eb2a94"
# FOUND: 4eb2a94

git log --oneline --all | grep -q "175379f" && echo "FOUND: 175379f" || echo "MISSING: 175379f"
# FOUND: 175379f
```

**Modified files contain expected patterns:**
```bash
grep -q "poll_interval_minutes" src/config/settings.py && echo "FOUND: poll_interval_minutes in settings" || echo "MISSING"
# FOUND: poll_interval_minutes in settings

grep -q "def poll" src/cli/commands.py && echo "FOUND: poll command" || echo "MISSING"
# FOUND: poll command

grep -q "run_sweep" src/cli/__init__.py && echo "FOUND: run_sweep export" || echo "MISSING"
# FOUND: run_sweep export
```

All files, commits, and patterns verified successfully.
