# Handoff Protocol: Multi-Model Collaboration

## Roles

- **Worker** (Model A): Executes plans, writes code. Typically an open source model.
- **Reviewer** (Model B): Reviews code quality, approves or requests fixes. Typically Opus 4.6.

## Rules

1. Worker NEVER pushes to `main`. Always works on a feature branch.
2. Worker updates `REVIEW_QUEUE.md` after every work session.
3. Reviewer checks `REVIEW_QUEUE.md` at session start.
4. Reviewer marks entries as cleared (with commit hash) after approval.
5. If Worker modifies a file that was previously cleared, it MUST flag it for re-review.
6. Only Reviewer merges to `main`.

## Branch Convention

```
worker/<phase>-<plan>       # e.g. worker/10-01
worker/<phase>-<plan>-fix   # if reworking after review feedback
```

## Work Session Flow

### Worker (Model A) Session

1. Pull latest `main`, create or checkout feature branch
2. Read the relevant PLAN.md — this is your spec
3. Execute the plan, commit atomically per task
4. Before ending session, update `REVIEW_QUEUE.md`:
   - Add entry to `## Pending Review`
   - List every file created or modified
   - Note the commit range (first..last commit hash)
   - Flag any files from `## Cleared` that were modified → move to `## Re-Review`
   - Add any decisions or concerns to `## Worker Notes`
5. Push the feature branch

### Reviewer (Model B) Session

1. Read `REVIEW_QUEUE.md`
2. For each entry in `## Pending Review`:
   - `git diff main..worker/<branch>` to see full diff
   - Review code quality, correctness, test coverage
   - If approved: move entry to `## Cleared` with review commit hash
   - If changes needed: add feedback to `## Review Feedback`, worker addresses next session
3. For each entry in `## Re-Review`:
   - Only diff the specific files flagged, against the cleared commit
   - If approved: move back to `## Cleared` with updated commit hash
   - If changes needed: add to `## Review Feedback`
4. Merge approved branches to `main`
5. Update STATE.md with progress

## File: .planning/REVIEW_QUEUE.md

This is the shared ledger. Both models read and write it. Structure:

```markdown
# Review Queue

## Pending Review

### [branch-name] — [date]
- **Plan:** 10-01 (Targeted Market Scanning - Filter Engine)
- **Branch:** worker/10-01
- **Commits:** abc1234..def5678
- **Files changed:**
  - src/scanning/filters.py (NEW)
  - src/scanning/time_filter.py (NEW)
  - tests/test_filters.py (NEW)
  - src/pipeline/runner.py (MODIFIED)
- **Worker notes:** Chose to implement time filter as a separate class rather than
  inline in the scanner. Tests cover edge cases for timezone handling.
- **Decisions made:** [any architectural choices the worker made autonomously]

## Re-Review

### [branch-name] — [date]
- **Previously cleared:** [date of clearance]
- **Cleared commit:** abc1234
- **Files re-touched:**
  - src/pipeline/runner.py — added new filter integration
- **Reason:** Needed to modify cleared code to integrate new filter from plan 10-02
- **Worker notes:** Minimal change, only added 2 lines to the import section and
  1 function call in run_scan().

## Review Feedback

### [branch-name] — [date]
- **Reviewer:** Opus 4.6
- **Status:** Changes requested
- **Issues:**
  - src/scanning/filters.py:45 — SQL injection risk in raw query
  - tests/test_filters.py — missing edge case for empty market list
- **Action required:** Worker fixes issues, moves entry back to Pending Review

## Cleared

### [branch-name] — [date cleared]
- **Plan:** 10-01
- **Cleared by:** Opus 4.6
- **Review commit:** ghi9012
- **Files in scope:**
  - src/scanning/filters.py
  - src/scanning/time_filter.py
  - tests/test_filters.py
  - src/pipeline/runner.py
- **Notes:** Clean implementation, good test coverage.
```

## Detecting Re-Review Needs

When Worker modifies any file, check it against the `## Cleared` section:

```bash
# Get list of cleared files
grep "^  - " .planning/REVIEW_QUEUE.md | grep -A999 "## Cleared" | sed 's/^  - //' | cut -d' ' -f1

# Compare with files you just changed
git diff --name-only HEAD~N
```

If overlap exists → entry moves from Cleared to Re-Review with the specific files flagged.

## Worker Pre-Submit Checklist

Before updating REVIEW_QUEUE.md and pushing, verify:

1. **All plan tests pass:** `pytest tests/test_<new_file>.py -v`
2. **No regressions in related tests:** If you modified a function's signature or return value, grep test files for mocks of that function and update them: `grep -r "function_name" tests/`
3. **Full suite spot-check:** `pytest --tb=line -q` — compare failure count to what's on main. If you introduced new failures, fix them before submitting.

## Worker Code Standards

These rules come from patterns flagged during review. Violating them will result in changes-requested feedback.

### 1. No cosmetic reformatting outside your scope

Do NOT run auto-formatters on files you didn't functionally change. Line-wrapping, re-indenting, or reflowing code that isn't part of your task adds noise to diffs, pollutes git blame, and makes review harder. If you modify a function, you may reformat *that function*. Do not touch the rest of the file.

**Bad:** Changing 120 lines of `db/models.py` line wrapping when you only added 1 field.
**Good:** Adding the field and leaving everything else alone.

### 2. Never leave debug hardcodes in submitted code

Hardcoded test values, `TODO: remove after debugging` blocks, and bypass logic MUST be removed before pushing to the review queue. If `ingest_active_markets()` only processes 1 hardcoded market, that's not a fix — it's broken production code.

Before submitting, search your own changes:
```bash
git diff main..HEAD | grep -i "debug\|TODO\|hardcode\|temporary\|FIXME"
```

### 3. Update tests when you change interfaces

If you rename a method (e.g., `get_markets` → `get_events`), change a function signature, or alter return types, you MUST update all test mocks that reference the old interface. This is the #1 source of regressions found in review.

```bash
# After changing any function, check for test mocks
grep -r "old_function_name" tests/
```

### 4. Debug sessions MUST have summary files

Every debug session that results in code changes MUST produce a summary file in `.planning/debug/`. The file must document:
- **Trigger:** What symptom started the investigation
- **Evidence:** What you checked and what you found (with timestamps)
- **Root cause:** The actual underlying problem
- **Fix:** What you changed and why
- **Files changed:** List of modified files

This is non-negotiable. The summary is how future sessions understand *why* code looks the way it does. If the biggest change in your branch has no debug summary, the review will be sent back.

Use the existing files in `.planning/debug/` as a template.

### 5. Don't document unbuilt features

Do not update README.md or user-facing docs to describe features that haven't been implemented yet. Docs ship with code, not before it.

### 6. Keep debug/diagnostic output opt-in

Debug JSON dumps, verbose logging to files, and diagnostic outputs should be gated behind an environment variable (`POLYMARKET_DEBUG`) or a `--debug`/`--verbose` CLI flag. Do not write debug artifacts unconditionally on every run.

## Quick Reference

| Situation | Action |
|-----------|--------|
| Worker finishes a plan | Add to Pending Review, push branch |
| Reviewer approves | Move to Cleared, merge to main |
| Reviewer rejects | Add to Review Feedback with specifics |
| Worker fixes feedback | Move from Feedback back to Pending Review |
| Worker touches cleared file | Move affected files to Re-Review |
| Worker gets stuck | Add to Worker Notes, reviewer advises next session |
| Both models idle | Check Pending Review — if empty, next plan is ready |
