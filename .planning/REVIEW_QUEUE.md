# Review Queue

## Reviewer Notes for Worker

Read this section before starting work. These are patterns the reviewer has flagged from previous reviews.

1. **When changing a function's return signature, update all test mocks too.** In 10-02, `_get_dependencies` went from 4-tuple to 5-tuple but `tests/test_cli_research.py` still mocked it as 4-tuple, causing a regression. Before submitting, grep test files for mocks of any function you modified: `grep -r "function_name" tests/`
2. **Do not reformat existing code.** Only change lines you need to change functionally. Cosmetic reformatting creates noise in diffs and slows review.
3. **When switching API endpoints, update tests that mock the old endpoint.** In worker/debugging, `get_markets()` was replaced by `get_events()` but targeted scanning tests still mocked `get_markets`, causing 2 regressions.
4. **Remove debug hardcodes before submitting.** `ingest_active_markets()` had a hardcoded `test_condition_ids` list that bypassed normal operation — broke 2 tests and would have broken production.
5. **Attach debug summaries to all significant changes.** The /events migration (biggest change in the branch) had no debug session file explaining why or documenting the evidence. Debug summaries exist to give future readers context.
6. **Read the Worker Code Standards section in HANDOFF_PROTOCOL.md.** It covers all of the above in detail plus additional rules.

## Pending Review

### worker/esports-backfill-fix — 2026-02-16
- **Issue:** eSports trades not found during backfill (debug session)
- **Branch:** worker/esports-backfill-fix
- **Commits:** 91eb9b8
- **Files changed:**
  - src/cli/commands.py (MODIFIED) — Wired JBecker client into backfill command
  - src/datasources/converters.py (MODIFIED) — Rewrote to handle snake_case columns
  - src/pipeline/ingest.py (MODIFIED) — Added taxonomy lookup + Gamma API lookups
  - .planning/debug/esports-backfill-missing.md (NEW) — Debug summary
- **Worker notes:** Fixed 4 bugs: (1) converter used wrong column names, (2) JBecker not wired in backfill, (3) token→condition mapping missing, (4) new markets not classified. Also backfilled tokens for 398 markets via CLOB API and ran classification on 259 new markets. Result: sample trader 0→515 eSports trades.

### worker/proxy-address-resolution — 2026-02-16
- **Plan:** Proxy Address Resolution (WORKER_TASK_PROXY_RESOLUTION.md)
- **Branch:** worker/proxy-address-resolution
- **Commits:** 3917af0..3331e7f
- **Files changed:**
  - src/db/models.py (MODIFIED) — Added columns to Trader model
  - src/api/gamma_client.py (MODIFIED) — Added get_public_profile() method
  - src/pipeline/ingest.py (MODIFIED) — Added resolve_trader_profiles() method
  - src/cli/commands.py (MODIFIED) — Added resolve-profiles CLI command
  - tests/test_profile_resolution.py (NEW) — Tests for profile resolution
  - README.md (MODIFIED) — Added profile resolution documentation
- **Worker notes:** Implemented profile resolution to resolve proxy wallet addresses to real Polymarket profiles. Includes migration helper for existing databases. All 7 new tests pass. Fixed migration order issue (migration must run before count query).

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

### worker/12-01 — 2026-02-14
- **Plan:** 12-01, 12-02, 12-03 (Deep Niche Scoring - all 3 plans)
- **Cleared by:** Opus 4.6
- **Review commit:** dabdb05
- **Files in scope:**
  - src/db/models.py (taxonomy_depth column + index)
  - src/evaluation/concentration.py (tournament + team concentration)
  - src/pipeline/queries.py (get_positions_for_slug, get_taxonomy_leaderboard, get_all_slugs_with_positions_at_depth)
  - src/pipeline/scoring_pipeline.py (compute_taxonomy_scores, identify_hidden_specialists)
  - src/cli/commands.py (leaderboard --depth, expertise, specialists commands)
  - src/cli/formatters.py (format_expertise_breakdown, format_specialists_table)
  - tests/test_deep_scoring.py, tests/test_scoring_pipeline_deep.py, tests/test_cli_deep_scoring.py
- **Notes:** 29/29 phase 12 tests pass, 0 new regressions. Heavy cosmetic reformatting cleaned up during review (models.py went from +186/-62 to +2 lines). Added reviewer note about reformatting. **NOTE: This was docs-only (README updates) — Phase 12 code was never executed. Plans exist but no implementation.**

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
