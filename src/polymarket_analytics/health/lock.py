"""Pipeline lock file protocol.

Prevents cron and monitor from overlapping on the same database.
Lock file is at data/.pipeline.lock, contains JSON with PID, process type,
and start time for debugging stale locks.

Usage:
    # Cron: blocks if another cron is running
    with PipelineLock("cron", lock_path="data/.pipeline.lock") as acquired:
        if not acquired:
            sys.exit(1)  # another cron is running
        run_pipeline()

    # Monitor: skips pass if cron lock is held
    with PipelineLock("monitor", lock_path="data/.pipeline.lock") as acquired:
        if not acquired:
            print("Cron is running, skipping this pass")
            return
        do_monitor_pass()
"""

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _read_lock(lock_path: Path) -> dict | None:
    """Read and parse lock file. Returns None if file doesn't exist or is corrupt."""
    try:
        if not lock_path.exists():
            return None
        content = lock_path.read_text().strip()
        if not content:
            return None
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return None


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _write_lock(lock_path: Path, process_type: str) -> None:
    """Write lock file with current process info."""
    lock_data = {
        "pid": os.getpid(),
        "process_type": process_type,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock_data))


def _remove_lock(lock_path: Path) -> None:
    """Remove lock file if it exists."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def check_lock(lock_path: str | Path) -> dict | None:
    """Check if a valid lock is held. Returns lock info dict or None.

    Automatically cleans up stale locks (PID no longer running).
    """
    lock_path = Path(lock_path)
    lock_info = _read_lock(lock_path)
    if lock_info is None:
        return None

    pid = lock_info.get("pid")
    if pid and not _is_process_alive(pid):
        # Stale lock — process died without cleanup
        _remove_lock(lock_path)
        return None

    return lock_info


@contextmanager
def pipeline_lock(process_type: str, lock_path: str | Path = "data/.pipeline.lock"):
    """Context manager for pipeline lock acquisition.

    Args:
        process_type: "cron" or "monitor"
        lock_path: Path to lock file

    Yields:
        dict | None — lock info if acquired (truthy), None if blocked (falsy).
        The dict contains: pid, process_type, started_at.

    Behavior:
        - If no lock exists: acquires it, yields lock info.
        - If lock held by dead process: cleans up stale lock, acquires it.
        - Cron vs cron: blocked (yields None).
        - Monitor vs cron: blocked (yields None, monitor should skip pass).
        - Cron vs monitor: acquires (cron has priority, can preempt monitor).
        - Monitor vs monitor: blocked (second monitor skips, avoids duplicate writes).
    """
    lock_path = Path(lock_path)
    existing = check_lock(lock_path)

    if existing is not None:
        holder_type = existing.get("process_type", "unknown")

        # Cron blocks everyone (cron is the scheduled heavy process).
        if holder_type == "cron":
            yield None
            return

        # Monitor blocks another monitor: --chain is also heavy, and two concurrent
        # monitor passes would do redundant work and race-write analytics.db.
        # Cron is NOT blocked by a running monitor — cron has priority.
        if holder_type == "monitor" and process_type == "monitor":
            yield None
            return

    # Acquire lock
    _write_lock(lock_path, process_type)
    try:
        yield {
            "pid": os.getpid(),
            "process_type": process_type,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        # Only release if we still own it (check PID to avoid race)
        current = _read_lock(lock_path)
        if current and current.get("pid") == os.getpid():
            _remove_lock(lock_path)
