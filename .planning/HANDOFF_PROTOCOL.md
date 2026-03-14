# Handoff Protocol: Multi-Model Collaboration

## Roles

- **Worker** (Model A): Executes plans, writes code. Works on feature branches.
- **Reviewer** (Model B): Reviews code quality, approves or requests fixes. Typically Opus 4.6.

## Rules

1. Worker NEVER pushes to `main`. Always works on a feature branch. This rule is enforced by a `pre-commit` hook that rejects commits made directly on `main` — see the Branch Protection section in AGENTS.md. A submission that bypasses this (e.g. via `--no-verify`) must be rejected and the Worker required to recreate the work on a proper branch.
2. Worker updates `REVIEW_QUEUE.md` after every work session.
3. Worker updates `STATE.md` to reflect current plan and status on every submission.
4. Reviewer checks `REVIEW_QUEUE.md` at session start.
5. **Reviewer updates `STATE.md` immediately on every merge — same session, non-negotiable.**
6. **Reviewer writes or verifies plan SUMMARY.md before closing out every approved plan.**
7. Reviewer marks entries as cleared (with commit hash) after approval.
8. If Worker modifies a file that was previously cleared, it MUST flag it for re-review.
9. Only Reviewer merges to `main`.

## Branch Convention

```
worker/<phase>-<slug>       # e.g. worker/21-market-entity-extraction
worker/<phase>-<slug>-fix   # if reworking after review feedback
```

## Work Session Flow

### Worker (Model A) Session

1. Switch to `main`, pull latest, then create your branch from it: `git checkout main && git pull && git checkout -b worker/<name>`. Never create a branch from an arbitrary HEAD.
2. Read the relevant PLAN.md — this is your spec.
3. Execute the plan, commit atomically per task.
4. Activate the virtual environment and run `pytest` — fix any failures before continuing.
5. **Update STATE.md:** set current phase, current plan number, status, last activity date. Must reflect actual current state, not phase-start state.
6. **Write `{phase-dir}/{phase-num}-{plan-num}-SUMMARY.md` for every plan before submission.** e.g. `21-01-SUMMARY.md`, `21-02-SUMMARY.md`. Required every time, not optional.
7. Before ending session, update `.planning/REVIEW_QUEUE.md`:
   - Add entry to `## Pending Review`
   - List every file created or modified
   - Note the commit range (first..last commit hash)
   - Flag any files from `## Cleared` that were modified → move to `## Re-Review`
   - Add any decisions or concerns to Worker Notes
   - Tick the pre-submit checklist honestly
8. Push the feature branch.

### Worker Pre-Submit Checklist

```
- [ ] Virtual environment active, all tests pass (pytest)
- [ ] No debug artifacts (no hardcoded values, no TODO: remove, no stray print() statements)
- [ ] STATE.md updated — current phase, plan number, last activity date
- [ ] Plan SUMMARY.md written (`{phase-num}-{plan-num}-SUMMARY.md` — required for every plan)
- [ ] No cosmetic changes outside task scope
```

Reviewer will reject any submission with unchecked boxes.

### Worker — Fixing Review Feedback

1. Mark your `## Re-Review` entry `Status: In Progress`.
2. Address every issue listed in `## Review Feedback`.
3. Update STATE.md to reflect the fix status.
4. Move entry back to `## Pending Review`, add a `Fixes:` line summarising what was addressed.
5. Clear the `## Review Feedback` entry — replace content with `Resolved — moved to Pending Review [date]`.
6. Push the fix branch.

### Reviewer (Model B) Session

1. Read `.planning/REVIEW_QUEUE.md` — if `## Pending Review` has items, review immediately.
2. For each entry in `## Pending Review`:
   - `git diff main..worker/<branch>` to see full diff.
   - Check pre-submit checklist — reject if any boxes unchecked.
   - Review code quality, correctness, test coverage, no debug artifacts.
   - **If approved:**
     1. Move entry to `## Cleared` with date and review notes.
     2. **Merge branch to `main`** (`git merge --no-ff worker/<branch>`).
     3. **Push `main` to origin immediately after merging.** Workers reset local main to `origin/main` before branching — an unpushed merge will be silently discarded, causing the merged code to disappear from the next worker's branch base.
     4. **Update STATE.md immediately** — phase, plan counts, last activity. Do this in the same session. Do not defer.
     5. **Commit STATE.md and REVIEW_QUEUE.md to main immediately.** Do not leave them as working-tree edits — uncommitted edits will be overwritten by the next worker's git operations.
     6. **Verify merge is complete:** `git log --oneline main..worker/<branch>` must return empty. If not, the merge didn't happen. Do it now.
     7. **Verify `{phase-num}-{plan-num}-SUMMARY.md` exists for this plan.** If not, write it before closing. If this was the last plan of the phase, update ROADMAP.md phase row to complete with date.
   - **If changes needed:** write actionable feedback to `## Review Feedback`, move entry to `## Re-Review`.
3. For each entry in `## Re-Review`:
   - Only diff the specific files flagged.
   - Same approval/rejection flow as above.
4. Entry must leave `## Pending Review` before session ends.

## STATE.md Update Protocol

STATE.md must always reflect reality. It is the Reviewer's responsibility to keep it current on merge. The Worker keeps it current on submission.

**On every Worker submission, STATE.md must show:**
- Current phase number and name
- Current plan number and status
- Last activity date

**On every Reviewer merge, STATE.md must additionally show:**
- Plan marked complete
- Phase marked complete if applicable
- Last activity updated to today

**STATE.md that is more than one plan behind reality is a bug. Treat it as one.**

## SUMMARY.md Protocol

Every plan must have a `{phase-num}-{plan-num}-SUMMARY.md` in its phase directory before the plan is considered closed.

**Worker writes it on every submission — not just the last plan of a phase.**
**Reviewer writes it if Worker missed it — before closing the session, not deferred.**

Contents (minimum):
- What was built
- Key decisions made during implementation
- Any deviations from the PLAN.md and why
- Test results
- Known issues or follow-up items

A plan with no SUMMARY.md is not complete, regardless of whether it is merged.

## File: .planning/REVIEW_QUEUE.md

```markdown
# Review Queue

## Pending Review

### [branch-name] — [date]
- **Plan:** 21-01
- **Branch:** worker/21-market-entity-extraction
- **Commits:** abc1234..def5678
- **Files changed:**
  - src/extraction/llm_extractor.py (NEW)
  - src/db/models.py (MODIFIED)
  - tests/extraction/test_llm_extractor.py (NEW)
- **Worker notes:** [decisions, concerns]
- **Checklist:**
  - [x] Tests pass (pytest)
  - [x] No debug artifacts
  - [x] STATE.md updated
  - [x] SUMMARY.md written (`{phase-num}-{plan-num}-SUMMARY.md`)

## Re-Review

### [branch-name] — [date]
- **Status:** Pending / In Progress
- **Previously cleared:** [date]
- **Files re-touched:** [list]
- **Reason:** [why cleared file was touched]

## Review Feedback

### [branch-name] — [date]
- **Reviewer:** Opus 4.6
- **Issues:**
  - src/extraction/llm_extractor.py:42 — extraction failures not logged
- **Action required:** Worker fixes, moves to Pending Review

## Cleared

### [branch-name] — [date cleared]
- **Plan:** 21-01
- **Cleared by:** Opus 4.6
- **Merge commit:** ghi9012
- **Notes:** Clean model + extractor, tests passing.
```

## Quick Reference

| Situation | Action |
|---|---|
| Worker finishes a plan | Write `{phase}-{plan}-SUMMARY.md`, update STATE.md, add to Pending Review, push branch |
| Reviewer approves | Merge, push origin, update STATE.md, verify SUMMARY.md exists, move to Cleared |
| Reviewer rejects | Write actionable feedback, move to Re-Review |
| Worker picks up feedback | Mark Re-Review Status: In Progress |
| Worker fixes feedback | Move to Pending Review with Fixes: note |
| Worker touches cleared file | Move affected files to Re-Review before pushing |
| STATE.md is stale | Whoever notices it — fix it immediately |
| Plan merged, no SUMMARY.md | Reviewer writes it before closing session |

## Code Standards

1. **No cosmetic reformatting outside scope.** If you modify a function, you may reformat that function. Do not touch the rest of the file.
2. **No debug hardcodes.** Hardcoded test values, bypass logic, and `TODO: remove` blocks must be removed before pushing. Run `git diff main..HEAD | grep -i "debug\|TODO\|hardcode\|temporary\|FIXME"` before submitting.
3. **Update tests when you change interfaces.** Rename a method → update all test mocks. `grep -r "old_function_name" tests/` after every interface change.
4. **Debug sessions must have summary files.** Any debug session resulting in code changes must produce a summary in `.planning/debug/` documenting trigger, evidence, root cause, fix, and files changed.
5. **Don't document unbuilt features.** Do not update README or user-facing docs for features not yet implemented.
6. **Keep debug output opt-in.** Debug dumps and verbose logging must be gated behind `POLYMARKET_DEBUG` env var or a `--debug` CLI flag. Never write debug artifacts unconditionally.
