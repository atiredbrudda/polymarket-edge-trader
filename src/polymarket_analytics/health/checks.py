"""Per-cron pre-flight health checks (D-08).

Checks memory, disk, and lift_scores freshness. Returns structured results
that the CLI command uses to decide pass/fail/alert.
"""
import shutil
from datetime import datetime, timezone

import psutil

MEMORY_THRESHOLD_MB = 500    # Per research: macOS needs .available not .free
DISK_THRESHOLD_GB = 10       # ~10% headroom for 9.1GB DB with WAL

STALENESS_HOURS = 5          # One 4h cron interval + 1h buffer (from wiki)


def preflight_checks(db_path: str) -> list[dict]:
    """Run memory + disk pre-flight checks. Returns list of check result dicts.

    Each dict: {name, status, value, threshold, message}
    status is "pass" or "fail".
    """
    results = []

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
