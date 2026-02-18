# Worker Instructions

You are the Worker model in a multi-model collaboration. A Reviewer (separate model) will review every line of your diff before it reaches main. Sloppy work gets rejected and wastes cycles for everyone.

## Absolute Rules

These are non-negotiable. Violating ANY of these causes your entire branch to be rejected.

### 1. ONLY change lines required by your task

This is the most violated rule. Do NOT:
- Reformat/rewrap lines you didn't functionally change
- Run auto-formatters on files
- "Clean up" surrounding code
- Change whitespace in unrelated code

If your task adds 1 field to a model, your diff should be ~3 lines for that file, NOT 150 lines of reformatting. The reviewer WILL revert cosmetic changes and reject the branch.

### 2. Update ALL tests when you change interfaces

If you change column names, function signatures, return types, or behavior — you MUST update every test file that references the old interface. Search with: `grep -r "function_name" tests/`

This is the #1 source of regressions. The converter was rewritten from camelCase to snake_case but test_converters.py wasn't updated — 13 test failures. Don't repeat this.

### 3. Run validation before submitting

```bash
bash scripts/worker_validate.sh
```

This checks for regressions, reformatting, and debug artifacts. If it fails, fix the issues before pushing.

### 4. Never push to main

Always use a `worker/` feature branch.

### 5. No duplicate code blocks

If you're copy-pasting the same logic into multiple methods, extract a helper function.

## Workflow

1. Read your task spec (PLAN.md or WORKER_TASK_*.md)
2. Read `.planning/HANDOFF_PROTOCOL.md` for full protocol details
3. Work on a `worker/` feature branch
4. Run `bash scripts/worker_validate.sh`
5. Update `.planning/REVIEW_QUEUE.md` with your changes
6. Push the feature branch

## Testing

```bash
source .venv/bin/activate
pytest tests/ -q --tb=short
# Baseline on main: 9 pre-existing failures
# Your branch must NOT add new failures
```
