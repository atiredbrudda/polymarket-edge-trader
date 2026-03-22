---
phase: 25
slug: lift-based-scoring-v2
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/test_lift_scoring.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_lift_scoring.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 0 | stubs | unit | `uv run pytest tests/test_lift_scoring.py -x -q 2>&1 \| head -20` | ❌ W0 | ⬜ pending |
| 25-01-02 | 01 | 1 | LIFT-01 metrics | unit | `uv run pytest tests/test_lift_scoring.py::test_clv -x -q` | ❌ W0 | ⬜ pending |
| 25-01-03 | 01 | 1 | LIFT-01 scoring | unit | `uv run pytest tests/test_lift_scoring.py::test_composite -x -q` | ❌ W0 | ⬜ pending |
| 25-01-04 | 01 | 1 | LIFT-01 pipeline | integration | `uv run pytest tests/test_lift_scoring.py -x -q` | ❌ W0 | ⬜ pending |
| 25-02-01 | 02 | 2 | LIFT-02 CLI | integration | `uv run pytest tests/test_lift_scoring.py -x -q` | ❌ W0 | ⬜ pending |
| 25-02-02 | 02 | 2 | LIFT-03 signals | integration | `uv run pytest tests/test_lift_scoring.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_lift_scoring.py` — stubs for LIFT-01, LIFT-02, LIFT-03
- [ ] Shared fixtures for positions, trades, market_avg_entries

*Existing infrastructure (pytest, conftest.py) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Q5 trader display in CLI | LIFT-02 | Visual output formatting | Run `polymarket analyze` and verify table renders correctly |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
