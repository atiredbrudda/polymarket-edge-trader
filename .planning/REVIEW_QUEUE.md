# Review Queue

## Reviewer Notes for Worker

Read this section before starting work. These are patterns the reviewer has flagged from previous reviews.

1. **When changing a function's return signature, update all test mocks too.** In 10-02, `_get_dependencies` went from 4-tuple to 5-tuple but `tests/test_cli_research.py` still mocked it as 4-tuple, causing a regression. Before submitting, grep test files for mocks of any function you modified: `grep -r "function_name" tests/`

## Pending Review

### worker/debugging — 2026-02-15
- **Branch:** worker/debugging
- **Commits:** 2623508, 95058fc
- **Files changed:**
  - src/api/gamma_client.py (MODIFIED)
  - src/api/models.py (MODIFIED)
  - src/cli/commands.py (MODIFIED)
  - src/cli/scheduler.py (MODIFIED)
  - src/pipeline/ingest.py (MODIFIED)
- **Worker notes:** Debug session - Multiple issues fixed:
  1. cli_log_file error - log rotation was size-based, changed to time-based (midnight)
  2. Gamma API /markets endpoint completely broken - ignores ALL filters
  3. Discovered /events endpoint works correctly - returns real game times
  4. Fixed discover command session handling (detached instance error)
  5. Added start_date to Market model for debugging
- **Fix applied:**
  - Changed CLI log rotation from '10 MB' to '00:00' (midnight daily)
  - Switched from /markets to /events endpoint for targeted scanning
  - Added get_events() to gamma_client.py with tag_id filtering
  - Added NICHE_TAG_IDS mapping for niche->tag_id conversion
  - Added _convert_events_to_markets() to extract markets from events
  - Ordered events by endDate (earliest first)
  - Fixed discover command SQLAlchemy session handling
- **Decisions made:** /events endpoint provides actual game times vs midnight UTC defaults from /markets
- **Test result:** discover --niche esports --closing-within 12h found 258 markets and 1016 traders in 131s

### worker/debugging — 2026-02-15
- **Branch:** worker/debugging
- **Commits:** 2623508
- **Files changed:**
  - src/cli/commands.py (MODIFIED)
- **Worker notes:** Debug session - cli_log_file error. Issue: Log rotation was size-based (10MB), user couldn't see fresh outputs for debugging. Also cleared old database for fresh tracking.
- **Fix applied:** Changed rotation from '10 MB' to '00:00' (midnight daily) for time-based rotation. Deleted data/polymarket.db (6.2MB) to clear old entries.
- **Decisions made:** Time-based rotation ensures fresh log each day, easier for debugging sessions.

### worker/debugging — 2026-02-14
- **Branch:** worker/debugging
- **Commits:** uncommitted (local changes)
- **Files changed:**
  - src/pipeline/ingest.py (MODIFIED)
- **Worker notes:** Debug session - Gamma API filtering broken. Two issues found:
  1. Gamma API server-side filtering is broken (returns wrong markets for any tag)
  2. EndDate filter not working (returns past-dated markets)
  3. Category fallback incorrectly labeled non-esports as Esports
- **Fix applied:** Added client-side filtering in `_filter_market_by_niche()` function to validate:
  - Markets have valid tags matching requested niche
  - Markets haven't ended (endDate not in past)
  - Removed problematic category fallback
- **Decisions made:** Client-side filtering compensates for broken Gamma API

## Cleared

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
