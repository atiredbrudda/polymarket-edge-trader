# Review Queue

## Reviewer Notes for Worker

Read this section before starting work. These are patterns the reviewer has flagged from previous reviews.

1. **When changing a function's return signature, update all test mocks too.** In 10-02, `_get_dependencies` went from 4-tuple to 5-tuple but `tests/test_cli_research.py` still mocked it as 4-tuple, causing a regression. Before submitting, grep test files for mocks of any function you modified: `grep -r "function_name" tests/`

2. **When switching API endpoints, update tests that mock the old endpoint.** In worker/debugging, `get_markets()` was replaced by `get_events()` but targeted scanning tests still mocked `get_markets`, causing 2 regressions.

3. **Remove debug hardcodes before submitting.** `ingest_active_markets()` had a hardcoded `test_condition_ids` list that bypassed normal operation — broke 2 tests and would have broken production.

4. **Attach debug summaries to all significant changes.** The /events migration (biggest change in the branch) had no debug session file explaining why or documenting the evidence. Debug summaries exist to give future readers context.

## Pending Review

(none)

## Cleared

### worker/debugging — 2026-02-16
- **Branch:** worker/debugging
- **Cleared by:** Opus 4.6 (reviewer)
- **Original items:** 3 debug sessions (Feb 14-15)
- **Files in scope:**
  - src/api/gamma_client.py
  - src/api/models.py
  - src/cli/commands.py
  - src/cli/scheduler.py
  - src/pipeline/ingest.py
  - src/db/models.py
  - tests/test_targeted_scanning.py (reviewer fix)
- **Issues found and fixed by reviewer:**
  1. 2 test regressions: targeted scanning tests mocked `get_markets` but code switched to `get_events` — updated tests
  2. Debug hardcode in `ingest_active_markets()` — removed, restored normal full-scan operation (also fixed 2 pre-existing test failures)
  3. Missing debug summary for /events migration — created `.planning/debug/events-endpoint-migration.md`
  4. Cosmetic reformatting of db/models.py (~120 lines) — reverted, kept only `start_date` field addition
  5. `end_date_max` passed as `start_date_max` to get_events — fixed to use actual `end_date_max` param (confirmed /events endpoint supports it)
  6. Debug JSON written unconditionally — gated behind `POLYMARKET_DEBUG` env var
- **Test result:** 9 failed (all pre-existing from main), 578 passed — 2 fewer failures than main (11→9) due to debug hardcode removal

### worker/10-02 — 2026-02-13
- **Plan:** 10-02 (Targeted Market Scanning - CLI Integration)
- **Cleared by:** Opus 4.6
- **Review commit:** 3b4dcde
- **Files in scope:**
  - src/pipeline/ingest.py
  - src/cli/commands.py
  - src/cli/scheduler.py
  - tests/test_targeted_scanning.py
  - tests/test_cli_research.py (reviewer fix)
- **Notes:** Good implementation. 1 regression found and fixed: test_batch_analyze_from_file broke because _get_dependencies mock returned 4-tuple instead of new 5-tuple. Lots of cosmetic reformatting in the diff (line wrapping) — functional changes are correct. 24/24 phase 10 tests pass, 0 net new regressions.

### worker/10-01 — 2026-02-13
- **Plan:** 10-01 (Targeted Market Scanning - Filter Engine)
- **Cleared by:** Opus 4.6
- **Review commit:** 094a202
- **Files in scope:**
  - src/api/gamma_client.py
  - src/pipeline/time_utils.py
  - tests/test_gamma_client.py
  - tests/test_time_utils.py
  - pyproject.toml
- **Notes:** Clean implementation, follows codebase patterns. 15/15 tests pass, 0 regressions. Merged to main.
