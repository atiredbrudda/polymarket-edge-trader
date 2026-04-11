"""Per-cron pre-flight health checks (D-08).

Checks memory, disk, lock, and lift_scores freshness. Returns structured results
that the CLI command uses to decide pass/fail/alert.

Also provides daily_summary (D-09) and weekly report helpers (D-10):
compute_q5_diff, check_quiet_canary, check_scoring_drift, check_data_completeness.
"""
import json
import shutil
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

from polymarket_analytics.health.lock import check_lock

MEMORY_THRESHOLD_MB = 500    # Per research: macOS needs .available not .free
DISK_THRESHOLD_GB = 10       # ~10% headroom for 9.1GB DB with WAL

STALENESS_HOURS = 5          # One 4h cron interval + 1h buffer (from wiki)


def check_pipeline_lock(db_path: str) -> dict:
    """Check if another cron process holds the pipeline lock.

    Returns {name, status, value, threshold, message}.
    Status is "fail" if a cron lock is held, "pass" otherwise.
    """
    lock_path = Path(db_path).parent / ".pipeline.lock"
    lock_info = check_lock(lock_path)

    if lock_info is None:
        return {
            "name": "pipeline_lock",
            "status": "pass",
            "value": "free",
            "threshold": "no cron lock",
            "message": "Pipeline lock is free",
        }

    holder_type = lock_info.get("process_type", "unknown")
    holder_pid = lock_info.get("pid", "?")
    started = lock_info.get("started_at", "?")

    if holder_type == "cron":
        return {
            "name": "pipeline_lock",
            "status": "fail",
            "value": f"locked by cron (PID {holder_pid})",
            "threshold": "no cron lock",
            "message": f"Pipeline locked by cron (PID {holder_pid}, started {started})",
        }

    # Monitor lock is not a blocker for cron
    return {
        "name": "pipeline_lock",
        "status": "pass",
        "value": f"locked by {holder_type} (PID {holder_pid})",
        "threshold": "no cron lock",
        "message": f"Pipeline lock held by {holder_type} (non-blocking)",
    }


def preflight_checks(db_path: str) -> list[dict]:
    """Run lock + memory + disk pre-flight checks. Returns list of check result dicts.

    Each dict: {name, status, value, threshold, message}
    status is "pass" or "fail".
    """
    results = []

    # Lock check — fail if another cron holds the lock
    results.append(check_pipeline_lock(db_path))

    # Memory check — use .available (free + reclaimable cache), NOT .free
    mem = psutil.virtual_memory()
    available_mb = mem.available / (1024 ** 2)
    results.append({
        "name": "memory",
        "status": "fail" if available_mb < MEMORY_THRESHOLD_MB else "pass",
        "value": f"{available_mb:.0f} MB",
        "threshold": f"{MEMORY_THRESHOLD_MB} MB",
        "message": f"Available RAM: {available_mb:.0f} MB (threshold: {MEMORY_THRESHOLD_MB} MB)",
    })

    # Disk check — shutil.disk_usage is stdlib, works on macOS APFS
    disk = shutil.disk_usage(db_path)
    free_gb = disk.free / (1024 ** 3)
    results.append({
        "name": "disk",
        "status": "fail" if free_gb < DISK_THRESHOLD_GB else "pass",
        "value": f"{free_gb:.1f} GB",
        "threshold": f"{DISK_THRESHOLD_GB} GB",
        "message": f"Free disk: {free_gb:.1f} GB (threshold: {DISK_THRESHOLD_GB} GB)",
    })

    return results


def check_lift_scores_freshness(db, niche: str) -> dict:
    """Check if lift_scores.computed_at is within STALENESS_HOURS.

    Returns {name, status, value, threshold, message}.
    Status is "pass" or "warn" (never "fail" — per D-08, staleness is a warning).
    """
    row = db.execute(
        "SELECT MAX(computed_at) FROM lift_scores WHERE category = ?", [niche]
    ).fetchone()
    computed_at = row[0] if row and row[0] else None

    if not computed_at:
        return {
            "name": "lift_scores_freshness",
            "status": "warn",
            "value": "never",
            "threshold": f"{STALENESS_HOURS}h",
            "message": "lift_scores never computed for this niche",
        }

    try:
        dt = datetime.fromisoformat(computed_at.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        status = "warn" if age_hours > STALENESS_HOURS else "pass"
        return {
            "name": "lift_scores_freshness",
            "status": status,
            "value": f"{age_hours:.1f}h",
            "threshold": f"{STALENESS_HOURS}h",
            "message": f"lift_scores are {age_hours:.1f}h old (threshold: {STALENESS_HOURS}h)",
        }
    except Exception as e:
        return {
            "name": "lift_scores_freshness",
            "status": "warn",
            "value": "parse_error",
            "threshold": f"{STALENESS_HOURS}h",
            "message": f"Could not parse computed_at: {e}",
        }


def daily_summary(db, niche: str, stages_failed: list[str] | None = None) -> dict:
    """Daily summary (D-09): signals, traders, errors in last 24h.

    Returns dict with keys: new_signals, updated_signals, traders_discovered,
    traders_backfilled, errored_stages.
    """
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
        "errored_stages": stages_failed or [],
    }


def compute_q5_diff(db, niche: str) -> dict:
    """Q5 list diff vs previous weekly snapshot (D-10).

    Returns {entered, exited, current_snapshot, message}.
    Handles corrupt health_log JSON gracefully (T-09-07 mitigation).
    """
    # Current Q5 traders
    rows = db.execute(
        "SELECT trader_address FROM q5_traders WHERE category = ?", [niche]
    ).fetchall()
    current = set(r[0] for r in rows)

    # Previous snapshot from health_log
    prev_row = db.execute(
        """SELECT checks FROM health_log
           WHERE tier='weekly' AND niche=?
           ORDER BY timestamp DESC LIMIT 1""",
        [niche],
    ).fetchone()

    if not prev_row:
        return {
            "entered": [],
            "exited": [],
            "current_snapshot": sorted(current),
            "message": "First weekly run — no previous snapshot to diff",
        }

    # T-09-07: wrap JSON parse in try/except — fallback to empty dict on corrupt data
    try:
        prev_checks = json.loads(prev_row[0]) if prev_row[0] else {}
    except (json.JSONDecodeError, TypeError):
        prev_checks = {}

    previous = set(prev_checks.get("q5_snapshot", []))

    entered = sorted(current - previous)
    exited = sorted(previous - current)

    return {
        "entered": entered,
        "exited": exited,
        "current_snapshot": sorted(current),
        "message": f"Q5 changes: +{len(entered)} entered, -{len(exited)} exited",
    }


def check_quiet_canary(db, niche: str) -> dict:
    """Suspiciously quiet canary (D-10): 0 new signals in 7 days with active markets.

    Only fires when there ARE active markets — avoids false positives during
    genuine quiet periods (e.g. off-season).
    """
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    new_signals_7d = db.execute(
        "SELECT COUNT(*) FROM signals WHERE first_seen >= ?", [cutoff_7d]
    ).fetchone()[0]

    active_markets = db.execute(
        "SELECT COUNT(*) FROM markets WHERE active = 1 AND resolved = 0 AND niche_slug = ?",
        [niche],
    ).fetchone()[0]

    if new_signals_7d == 0 and active_markets > 5:
        return {
            "name": "quiet_canary",
            "status": "warn",
            "value": f"0 new signals, {active_markets} active markets",
            "threshold": ">0 signals per 7 days with active markets",
            "message": (
                f"Suspiciously quiet: 0 new signals in 7 days with {active_markets} active markets"
            ),
        }

    return {
        "name": "quiet_canary",
        "status": "pass",
        "value": f"{new_signals_7d} new signals, {active_markets} active markets",
        "threshold": ">0 signals per 7 days with active markets",
        "message": f"{new_signals_7d} new signals in last 7 days, {active_markets} active markets",
    }


def check_scoring_drift(db, niche: str) -> dict:
    """Scoring drift detection (D-10): >20% change in median composite_score.

    Compares current median to previous weekly snapshot. Reports numbers always;
    warns only if threshold crossed.
    Handles corrupt health_log JSON gracefully (T-09-07 mitigation).
    """
    # Current median composite_score for Q5 traders
    rows = db.execute(
        "SELECT composite_score FROM q5_traders WHERE category = ?", [niche]
    ).fetchall()

    if not rows:
        return {
            "name": "scoring_drift",
            "status": "pass",
            "value": "no Q5 traders",
            "threshold": "20% change",
            "message": "No Q5 traders — cannot compute drift",
        }

    current_scores = [r[0] for r in rows if r[0] is not None]
    current_median = statistics.median(current_scores) if current_scores else 0.0

    # Previous median from health_log
    prev_row = db.execute(
        """SELECT checks FROM health_log
           WHERE tier='weekly' AND niche=?
           ORDER BY timestamp DESC LIMIT 1""",
        [niche],
    ).fetchone()

    if not prev_row:
        return {
            "name": "scoring_drift",
            "status": "pass",
            "value": f"median={current_median:.2f}",
            "threshold": "20% change",
            "message": f"First weekly run — current median composite: {current_median:.2f}",
        }

    # T-09-07: wrap JSON parse in try/except — fallback on corrupt data
    try:
        prev_checks = json.loads(prev_row[0]) if prev_row[0] else {}
    except (json.JSONDecodeError, TypeError):
        prev_checks = {}

    prev_median = prev_checks.get("median_composite", current_median)

    if prev_median == 0:
        pct_change = 0.0
    else:
        pct_change = abs(current_median - prev_median) / abs(prev_median) * 100

    status = "warn" if pct_change > 20 else "pass"
    return {
        "name": "scoring_drift",
        "status": status,
        "value": f"median={current_median:.2f} (was {prev_median:.2f}, {pct_change:.0f}% change)",
        "threshold": "20% change",
        "message": (
            f"Scoring drift: median composite {prev_median:.2f} -> "
            f"{current_median:.2f} ({pct_change:.0f}% change)"
        ),
    }


def check_data_completeness(db) -> dict:
    """Data completeness (D-10): % of positions with data_incomplete flag.

    Always returns status="pass" — informational metric only.
    """
    row = db.execute(
        "SELECT COUNT(*), SUM(CASE WHEN data_incomplete = 1 THEN 1 ELSE 0 END) FROM positions"
    ).fetchone()
    total = row[0] or 0
    incomplete = row[1] or 0
    pct = round((incomplete / total * 100), 1) if total > 0 else 0.0

    return {
        "name": "data_completeness",
        "status": "pass",  # Informational — always pass
        "value": f"{incomplete}/{total} ({pct}%)",
        "threshold": "informational",
        "message": f"Data completeness: {incomplete}/{total} positions incomplete ({pct}%)",
    }
