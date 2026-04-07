# Handoff Protocol: Multi-Model Collaboration

## Roles

- **Worker** (GSD executor): Executes plans, writes code. Works on feature branches only.
- **Reviewer** (main Claude conversation): Reviews code quality, approves or flags. Coordinates
  merge with the user. Updates STATE.md and ROADMAP.md after merge.

The user is the merge authority — they run `git merge` when the Reviewer says approved.

---

## Rules

1. Worker NEVER pushes to `main`. Always works on a feature branch. See branch protection hook
   in `AGENTS.md`. A submission that bypasses this must be rejected.
2. Worker updates `REVIEW_QUEUE.md` after every work session.
3. Worker writes `SUMMARY.md` for every plan before submission.
4. Reviewer checks `REVIEW_QUEUE.md` at session start.
5. **Reviewer updates `STATE.md` immediately on every merge — same session, non-negotiable.**
6. Reviewer marks entries as Cleared (with date) after approval.
7. If Worker modifies a file that was previously cleared, it MUST flag it for re-review.
8. Only the user merges to `main`, on Reviewer say-so.
9. Worker does NOT touch `STATE.md` or `ROADMAP.md`.
10. **Never leave real work in a git stash.** Stashes are invisible between sessions and will be
    lost. Any in-progress fix — even partial — must be committed to a named branch immediately.
    A draft commit on a branch is always preferable to a stash. Lost stash = lost work.

---

## Branch Convention

```
worker/<phase>-<slug>           # e.g. worker/07-flat-position-tracking
worker/<phase>-<slug>-fix       # if reworking after review feedback
```

GSD executor may use `gsd/phase-<NN>-<slug>` — both are valid. The invariant is: nothing
lands on `main` without Reviewer approval and user merge action.

---

## Work Session Flow

### Worker Session

1. Pre-flight check:
   ```bash
   git log --oneline -1
   git status
   ```
   If dirty, stop. Never branch from dirty state.

2. Create branch: `git checkout main && git pull && git checkout -b worker/<phase>-<slug>`

3. Read the relevant PLAN.md at `.planning/phases/{phase-dir}/{phase-num}-{plan-num}-PLAN.md` — this is your spec.

4. Execute the plan, commit atomically per task.

5. Run full test + lint suite:
   ```bash
   source .venv/bin/activate
   pytest
   ruff check src/ tests/
   ```
   Fix all failures before continuing.

6. Write SUMMARY.md at `.planning/phases/{phase-dir}/{phase-num}-{plan-num}-SUMMARY.md`.
   Required every submission, not optional.

7. Before ending session, update `.planning/REVIEW_QUEUE.md`:
   - Add entry to `## Pending Review`
   - List every file created or modified
   - Note the commit range (first..last)
   - Flag any previously Cleared files that were re-touched → move to Re-Review
   - Tick the pre-submit checklist honestly
   - Add any decisions or concerns under Worker Notes

8. Push the feature branch.

### Worker Pre-Submit Checklist

```
- [ ] All tests pass (source .venv/bin/activate && pytest)
- [ ] Linter clean (ruff check src/ tests/)
- [ ] No debug artifacts (no hardcoded values, no TODO: remove, no stray print() statements)
- [ ] STATE.md NOT touched (reviewer-only)
- [ ] SUMMARY.md written (.planning/phases/XX-name/XX-NN-SUMMARY.md — required every plan)
- [ ] No cosmetic changes outside task scope
```

Reviewer will reject any submission with unchecked boxes.

### Worker — Fixing Review Feedback

1. Mark the Flagged entry `Status: In Progress`.
2. Address every issue listed in the Flagged entry.
3. Move entry back to `## Pending Review`, add a `Fixes:` line summarising what was addressed.
4. Clear the Flagged feedback entry — replace content with `Resolved — moved to Pending Review [date]`.
5. Push the fix branch (same branch, no new branch unless scope changed significantly).

---

### Reviewer Session

1. Read `.planning/REVIEW_QUEUE.md` — if `## Pending Review` has items, review immediately.

2. For each entry in `## Pending Review`:
   - `git diff main..worker/<branch>` to see full diff.
   - Check pre-submit checklist — reject if any boxes unchecked.
   - Run `.planning/REVIEW_PROTOCOL.md` checklist: pipeline contracts, schema/data integrity,
     The Graph specifics, terminal output standards, general quality.
   - **If approved:**
     1. Move entry to `## Cleared` with date and review notes.
     2. Tell the user: **"Approved — ready to merge `worker/<branch>` → `main`."**
     3. After user confirms merge: update `STATE.md` — phase, plan, last activity.
     4. Commit `STATE.md` and `REVIEW_QUEUE.md` to main. Do not leave them as working-tree edits.
     5. **Verify merge is complete:** `git log --oneline main..worker/<branch>` must return empty.
     6. **Verify SUMMARY.md exists** for this plan. If not, write it before closing.
     7. If last plan of phase: update `ROADMAP.md` phase row to complete with date.
   - **If changes needed:** write actionable feedback, move entry to `## Flagged`.

3. For each entry in `## Re-Review`:
   - Only diff the specific files flagged.
   - Same approval/rejection flow as above.

4. Entry must leave `## Pending Review` before session ends.

---

## STATE.md Update Protocol

STATE.md is Reviewer-maintained. Worker does not touch it.

**On every Reviewer merge, STATE.md must show:**
- Current phase number and name
- Plan marked complete (or phase marked complete if applicable)
- Last activity updated to today

**STATE.md that is more than one plan behind reality is a bug. Treat it as one.**

---

## SUMMARY.md Protocol

Every plan must have a SUMMARY.md before it is considered closed.
Path: `.planning/phases/{phase-dir}/{phase-num}-{plan-num}-SUMMARY.md`
e.g. `.planning/phases/07-flat-position-tracking/07-01-SUMMARY.md`

**Worker writes it on every submission — not just the last plan of a phase.**
**Reviewer writes it if Worker missed it — before closing the session, not deferred.**

Contents (minimum):
- What was built
- Key decisions made during implementation
- Any deviations from the PLAN.md and why
- Test results (pytest output summary)
- Known issues or follow-up items

A plan with no SUMMARY.md is not complete, regardless of whether it is merged.

---

## REVIEW_QUEUE.md Entry Format

```markdown
### Phase XX Plan NN - short description — [date]
- **Branch:** worker/XX-description
- **Plan:** .planning/phases/XX-name/XX-NN-PLAN.md
- **Summary:** .planning/phases/XX-name/XX-NN-SUMMARY.md
- **Commits:** abc1234..def5678
- **Files changed:**
  - src/polymarket_analytics/module/file.py (NEW|MODIFIED)
  - tests/test_file.py (NEW|MODIFIED)
- **Worker notes:** [decisions, concerns]
- **Checklist:**
  - [x] Tests pass (pytest)
  - [x] Linter clean (ruff check src/ tests/)
  - [x] No debug artifacts
  - [x] STATE.md NOT touched
  - [x] SUMMARY.md written
```

---

## Quick Reference

| Situation | Action |
|---|---|
| Worker finishes a plan | Write SUMMARY.md, add to Pending Review, push branch |
| Reviewer approves | Tell user to merge, then update STATE.md, verify SUMMARY.md, move to Cleared |
| Reviewer rejects | Write actionable feedback, move to Flagged |
| Worker picks up feedback | Mark Flagged Status: In Progress |
| Worker fixes feedback | Move to Pending Review with Fixes: note |
| Worker touches cleared file | Move affected files to Re-Review before pushing |
| STATE.md is stale | Reviewer fixes it immediately |
| Plan merged, no SUMMARY.md | Reviewer writes it before closing session |
| ROADMAP.md last plan of phase | Reviewer updates phase status to complete with date |

---

## Code Standards

These are in addition to the pipeline-specific rules in `REVIEW_PROTOCOL.md`.

1. **No cosmetic reformatting outside scope.** If you modify a function, you may reformat that
   function. Do not touch the rest of the file.

2. **No debug hardcodes.** Hardcoded test values, bypass logic, and `TODO: remove` blocks must
   be removed before pushing:
   ```bash
   git diff main..HEAD | grep -iE "debug|TODO|hardcode|temporary|FIXME"
   ```

3. **Update tests when you change interfaces.** Rename a method → update all test mocks.
   ```bash
   grep -r "old_function_name" tests/
   ```

4. **Don't document unbuilt features.** Do not update README.md or GUIDE.md for features not
   yet implemented.

5. **Keep debug output opt-in.** Debug dumps and verbose logging must be gated behind
   `POLYMARKET_DEBUG` env var or a `--debug` CLI flag. Never write debug artifacts
   unconditionally.

6. **Upsert pattern.** Use `ON CONFLICT DO UPDATE` — not `INSERT OR REPLACE` (resets
   `created_at`). Pure skip-if-exists uses `INSERT OR IGNORE`.

7. **NUMERIC affinity.** Price and size columns use raw SQL `CREATE TABLE` with explicit
   NUMERIC affinity — not sqlite-utils table.create() type inference.

8. **Null coercion.** `str(x or "")` not `str(x)` — `str(None)` produces `"None"` (truthy string).

9. **Rich UX contract.** Every command prints a header immediately on start. Every loop over
   N items has a Rich progress bar. Any operation >1s without a loop has a spinner. Every
   command prints a summary on completion with counts — never exits silently.
