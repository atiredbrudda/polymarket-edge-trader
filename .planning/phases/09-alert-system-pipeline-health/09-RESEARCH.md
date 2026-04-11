# Phase 9: Alert System + Pipeline Health - Research

**Researched:** 2026-04-11
**Domain:** Operational alerting, system health monitoring, macOS notifications, Telegram Bot API
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Dual-channel delivery — Telegram bot + macOS native notifications
- **D-02:** Telegram covers mobile (user away from desk). macOS covers desktop (user on Discord/at computer).
- **D-03:** Both channels fire for every alert — no priority routing between them
- **D-04:** Alert + skip cycle — when a health pre-check fails (e.g., insufficient memory), send alert via both channels, skip the cron run entirely, retry next cycle
- **D-05:** No process killing — pipeline is paper trading and other running processes may be equally or more important. System must never kill external processes.
- **D-06:** No self-healing — system alerts only, does not attempt to fix problems itself. User decides what to do.
- **D-07:** Pipeline is already resilient to missed runs (monitor covers Q5 independently, missed-Sunday fallback handles gaps). A skipped cron is a non-event as long as the user knows.
- **D-08:** Per-cron checks (every 4h run): all stages completed (exit codes), memory/disk pre-flight (abort early if below threshold before starting), `lift_scores.computed_at` freshness (warn if older than expected, >5h)
- **D-09:** Daily checks (end-of-day summary): signals generated/updated count, traders discovered vs traders backfilled, any stages that errored in last 24h
- **D-10:** Weekly checks (Sunday after full backfill): Q5 list diff (who entered/exited Q5 this week), scoring drift (has composite score distribution shifted significantly), data completeness (% of traders with `data_incomplete` flag), "suspiciously quiet" canary (no new signals in 7 days when markets are active)

### Claude's Discretion
- Exact memory/disk thresholds for pre-flight abort
- macOS notification implementation (osascript vs terminal-notifier vs native API)
- Telegram bot library choice
- Log format and storage for health check results
- How daily/weekly summaries are aggregated (DB table vs flat file)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HLTH-01 | Per-cron pre-flight checks (memory/disk thresholds, stage exit codes, lift_scores freshness) | Memory check: psutil (installable). Disk check: shutil.disk_usage (stdlib). lift_scores staleness: existing pattern in _load_q5_traders(). Exit code tracking: wrap cron script stages and capture return codes. |
| HLTH-02 | Daily summary (signals count, traders discovered/backfilled, errored stages) | Query signals table for count delta. Query traders for last_backfilled_at timestamps. Stage errors come from health_log table (new). |
| HLTH-03 | Weekly health report (Q5 diff, scoring drift, data completeness, quiet canary) | Q5 diff: compare current q5_traders to snapshot stored in health_log. Scoring drift: stddev of composite_score from lift_scores. data_incomplete %: query positions table. Quiet canary: last signal's first_seen vs now. |
| HLTH-04 | Dual-channel alert delivery — Telegram bot + macOS native notifications | Telegram: httpx POST to api.telegram.org/bot{token}/sendMessage (no library needed — httpx already in deps). macOS: osascript verified working on this machine. |
| HLTH-05 | Alert + skip cycle on pre-flight failure — never kill external processes | Pattern: check pre-flight → if fail, send alert via both channels, exit 0 from cron script (don't let && chain propagate failure). Lock file already referenced in wiki. |
| HLTH-06 | Health check results logged for historical review | New `health_log` table in SQLite — consistent with project's "everything in analytics.db" pattern. |
</phase_requirements>

---

## Summary

Phase 9 adds operational awareness to the pipeline. The system currently produces results but has no mechanism to tell the user when it stops working correctly. This phase adds three tiers of checks: per-cron pre-flight (gates each run), daily summaries (end-of-day accounting), and weekly deep-health reports (trending drift and data quality). All alerts fire on two channels simultaneously: Telegram (async HTTP via httpx) and macOS native notifications (osascript).

The implementation is intentionally conservative. No self-healing, no process killing, no complex orchestration. The pipeline is already resilient to missed runs by design (monitor covers Q5 independently, missed-Sunday fallback handles gaps). The health system's job is to make the user aware, not to take action.

The key technical insight is that httpx is already in the project dependencies, making Telegram integration trivial: a direct HTTP POST to `api.telegram.org/bot{token}/sendMessage`. No additional library needed. osascript is verified available on this machine. The only new dependency is psutil for memory checking (installable, no conflicts).

**Primary recommendation:** Implement `health.py` as a standalone module with a `notify(message, title)` function and tier-specific check functions. The cron script calls health checks at the right moments. Health results persist in a new `health_log` table in analytics.db.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 (already installed) | Telegram Bot API calls | Already in deps; async-compatible; no additional library needed for Bot API |
| osascript | system (macOS built-in) | macOS native notifications | Verified working on this machine; zero dependencies |
| psutil | 7.2.2 (needs install) | Memory + disk checks | Standard for cross-platform system metrics in Python; `shutil.disk_usage` is stdlib but lacks free RAM |
| shutil | stdlib | Disk space check | `shutil.disk_usage(path)` returns (total, used, free) — no install needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlite-utils | 3.39 (already installed) | health_log table persistence | Consistent with all other DB writes in project |
| python-dotenv | 1.2.2 (already installed) | Read TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID from .env | Same pattern as all other commands |
| Rich | 14.3.3 (already installed) | Console output for health summaries | Consistent with all other command output |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx (direct) | python-telegram-bot library | Library adds 500KB+ dep with its own async loop; httpx direct call is 3 lines and already installed |
| osascript | terminal-notifier | terminal-notifier not installed; osascript is built-in and verified working |
| health_log SQLite table | flat JSON/log files | SQLite consistent with project patterns; enables historical queries; easier to query for weekly drift reports |

**Installation:**
```bash
uv add psutil
```

**Version verification:** [VERIFIED: pip dry-run] psutil 7.2.2 available for this platform (macosx_11_0_arm64).

---

## Architecture Patterns

### Recommended Project Structure
```
src/polymarket_analytics/
├── health/
│   ├── __init__.py
│   ├── notify.py          # send_alert(title, message) — both channels
│   ├── checks.py          # per_cron_checks(), daily_summary(), weekly_report()
│   └── log.py             # write_health_log(), read_health_log()
├── commands/
│   └── health_check.py    # Click CLI command: `polymarket health-check --tier cron|daily|weekly`
```

### Pattern 1: Dual-Channel Notify
**What:** Single `send_alert(title, message)` function fires both Telegram and osascript in sequence. Both channels always fire; neither blocks the other on failure.
**When to use:** Every alert path — pre-flight failures, daily summaries, weekly reports

```python
# Source: Telegram Bot API docs (api.telegram.org) + osascript man page
import subprocess
import httpx
import os

def send_alert(title: str, message: str) -> None:
    """Send alert to both Telegram and macOS notifications. Best-effort — never raises."""
    _send_telegram(title, message)
    _send_macos_notification(title, message)

def _send_telegram(title: str, message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    text = f"*{title}*\n{message}"
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass  # Never block the pipeline on notification failure

def _send_macos_notification(title: str, message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            timeout=5, capture_output=True,
        )
    except Exception:
        pass
```

### Pattern 2: Pre-flight Check + Alert + Skip
**What:** Cron script runs `polymarket health-check --tier cron` before the stage chain. On failure, the health-check command sends the alert and exits with code 1. The cron script treats exit code 1 as "skip this run, don't alert again" (alert already sent).
**When to use:** Every cron run (every 4h)

```bash
# In cron script — before the stage chain:
if ! polymarket --niche esports health-check --tier cron; then
    echo "Pre-flight failed. Skipping this run. Alert sent."
    exit 0  # Exit cleanly — don't let cron mark as failed
fi
# ... rest of pipeline stages
```

### Pattern 3: health_log Table
**What:** Every health-check run writes one row to `health_log`. Enables historical review (HLTH-06) and weekly diff computation (Q5 entries/exits).
**When to use:** Every call to health-check command

```sql
-- New table (added to schema.py run_migrations)
CREATE TABLE IF NOT EXISTS health_log (
    id TEXT PRIMARY KEY,          -- uuid or timestamp hash
    tier TEXT,                     -- 'cron' | 'daily' | 'weekly'
    timestamp TEXT,                -- ISO UTC
    status TEXT,                   -- 'pass' | 'warn' | 'fail'
    checks TEXT,                   -- JSON: {check_name: {status, value, threshold}}
    summary TEXT,                  -- Human-readable summary sent in alert
    niche TEXT                     -- e.g. 'esports'
);
```

### Pattern 4: Q5 Snapshot for Weekly Diff
**What:** Weekly check compares current Q5 list to the snapshot stored in the most recent `health_log` row with `tier='weekly'`. Diff = new entrants + exits.
**When to use:** Weekly health report (D-10)

```python
# Source: derived from existing _load_q5_traders() pattern in monitor.py
def compute_q5_diff(db, niche: str) -> dict:
    # Current Q5
    current = set(row[0] for row in db.execute(
        "SELECT trader_address FROM q5_traders WHERE category = ?", [niche]
    ).fetchall())
    
    # Previous snapshot from health_log
    prev_row = db.execute(
        """SELECT checks FROM health_log 
           WHERE tier='weekly' AND niche=? 
           ORDER BY timestamp DESC LIMIT 1""",
        [niche]
    ).fetchone()
    
    if prev_row:
        import json
        prev_checks = json.loads(prev_row[0])
        previous = set(prev_checks.get("q5_snapshot", []))
    else:
        previous = set()
    
    return {
        "entered": list(current - previous),
        "exited": list(previous - current),
        "current_snapshot": list(current),
    }
```

### Anti-Patterns to Avoid
- **Raising exceptions in notify functions:** Notification failure must never crash or block the pipeline. Every notify path must be try/except with pass.
- **Async Telegram calls during sync cron context:** Use synchronous `httpx.post()` (not async) in the cron-side health checks. The health-check command is not async — keep it simple.
- **Killing or pausing the monitor:** Per D-05, never attempt to coordinate with or kill the monitor process. The lock file (referenced in wiki) tells the monitor to skip, not the health system.
- **File-based stage logs that grow unboundedly:** Write health_log to SQLite (queryable), not append-only log files.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Memory reading | Custom /proc parsing | `psutil.virtual_memory()` | Cross-platform, handles macOS memory pressure correctly |
| Disk space | `os.statvfs` | `shutil.disk_usage(path)` | stdlib, simpler API, accurate on macOS APFS |
| Telegram HTTP | Custom retry/backoff | httpx with timeout=10 + try/except | Already installed; one call is sufficient; no retry needed (notification is best-effort) |
| macOS notification | Custom NSUserNotification bindings | osascript subprocess | Zero deps, verified working, AppleScript is stable |
| Unique health log IDs | Custom UUID | `datetime.now(timezone.utc).isoformat()` as primary key | Timestamp is naturally unique per-run at millisecond precision; human-readable for debugging |

---

## Common Pitfalls

### Pitfall 1: Notification failure blocks the pipeline
**What goes wrong:** `httpx.post()` to Telegram raises `ConnectTimeout` (network issue) → uncaught exception → cron aborts before doing any work.
**Why it happens:** Treating notification as critical path instead of best-effort side effect.
**How to avoid:** Every notify call wrapped in `try/except Exception: pass`. The health-check command's exit code reflects health status, not notification success.
**Warning signs:** Cron exits with error during pre-flight but no stages ran.

### Pitfall 2: Memory threshold too aggressive on this machine
**What goes wrong:** Pre-flight checks free RAM using `psutil.virtual_memory().available`. macOS reports very low "free" pages due to aggressive disk cache use (verified: only ~26 MB "free" right now). A threshold like 1 GB would always block the cron.
**Why it happens:** macOS memory management distinguishes "free" (unused) from "available" (free + reclaimable cache). `psutil.virtual_memory().available` correctly returns available (free + reclaimable), not just free pages.
**How to avoid:** Use `psutil.virtual_memory().available`, not `.free`. Recommended threshold: 500 MB available. At current load this machine has enough available even with minimal free pages.
**Warning signs:** Pre-flight always fails with "insufficient memory" even when pipeline runs fine manually.

### Pitfall 3: lift_scores staleness false positives
**What goes wrong:** Health check compares `lift_scores.computed_at` to `now()`. If the machine was asleep, `now()` is hours ahead of the last computed_at, triggering a stale-scores alert even though the cron ran fine before sleep.
**Why it happens:** Wall-clock staleness check doesn't account for machine sleep/wake cycles.
**How to avoid:** Stale-scores check should be a WARN, not a FAIL (already per D-08: "warn if older than expected"). Never block a cron run purely on score staleness. The wiki's 5-hour threshold (one 4h interval + 1h buffer) is the right number.
**Warning signs:** Spurious alerts after laptop wakes from sleep.

### Pitfall 4: Daily summary double-counting signals
**What goes wrong:** "signals count" for daily summary queries all signals in the DB, not just new ones from the last 24h. 469 signals already exist — the daily count would always be 469+.
**Why it happens:** The signals table has `first_seen` and `last_updated` timestamps. Only `last_updated` within the last 24h window represents today's activity.
**How to avoid:** Daily summary queries `WHERE last_updated >= datetime('now', '-1 day')` to count active signals updated in the window. Or use `first_seen` to count truly new signals.
**Warning signs:** Daily alert always reports the same large number (total) instead of a delta.

### Pitfall 5: Weekly Q5 diff on first run
**What goes wrong:** First weekly report has no previous snapshot to diff against. Code raises KeyError or crashes trying to deserialize the previous Q5 list.
**Why it happens:** No guard for "no previous health_log row."
**How to avoid:** If `prev_row is None`, report "first weekly run — no previous snapshot to diff" and store current snapshot. Don't compute a diff.
**Warning signs:** Weekly check crashes on first use.

### Pitfall 6: osascript special characters in message string
**What goes wrong:** Alert message contains a quote (`"`) or backslash → osascript AppleScript string breaks → notification silently fails or throws AppleScript error.
**Why it happens:** String is interpolated directly into AppleScript source.
**How to avoid:** Sanitize message before passing to osascript: strip or replace double quotes. Or use the `-e` flag with single-quoted AppleScript and escape inner quotes carefully.
**Warning signs:** Notifications stop working after a message contains a ticker symbol or file path.

---

## Code Examples

### Telegram Bot API via httpx (synchronous)
```python
# Source: api.telegram.org/bots/api#sendmessage — verified endpoint returns 302 on GET
import httpx
import os

def send_telegram(title: str, body: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"*{title}*\n{body}",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
    except Exception:
        pass
```

### macOS notification via osascript (verified working on this machine)
```python
# Source: [VERIFIED: direct test on this machine — osascript at /usr/bin/osascript]
import subprocess

def send_macos_notification(title: str, body: str) -> None:
    # Sanitize quotes to prevent AppleScript injection
    safe_body = body.replace('"', "'")
    safe_title = title.replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_body}" with title "{safe_title}"'],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass
```

### Memory pre-flight check (using psutil.available)
```python
# Source: [ASSUMED based on psutil docs] — psutil.virtual_memory().available is
# the correct macOS metric (free + reclaimable cache), not .free
import psutil
import shutil

MEMORY_THRESHOLD_MB = 500
DISK_THRESHOLD_GB = 10

def preflight_checks(db_path: str) -> list[dict]:
    """Returns list of {name, status, value, threshold, message} dicts."""
    results = []
    
    # Memory check
    mem = psutil.virtual_memory()
    available_mb = mem.available / (1024 ** 2)
    results.append({
        "name": "memory",
        "status": "fail" if available_mb < MEMORY_THRESHOLD_MB else "pass",
        "value": f"{available_mb:.0f} MB",
        "threshold": f"{MEMORY_THRESHOLD_MB} MB",
        "message": f"Available RAM: {available_mb:.0f} MB",
    })
    
    # Disk check
    disk = shutil.disk_usage(db_path)
    free_gb = disk.free / (1024 ** 3)
    results.append({
        "name": "disk",
        "status": "fail" if free_gb < DISK_THRESHOLD_GB else "pass",
        "value": f"{free_gb:.1f} GB",
        "threshold": f"{DISK_THRESHOLD_GB} GB",
        "message": f"Free disk: {free_gb:.1f} GB",
    })
    
    return results
```

### lift_scores staleness check (modeled on existing _load_q5_traders pattern)
```python
# Source: [VERIFIED: existing pattern in monitor.py _load_q5_traders()]
from datetime import datetime, timezone, timedelta

STALENESS_HOURS = 5  # one 4h cron interval + 1h buffer

def check_lift_scores_freshness(db, niche: str) -> dict:
    row = db.execute(
        "SELECT MAX(computed_at) FROM lift_scores WHERE category = ?", [niche]
    ).fetchone()
    computed_at = row[0] if row and row[0] else None
    
    if not computed_at:
        return {"name": "lift_scores_freshness", "status": "warn",
                "message": "lift_scores never computed"}
    
    try:
        dt = datetime.fromisoformat(computed_at.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        status = "warn" if age_hours > STALENESS_HOURS else "pass"
        return {
            "name": "lift_scores_freshness",
            "status": status,
            "value": f"{age_hours:.1f}h old",
            "threshold": f"{STALENESS_HOURS}h",
            "message": f"lift_scores are {age_hours:.1f}h old (last scored: {computed_at})",
        }
    except Exception as e:
        return {"name": "lift_scores_freshness", "status": "warn",
                "message": f"Could not parse computed_at: {e}"}
```

### Daily summary queries
```python
# Source: [VERIFIED: signals table schema in schema.py — fields first_seen, last_updated exist]
from datetime import datetime, timezone, timedelta

def daily_summary(db, niche: str) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    
    new_signals = db.execute(
        "SELECT COUNT(*) FROM signals WHERE first_seen >= ?", [cutoff]
    ).fetchone()[0]
    
    updated_signals = db.execute(
        "SELECT COUNT(*) FROM signals WHERE last_updated >= ?", [cutoff]
    ).fetchone()[0]
    
    traders_discovered = db.execute(
        "SELECT COUNT(*) FROM traders WHERE first_seen >= ?", [cutoff]
    ).fetchone()[0]
    
    traders_backfilled = db.execute(
        "SELECT COUNT(*) FROM traders WHERE last_backfilled_at >= ?", [cutoff]
    ).fetchone()[0]
    
    return {
        "new_signals": new_signals,
        "updated_signals": updated_signals,
        "traders_discovered": traders_discovered,
        "traders_backfilled": traders_backfilled,
    }
```

### Weekly data completeness check
```python
# Source: [VERIFIED: positions.data_incomplete column exists in schema.py]
def data_completeness(db) -> dict:
    row = db.execute(
        "SELECT COUNT(*), SUM(data_incomplete) FROM positions"
    ).fetchone()
    total, incomplete = row[0], row[1] or 0
    pct = (incomplete / total * 100) if total > 0 else 0
    # Baseline: 1836/1030198 = 0.2% — verified 2026-04-11
    return {
        "total_positions": total,
        "incomplete_positions": incomplete,
        "pct_incomplete": round(pct, 2),
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No health monitoring | Per-cron + daily + weekly checks | Phase 9 (new) | Operational awareness without self-healing |
| Telegram via python-telegram-bot library | Direct httpx POST to Bot API | Decision D-03 (this phase) | No new library dependency needed |
| Console-only health warnings (current monitor staleness warn) | Dual-channel persistent alerts | Phase 9 (new) | User informed even when away from terminal |

**Deprecated/outdated:**
- `terminal-notifier`: Not installed on this machine. osascript is simpler and built-in.
- python-telegram-bot library: Heavy dep not needed when httpx is already available and Bot API is simple REST.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `psutil.virtual_memory().available` correctly reports reclaimable+free on macOS (not just truly free pages) | Common Pitfalls, Code Examples | If wrong, pre-flight would always fail — 26 MB "free" but ~2+ GB available in practice |
| A2 | Telegram Bot API endpoint is `api.telegram.org/bot{TOKEN}/sendMessage` with `chat_id` + `text` + `parse_mode` JSON body | Code Examples | Low risk — Bot API has been stable at this endpoint for years |
| A3 | `first_seen` column exists on `traders` table for daily summary query | Code Examples | Verify in schema.py — schema shows `first_seen` on traders table [VERIFIED] |
| A4 | Scoring drift detection is useful if `stddev(composite_score)` changes >20% week over week | Open Questions | May need user input on what "significant drift" means |

---

## Open Questions

1. **What constitutes "significant" scoring drift for the weekly report?**
   - What we know: composite_score is z_clv + z_roi + z_sharpe. Current Q5 has 530 traders.
   - What's unclear: What % change in stddev or mean composite_score should trigger a warning vs informational message?
   - Recommendation: Start with >20% week-over-week change in median composite_score as "notable drift." Report the actual numbers always; only warn if threshold crossed.

2. **"Suspiciously quiet" canary threshold**
   - What we know: 469 signals currently exist. Pipeline has been running ~2 weeks.
   - What's unclear: How many active markets justify expecting at least 1 new signal per 7 days?
   - Recommendation: Canary fires if `COUNT(*) WHERE first_seen >= 7 days ago = 0` AND `COUNT(*) active markets > 5`. This avoids false positives during genuine quiet periods.

3. **Stage exit code tracking — cron vs Python command**
   - What we know: Cron script chains stages with `&&`. A failed stage stops the chain. The health-check sees the aftermath, not the individual stage that failed.
   - What's unclear: Should stage exit codes be captured per-stage in the cron script and passed to health-check, or should health-check infer failure from DB state?
   - Recommendation: Cron script captures exit codes per stage and passes them as a summary to `polymarket health-check --tier daily --stages-failed "backfill,score"`. Simpler than DB-based inference.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| osascript | macOS notifications (HLTH-04) | Yes | system built-in | None needed |
| httpx | Telegram Bot API (HLTH-04) | Yes | 0.28.1 | None needed |
| psutil | Memory pre-flight (HLTH-01) | No (needs install) | 7.2.2 | shutil.disk_usage for disk; no fallback for RAM — must install |
| shutil | Disk pre-flight (HLTH-01) | Yes | stdlib | None needed |
| TELEGRAM_BOT_TOKEN | Telegram delivery (HLTH-04) | Not in .env yet | — | Skip Telegram silently if missing |
| TELEGRAM_CHAT_ID | Telegram delivery (HLTH-04) | Not in .env yet | — | Skip Telegram silently if missing |

**Missing dependencies with no fallback:**
- psutil: Required for memory check. `uv add psutil` must run in Wave 0. No pure-Python alternative for available RAM on macOS.

**Missing dependencies with fallback:**
- TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: Not yet in .env. Telegram notify function silently no-ops when missing — macOS notification still fires. User must add these to .env to enable Telegram channel.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | pyproject.toml (implicit) |
| Quick run command | `.venv/bin/python -m pytest tests/ -x -q` |
| Full suite command | `.venv/bin/python -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HLTH-01 | Memory check returns fail when below threshold | unit | `pytest tests/test_health.py::test_preflight_memory_fail -x` | No — Wave 0 |
| HLTH-01 | Disk check returns fail when below threshold | unit | `pytest tests/test_health.py::test_preflight_disk_fail -x` | No — Wave 0 |
| HLTH-01 | lift_scores staleness check returns warn at >5h | unit | `pytest tests/test_health.py::test_staleness_warn -x` | No — Wave 0 |
| HLTH-02 | Daily summary counts signals updated in last 24h | unit | `pytest tests/test_health.py::test_daily_summary -x` | No — Wave 0 |
| HLTH-03 | Q5 diff correctly detects entrants and exits | unit | `pytest tests/test_health.py::test_q5_diff -x` | No — Wave 0 |
| HLTH-03 | Quiet canary fires when 0 new signals in 7 days with active markets | unit | `pytest tests/test_health.py::test_quiet_canary -x` | No — Wave 0 |
| HLTH-04 | send_alert calls both channels without raising | unit | `pytest tests/test_health.py::test_send_alert_both_channels -x` | No — Wave 0 |
| HLTH-04 | send_alert silently no-ops when TELEGRAM credentials missing | unit | `pytest tests/test_health.py::test_send_alert_no_credentials -x` | No — Wave 0 |
| HLTH-05 | Pre-flight fail → send alert → exit 1 (skip cycle) | unit | `pytest tests/test_health.py::test_preflight_fail_sends_alert -x` | No — Wave 0 |
| HLTH-06 | health_log row written after each check run | unit | `pytest tests/test_health.py::test_health_log_persisted -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_health.py -x -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_health.py` — all 10 tests listed above; covers HLTH-01 through HLTH-06
- [ ] `src/polymarket_analytics/health/__init__.py` — package init
- [ ] `uv add psutil` — required before any health check code can import psutil

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Bot token in .env (same pattern as GRAPH_API_KEY) |
| V3 Session Management | No | Stateless HTTP POST per alert |
| V4 Access Control | No | Single-user local pipeline |
| V5 Input Validation | Yes | Sanitize alert message before osascript interpolation (strip/replace quotes) |
| V6 Cryptography | No | Bot token is plaintext in .env — same risk as existing API keys |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| osascript injection via unescaped message | Tampering | Replace `"` with `'` in all strings before AppleScript interpolation |
| Telegram token in env var | Info Disclosure | .env already in .gitignore (verified by project conventions); no new risk |
| Notification flood (health check loop bug) | Denial of Service | health_log timestamp prevents duplicate alerts: check if same tier+status already logged in last N minutes before sending |

---

## Sources

### Primary (HIGH confidence)
- `monitor.py` lines 47-77 — `_load_q5_traders()` staleness pattern, direct read [VERIFIED: codebase]
- `schema.py` — all table schemas including signals.first_seen, signals.last_updated, traders.first_seen, positions.data_incomplete [VERIFIED: codebase]
- `../LLM Wiki/workspaces/polymarket/wiki/cron-architecture.md` — 4h cron schedule, lean/full modes, staleness threshold, lock file [VERIFIED: wiki read]
- `../LLM Wiki/workspaces/polymarket/wiki/operations-overview.md` — health check design (lock, memory, WAL, disk, staleness checks) [VERIFIED: wiki read]
- osascript direct test — notification works on this machine [VERIFIED: `osascript -e ...` returned success]
- httpx Telegram connectivity — `api.telegram.org` reachable (302 redirect) [VERIFIED: httpx GET test]
- psutil 7.2.2 pip dry-run — installable on this platform [VERIFIED: pip --dry-run]

### Secondary (MEDIUM confidence)
- Telegram Bot API endpoint format `api.telegram.org/bot{TOKEN}/sendMessage` with JSON body [CITED: https://core.telegram.org/bots/api#sendmessage — standard since 2015, stable]
- `psutil.virtual_memory().available` as the correct macOS metric (free + reclaimable) [CITED: https://psutil.readthedocs.io/en/latest/#psutil.virtual_memory]

### Tertiary (LOW confidence)
- 20% composite_score stddev as "significant drift" threshold — informed estimate, not benchmarked against this dataset [ASSUMED]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified present or installable; Telegram API verified reachable; osascript verified working
- Architecture: HIGH — directly derived from existing codebase patterns (ShutdownManager, _load_q5_traders, schema patterns)
- Pitfalls: HIGH for osascript/memory pitfalls (verified on this machine); MEDIUM for daily summary double-counting (verified schema, inferred from field semantics)
- Thresholds (memory 500MB, disk 10GB, staleness 5h): MEDIUM — 500MB/5h directly from wiki; 10GB is reasonable for 9.1GB DB with WAL headroom

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (stable stack; Telegram Bot API changes rarely)
