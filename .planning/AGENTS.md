# Agent Contract: Worker ↔ Reviewer

## Roles

**Worker** — executes plans, writes code, works exclusively on feature branches.
**Reviewer** — reviews code, approves or rejects, is the only entity that merges to `main`.

---

## State Machine

```
Pending Review
  → [Reviewer approves]        → Cleared (Reviewer merges to main, updates STATE.md, writes SUMMARY.md if last plan in phase)
  → [Reviewer finds issues]    → Re-Review  +  Review Feedback written

Re-Review
  → [Worker picks up]          → Re-Review, Status: In Progress
  → [Worker fixes and submits] → Pending Review (fix notes added, feedback entry cleared)

Pending Review (re-submission)
  → [Reviewer approves]        → Cleared
  → [Reviewer finds new issues]→ Re-Review  +  Review Feedback written

Cleared file modified by Worker → Re-Review (flagged files only)
```

---

## Worker Obligations

1. **Branch from current main — pre-flight check first.** Before creating any branch:
   ```bash
   git log --oneline -1
   git status
   ```
   If working tree is dirty, stop and investigate. Never create a branch from a dirty state.

   Once clean: `git checkout main && git pull && git checkout -b worker/<name>`.

2. **Do not touch `ROADMAP.md`.** Reviewer-only.

3. **Before submitting:** pytest passes, no debug artifacts, no cosmetic changes outside scope.

4. **When submitting:** Write a full Pending Review entry — branch, commit range, files changed, decisions made, any concerns. Include this checklist, ticked honestly:
   ```
   - [ ] All tests pass (source .venv/bin/activate && pytest)
   - [ ] STATE.md updated (current phase, plan number, last activity date)
   - [ ] Plan SUMMARY.md written (`{phase-num}-{plan-num}-SUMMARY.md` — every plan, not just last)
   - [ ] No debug artifacts, no cosmetic changes outside scope
   ```

5. **SUMMARY.md must be written for every plan on submission** — not just the last plan of a phase. Write `{phase-dir}/{phase-num}-{plan-num}-SUMMARY.md` before pushing.

6. **STATE.md must reflect the current plan on every submission.** Not the phase start state — the actual current plan number, status, and last activity date. Stale STATE.md is grounds for rejection.

7. **When fixing feedback:** Address every issue in Review Feedback. Mark Re-Review entry `Status: In Progress` while working. On resubmit: move to Pending Review, add `Fixes:` note, clear the feedback entry.

8. **If a cleared file must be modified:** flag it immediately, move affected files to Re-Review before pushing.

9. **Before deleting any file:** confirm no other file depends on it. If uncertain, list it under `Files requiring relocation:` in your Pending Review submission. The Reviewer decides. Deleting without this check is grounds for rejection.

---

## Reviewer Obligations

1. **On session start:** check Pending Review — if items exist, review them immediately.

2. **After reviewing:** entry must leave Pending Review before the session ends (moved to Re-Review or Cleared).

3. **Feedback must be actionable:** file path, line number if relevant, what is wrong, what is needed. No vague comments.

4. **On re-review:** only diff the flagged files unless the worker added new files.

5. **On approval — do all of these before closing:**
   - Verify all checklist items ticked. Reject if any unchecked.
   - Move entry to Cleared with date and brief note.
   - **Merge worker branch to `main`** (`git merge --no-ff worker/<branch>`).
   - **Push `main` to origin immediately after merging.** Workers reset local main to `origin/main` before branching — if you don't push, the next worker's branch will be missing your merge.
   - **Update STATE.md immediately**, then **commit STATE.md and REVIEW_QUEUE.md to main**. Do not leave reviewer edits unstaged.
   - **VERIFY: `git log --oneline main..worker/<branch>` must return empty.** If not, the merge is incomplete. Finish it now.

6. **After the last plan of a phase is merged:**
   - Verify `{phase-dir}/{phase-num}-{plan-num}-SUMMARY.md` exists for every plan.
   - If missing, write it before closing the session.
   - Update ROADMAP.md phase status to complete with date.

---

## Blocking Rules

- Worker does not merge. Ever.
- Reviewer does not leave Pending Review items unreviewed at end of session.
- Reviewer does not merge without updating STATE.md in the same session.
- Every plan gets a SUMMARY.md — Worker writes it, Reviewer writes it if Worker missed it.
- Neither party edits the other's active section in REVIEW_QUEUE.md except as the protocol specifies.

---

## Branch Protection (Enforced by Hook)

The repo has a `pre-commit` hook that rejects any commit made directly on `main`. If a Worker somehow bypasses it, the Reviewer must reject the submission and require the Worker to recreate the work on a proper `worker/*` branch.

To install the hook:

```sh
cat > .git/hooks/pre-commit << 'EOF'
branch=$(git symbolic-ref HEAD 2>/dev/null)
if [ "$branch" = "refs/heads/main" ]; then
  echo "ERROR: Direct commits to main are not allowed. Use a worker/* branch."
  exit 1
fi
EOF
chmod +x .git/hooks/pre-commit
```
