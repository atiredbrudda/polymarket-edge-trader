---
phase: 23
slug: contextual-analyze-command
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-14
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/test_analyze.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_analyze.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 0 | stubs | unit | `uv run pytest tests/test_analyze.py -x -q 2>&1 \| head -20` | ❌ W0 | ⬜ pending |
| 23-01-02 | 01 | 1 | ANALYZE-06 crawler cursor | unit | `uv run pytest tests/test_analyze.py::test_crawler_cursor -x -q` | ❌ W0 | ⬜ pending |
| 23-01-03 | 01 | 1 | ANALYZE-01..05 query layer | unit | `uv run pytest tests/test_analyze.py -x -q` | ❌ W0 | ⬜ pending |
| 23-02-01 | 02 | 2 | ANALYZE-07 stub | integration | `uv run pytest tests/test_analyze.py -x -q 2>&1 \| tail -5` | ❌ W0 | ⬜ pending |
| 23-02-02 | 02 | 2 | ANALYZE-07 CLI command | integration | `uv run pytest tests/test_analyze.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_analyze.py` — stubs for all tasks above
- [ ] Fixtures: in-memory DB with seed MarketEntity, Trader, Position rows

*Existing infrastructure (conftest.py, session_factory fixture) covers DB setup.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Crawler pause/resume across process kill | crawler | Process kill can't be unit tested | Run `polymarket analyze --crawl`, kill mid-run, restart, verify it resumes from cursor not start |
| Terminal output readability | CLI UX | Visual/formatting | Run batch mode with 3+ traders, verify output matches spec |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
