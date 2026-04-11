---
phase: 9
slug: alert-system-pipeline-health
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-11
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | pyproject.toml (implicit) |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_health.py -x -q` |
| **Full suite command** | `.venv/bin/python -m pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_health.py -x -q`
- **After every plan wave:** Run `.venv/bin/python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | HLTH-01 | T-09-01 / osascript injection | Sanitize quotes before AppleScript interpolation | unit | `pytest tests/test_health.py::test_preflight_memory_fail -x` | No — Wave 0 | ⬜ pending |
| 09-01-02 | 01 | 1 | HLTH-01 | — | N/A | unit | `pytest tests/test_health.py::test_preflight_disk_fail -x` | No — Wave 0 | ⬜ pending |
| 09-01-03 | 01 | 1 | HLTH-01 | — | N/A | unit | `pytest tests/test_health.py::test_staleness_warn -x` | No — Wave 0 | ⬜ pending |
| 09-02-01 | 02 | 1 | HLTH-04 | T-09-02 / notification flood | health_log dedup prevents flood | unit | `pytest tests/test_health.py::test_send_alert_both_channels -x` | No — Wave 0 | ⬜ pending |
| 09-02-02 | 02 | 1 | HLTH-04 | — | N/A | unit | `pytest tests/test_health.py::test_send_alert_no_credentials -x` | No — Wave 0 | ⬜ pending |
| 09-03-01 | 03 | 2 | HLTH-02 | — | N/A | unit | `pytest tests/test_health.py::test_daily_summary -x` | No — Wave 0 | ⬜ pending |
| 09-03-02 | 03 | 2 | HLTH-03 | — | N/A | unit | `pytest tests/test_health.py::test_q5_diff -x` | No — Wave 0 | ⬜ pending |
| 09-03-03 | 03 | 2 | HLTH-03 | — | N/A | unit | `pytest tests/test_health.py::test_quiet_canary -x` | No — Wave 0 | ⬜ pending |
| 09-04-01 | 04 | 2 | HLTH-05 | — | N/A | unit | `pytest tests/test_health.py::test_preflight_fail_sends_alert -x` | No — Wave 0 | ⬜ pending |
| 09-04-02 | 04 | 2 | HLTH-06 | — | N/A | unit | `pytest tests/test_health.py::test_health_log_persisted -x` | No — Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_health.py` — stubs for HLTH-01 through HLTH-06 (10 tests)
- [ ] `src/polymarket_analytics/health/__init__.py` — package init
- [ ] `uv add psutil` — required before health check code can import psutil

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Telegram message actually delivered | HLTH-04 | Requires real bot token + network | Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env, run `polymarket health-check --tier cron --niche esports`, verify message arrives in Telegram |
| macOS notification visible on screen | HLTH-04 | Requires display + notification center | Run `polymarket health-check --tier cron --niche esports`, verify macOS notification banner appears |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
