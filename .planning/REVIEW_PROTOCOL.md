# Review Protocol

Two roles: **Worker** (GSD executor) and **Reviewer** (main Claude conversation).

Worker plans, executes, and verifies. Reviewer checks execution against GUIDE.md
and the codebase before anything gets committed to main.

---

## Worker Handoff Checklist

Before signalling ready for review, the worker must:

1. All plan tasks complete
2. Tests pass: `pytest` exits 0
3. SUMMARY.md written with deviations documented
4. Work is on a worker branch - nothing pushed to main
5. No debug hardcodes, no TODO comments left in shipped code
6. STATE.md and ROADMAP.md untouched - reviewer-only
7. **Add entry to `.planning/REVIEW_QUEUE.md` under Pending Review**

The worker must NOT commit to main or update STATE.md. That happens after review.

---

## How to Invoke Review

User tells the reviewer (main conversation):

> "Review the queue" or "Review phase X plan Y"

Reviewer will:
1. Check `.planning/REVIEW_QUEUE.md` for Pending entries
2. Read the PLAN.md to understand intent
3. Read the SUMMARY.md for what was built and any deviations
4. Read every changed file on the branch
5. Run the checklist below
6. Return: **Approved** (with notes) or **Flagged** (with specific issues to fix)
7. Move the entry in REVIEW_QUEUE.md to Cleared or Flagged accordingly

---

## Review Checklist

### Pipeline contracts (GUIDE.md hard rules)
- [ ] Every command asserts its dependencies exist at startup - no silent 0-results
- [ ] `build-positions` checks `market_entities.game IS NOT NULL` before running
- [ ] Entity extraction filtered to `WHERE markets.niche_slug = :niche` - never global
- [ ] `score` JOINs through `markets` on `niche_slug` - not scoring all niches together
- [ ] No trades written before token_catalog exists for that niche
- [ ] Zero synthetic market_ids: no `graph_%` or non-`0x%` values in `trades.market_id`

### Schema / data integrity
- [ ] Price and size columns use NUMERIC affinity (raw SQL), not `float` via sqlite-utils
- [ ] Upsert pattern: `ON CONFLICT DO UPDATE` - not `INSERT OR REPLACE` (would reset `created_at`)
- [ ] Pure skip-if-exists: `INSERT OR IGNORE` - not ON CONFLICT UPDATE
- [ ] Null coercion: `str(x or "")` not `str(x)` - `str(None)` produces `"None"` (truthy string)
- [ ] No unbounded string columns for API fields that could be large JSON blobs - use TEXT

### The Graph specific
- [ ] Asset ID selected as non-zero: not by maker/taker role (the 48% bug)
- [ ] Prices > 1.0 converted: `price = 1 / price`

### Terminal output (GUIDE.md standards)
- [ ] Command prints header line immediately on start
- [ ] Every loop over N items has a Rich progress bar (description, bar, M/N, elapsed)
- [ ] Any operation > 1s without a loop has a spinner
- [ ] Command prints summary on completion with counts - never exits silently
- [ ] Errors print inline in red without halting the progress bar

### General
- [ ] No cosmetic reformatting of existing code
- [ ] No new abstractions for single-use operations
- [ ] Function signatures unchanged in existing code (unless the plan required it)
- [ ] If function signatures changed: mocks/fixtures updated to match

---

## After Approval

Reviewer **immediately** merges the worker branch to main and updates planning artifacts. No user action required.

Reviewer:
1. Moves queue entry from Pending → Cleared (with reviewer notes)
2. Merges worker branch to main: `git checkout main && git merge --no-ff worker/XX-...`
3. **Updates STATE.md** — mandatory after every clear, before committing:
   - Pending Todos: strike through completed item, update count line
   - Handoff notes: add MERGED entry with what changed and test count
   - "Next" line: reflect new remaining todos
   - Last updated: timestamp + one-line summary of what changed
4. Updates ROADMAP.md phase status if last plan of a phase
5. If clearing a todo (not a phase plan): move the todo file from `todos/pending/` → `todos/done/`
6. Commits STATE.md + REVIEW_QUEUE.md + any moved todo files on a worker branch, merges to main

**Why --no-verify on merge commits:** The pre-commit hook blocks direct commits to main to protect against accidental code changes. Merge commits are explicitly authorized reviewer actions — bypassing the hook for merges is correct and intentional.

---

## After Flagging

Reviewer lists specific issues. Worker fixes on the same branch and signals ready
again. No new branch needed unless the scope changed significantly.
