---
phase: 22
slug: org-team-mapping
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-14
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | none — run from project root |
| **Quick run command** | `python -m pytest tests/org_mapping/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q --ignore=tests/datasources` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/org_mapping/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/org_mapping/ tests/extraction/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 0 | MAP-01..06 | unit stubs | `python -m pytest tests/org_mapping/ -x -q` | ❌ W0 | ⬜ pending |
| 22-01-02 | 01 | 1 | MAP-01 | unit | `python -m pytest tests/org_mapping/test_queries.py::test_team_stats_basic -x` | ❌ W0 | ⬜ pending |
| 22-01-03 | 01 | 1 | MAP-02 | unit | `python -m pytest tests/org_mapping/test_queries.py::test_direction_mapping -x` | ❌ W0 | ⬜ pending |
| 22-01-04 | 01 | 1 | MAP-03 | unit | `python -m pytest tests/org_mapping/test_queries.py::test_excludes_unresolved -x` | ❌ W0 | ⬜ pending |
| 22-01-05 | 01 | 1 | MAP-04 | unit | `python -m pytest tests/org_mapping/test_queries.py::test_excludes_prop_markets -x` | ❌ W0 | ⬜ pending |
| 22-01-06 | 01 | 1 | MAP-05 | unit | `python -m pytest tests/org_mapping/test_queries.py::test_upsert_idempotent -x` | ❌ W0 | ⬜ pending |
| 22-01-07 | 01 | 1 | MAP-06 | unit | `python -m pytest tests/org_mapping/test_queries.py::test_canonical_team_names -x` | ❌ W0 | ⬜ pending |
| 22-02-01 | 02 | 2 | MAP-07 | integration | `python -m pytest tests/org_mapping/test_cli.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/org_mapping/__init__.py` — package marker
- [ ] `src/org_mapping/queries.py` — stub (function signatures only)
- [ ] `src/org_mapping/models.py` — stub (TraderTeamStats model)
- [ ] `tests/org_mapping/__init__.py` — package marker
- [ ] `tests/org_mapping/test_queries.py` — 6 unit test stubs (MAP-01 through MAP-06)
- [ ] `tests/org_mapping/test_cli.py` — 1 CLI test stub (MAP-07)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `polymarket team-stats <address>` output readability | MAP-07 | CLI output format | Run command on real trader, inspect table formatting |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
