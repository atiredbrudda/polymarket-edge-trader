---
phase: 09-alert-system-pipeline-health
plan: "02"
subsystem: health
tags: [health, preflight, cli, psutil, shutil, sqlite, tdd]
dependency_graph:
  requires: [health/notify.py, health/log.py, health_log schema, psutil]
  provides: [health/checks.py, commands/health_check.py]
  affects: [cron script, plans 09-03]
tech_stack:
  added: []
  patterns: [TDD red-green, Click CLI --db-path pattern, patch-at-import-site]
key_files:
  created:
    - src/polymarket_analytics/health/checks.py
    - src/polymarket_analytics/commands/health_check.py
  modified:
    - src/polymarket_analytics/commands/__init__.py
    - tests/test_health.py
decisions:
  - health-check uses --db-path CLI option (default data/analytics.db) — NicheConfig has no db_path attribute
  - patch targets use import-site paths (polymarket_analytics.commands.health_check.*) not source module paths
  - staleness is warn not fail — per D-08, stale scores degrade quality but don't block the cron cycle
  - sys.exit(1) called after send_alert to ensure alert fires before process exits
metrics:
  duration: "8 min"
  completed_date: "2026-04-11"
  tasks_completed: 2
  files_changed: 4
---

# Phase 09 Plan 02: Pre-flight Health Checks Summary

**One-liner:** Per-cron pre-flight gate (memory/disk/staleness) with dual-channel alert-and-skip on failure — 15 tests pass, 3 plan-09-03 stubs remain skipped.

## What Was Built

### Task 1: `health/checks.py` — pre-flight check functions (TDD)

- **`preflight_checks(db_path)`** — runs memory check (psutil.virtual_memory().available, threshold 500 MB) and disk check (shutil.disk_usage, threshold 10 GB). Returns list of `{name, status, value, threshold, message}` dicts. Status is "pass" or "fail".
- **`check_lift_scores_freshness(db, niche)`** — queries `MAX(computed_at)` from lift_scores for the niche. Returns "warn" if >5h old or never computed, "pass" otherwise. Never returns "fail" — staleness degrades quality but doesn't block the cycle (per D-08).
- Constants: `MEMORY_THRESHOLD_MB = 500`, `DISK_THRESHOLD_GB = 10`, `STALENESS_HOURS = 5`.

### Task 2: `commands/health_check.py` — Click CLI + alert-and-skip logic

- **`health-check --tier cron [--stages-failed NAMES] [--db-path PATH]`** — pre-flight gate for cron scripts.
- Runs memory + disk preflight, lift_scores freshness check, and optional stage exit code check (from `--stages-failed`).
- Displays Rich table of results. Logs to `health_log` table.
- On any "fail" check: calls `send_alert` (both channels), prints red PRE-FLIGHT FAILED message, exits 1 — cron script skips the cycle.
- On "warn" only: sends warning alert but exits 0 — cycle proceeds.
- On all "pass": exits 0 with green confirmation.
- Per D-05: no `os.kill`, `terminate`, or process killing anywhere.
- Registered via `import polymarket_analytics.commands.health_check` in `commands/__init__.py`.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | health/checks.py — preflight functions (TDD) | 8805654 | health/checks.py, tests/test_health.py |
| 2 | health-check CLI command | af40abb | commands/health_check.py, commands/__init__.py, tests/test_health.py |

## Test Results

```
15 passed, 3 skipped in 0.30s
```

All 15 active tests pass:
- `test_preflight_memory_fail` — mock 200 MB → status="fail"
- `test_preflight_memory_pass` — mock 2 GB → status="pass"
- `test_preflight_disk_fail` — mock 5 GB free → status="fail"
- `test_preflight_disk_pass` — mock 50 GB free → status="pass"
- `test_staleness_warn` — 6h old computed_at → status="warn"
- `test_staleness_pass` — 1h old computed_at → status="pass"
- `test_staleness_never_computed` — empty table → status="warn", message contains "never"
- `test_preflight_fail_sends_alert` — CLI exit 1, send_alert called with "FAILED" title
- `test_cron_check_all_pass` — CLI exit 0, health_log row with status="pass"
- Plus 6 existing plan 09-01 tests (all still pass)

3 skipped stubs are for plan 09-03 (daily/weekly summaries).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] NicheConfig has no db_path attribute**
- **Found during:** Task 2 implementation
- **Issue:** Plan's code template used `config.db_path` but `NicheConfig` only has `tag_id`, `slug`, `min_positions`, `scoring_window_days`, `entity_fields`, `event_slug_prefixes`. No `db_path` field.
- **Fix:** Added `--db-path` Click option (default `data/analytics.db`) following the same pattern as `detect`, `score`, and all other commands.
- **Files modified:** `src/polymarket_analytics/commands/health_check.py`
- **Commit:** af40abb

**2. [Rule 1 - Bug] Wrong patch targets in tests**
- **Found during:** Task 2 test writing
- **Issue:** Plan's test stubs patched `polymarket_analytics.health.checks.preflight_checks` but the command module imports the functions with `from ... import`, so the bound name is `polymarket_analytics.commands.health_check.preflight_checks`. Same for `send_alert` and `init_database`.
- **Fix:** All patch targets updated to `polymarket_analytics.commands.health_check.*` (import-site patching).
- **Files modified:** `tests/test_health.py`
- **Commit:** af40abb

## Known Stubs

None — all implemented functionality is fully wired. The 3 `pytest.mark.skip` entries are plan 09-03 stubs (daily/weekly summaries), correctly deferred.

## Threat Model Coverage

| Threat | Status |
|--------|--------|
| T-09-04 — DoS via tight cron loop | Accepted — 4h cron interval, health_log provides audit trail |
| T-09-05 — sys.exit(1) privilege escalation | Accepted — exit 1 only signals "skip" to calling script |

## Self-Check: PASSED

- `src/polymarket_analytics/health/checks.py` — FOUND
- `src/polymarket_analytics/commands/health_check.py` — FOUND
- Commit 8805654 — FOUND
- Commit af40abb — FOUND
