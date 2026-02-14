# Review Queue

## Reviewer Notes for Worker

Read this section before starting work. These are patterns the reviewer has flagged from previous reviews.

1. **When changing a function's return signature, update all test mocks too.** In 10-02, `_get_dependencies` went from 4-tuple to 5-tuple but `tests/test_cli_research.py` still mocked it as 4-tuple, causing a regression. Before submitting, grep test files for mocks of any function you modified: `grep -r "function_name" tests/`
2. **Do not reformat existing code.** The executor model keeps line-wrapping existing `mapped_column()` and import lines. Only change lines you need to change functionally. Cosmetic reformatting creates noise in diffs and slows review.

## Pending Review

_No entries._

## Re-Review

_No entries._

## Review Feedback

_No entries._

## Cleared

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
- **Notes:** 29/29 phase 12 tests pass, 0 new regressions. Heavy cosmetic reformatting cleaned up during review (models.py went from +186/-62 to +2 lines). Added reviewer note about reformatting.

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
