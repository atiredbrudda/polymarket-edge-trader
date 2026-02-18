# Review Queue

## Reviewer Notes for Worker

Read this section and the AGENTS.md file in project root before starting work. Read `.planning/HANDOFF_PROTOCOL.md` for full protocol. These are patterns the reviewer has flagged from previous reviews — every one corresponds to a real rejection.

1. **When changing a function's return signature, update all test mocks too.** Before submitting, grep test files for mocks of any function you modified: `grep -r "function_name" tests/`
2. **Do not reformat existing code.** Only change lines you need to change functionally. Cosmetic reformatting = automatic rejection.
3. **When switching API endpoints, update tests that mock the old endpoint.**
4. **Remove debug hardcodes before submitting.**
5. **Attach debug summaries to all significant changes.**
6. **Run `bash scripts/worker_validate.sh` before pushing.** If it shows regressions, fix them.

## Review Feedback

(empty — no active feedback)

## Pending Review

### worker/backfill-batch-optimization — 2026-02-18
- **Task:** Optimize backfill speed with batch JBecker parquet queries
- **Branch:** worker/backfill-batch-optimization
- **Commits:** a94c62d..8cc9453 (functional: a94c62d, fda3f32, 705cfc3)
- **Files changed:**
  - src/datasources/jbecker.py (MODIFIED - batch_query_traders_history method)
  - src/pipeline/ingest.py (MODIFIED - prefetched_trades param, batch in backfill loop, blockchain warning)
  - src/cli/commands.py (MODIFIED - batch prefetch in CLI backfill command)
  - tests/datasources/test_jbecker.py (MODIFIED - 4 batch query tests)
  - tests/pipeline/test_ingest_blockchain.py (FIXED - updated tests using removed prefer_blockchain)
  - .planning/debug/resolved/backfill-frozen-on-trader.md (NEW - debug summary)
- **Worker notes:**
  - Original problem: N parquet scans for N traders (slow)
  - Solution: batch_query_traders_history() fetches all in one scan
  - Debug finding: CLI backfill wasn't using batch optimization (fixed)
  - Bonus: Blockchain fallback now warns "6-7 HOURS" instead of silent freeze
- **Validation:** 7 failed, 591 passed (2 tests fixed vs baseline 9 failures, 0 new regressions)

## Cleared

### worker/fix-9-test-failures — 2026-02-18
- **Branch:** worker/fix-9-test-failures
- **Cleared by:** Opus 4.6
- **Files in scope:**
  - tests/test_ingest.py (Group B + C fixes)
  - tests/test_api_client.py (Group A fixes)
  - tests/pipeline/test_ingest_blockchain.py (Group D fixes)
- **Notes:** Zero src/ changes. All 4 groups correct: httpx mocks for Data API, Market rows for discover, get_trader_trades for ingest, prefer_blockchain param removed. 587 tests pass, 0 failures.

### worker/fix-lsp-errors — 2026-02-18
- **Branch:** worker/fix-lsp-errors (stack: proxy-address-resolution, esports-backfill-fix, fix-lsp-errors)
- **Cleared by:** Opus 4.6
- **Reviewer fix:** Moved inline `import httpx` and `import time as _time` to module level in ingest.py
- **Notes:** LSP attr fixes (specialization_label, win_rate_component, None filter in queries). Proxy resolution (4 new Trader columns, get_public_profile, resolve-profiles CLI). eSports backfill (snake_case parquet schema, taxonomy-based category routing). 585 tests pass, 9 pre-existing failures.

## Previously Cleared

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
