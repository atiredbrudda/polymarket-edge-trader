"""Tests for pipeline lock file protocol."""

import json
import os
from pathlib import Path

from polymarket_analytics.health.lock import (
    check_lock,
    pipeline_lock,
    _read_lock,
    _write_lock,
    _remove_lock,
)


def test_acquire_and_release(tmp_path):
    """Lock is acquired when no lock exists, released on exit."""
    lock_file = tmp_path / ".pipeline.lock"

    with pipeline_lock("cron", lock_path=lock_file) as acquired:
        assert acquired is not None
        assert acquired["process_type"] == "cron"
        assert acquired["pid"] == os.getpid()
        # Lock file should exist during context
        assert lock_file.exists()

    # Lock file should be removed after context
    assert not lock_file.exists()


def test_cron_blocks_cron(tmp_path):
    """A cron lock blocks another cron from acquiring."""
    lock_file = tmp_path / ".pipeline.lock"

    # Simulate an existing cron lock from current process (alive PID)
    _write_lock(lock_file, "cron")

    # Try to acquire as cron — should be blocked
    with pipeline_lock("cron", lock_path=lock_file) as acquired:
        assert acquired is None


def test_cron_blocks_monitor(tmp_path):
    """A cron lock blocks monitor from acquiring (monitor should skip pass)."""
    lock_file = tmp_path / ".pipeline.lock"

    # Simulate an existing cron lock
    _write_lock(lock_file, "cron")

    # Try to acquire as monitor — should be blocked
    with pipeline_lock("monitor", lock_path=lock_file) as acquired:
        assert acquired is None


def test_monitor_does_not_block_cron(tmp_path):
    """A monitor lock does NOT block cron (monitor is lightweight)."""
    lock_file = tmp_path / ".pipeline.lock"

    # Simulate an existing monitor lock
    _write_lock(lock_file, "monitor")

    # Try to acquire as cron — should succeed
    with pipeline_lock("cron", lock_path=lock_file) as acquired:
        assert acquired is not None
        assert acquired["process_type"] == "cron"


def test_monitor_does_not_block_monitor(tmp_path):
    """A monitor lock does NOT block another monitor."""
    lock_file = tmp_path / ".pipeline.lock"

    # Simulate an existing monitor lock
    _write_lock(lock_file, "monitor")

    # Try to acquire as monitor — should succeed
    with pipeline_lock("monitor", lock_path=lock_file) as acquired:
        assert acquired is not None


def test_stale_lock_cleaned_up(tmp_path):
    """A lock from a dead process is cleaned up and new lock acquired."""
    lock_file = tmp_path / ".pipeline.lock"

    # Write a lock with a PID that definitely doesn't exist
    lock_data = {
        "pid": 99999999,
        "process_type": "cron",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    lock_file.write_text(json.dumps(lock_data))

    # check_lock should detect the stale lock and clean it up
    result = check_lock(lock_file)
    assert result is None
    assert not lock_file.exists()


def test_stale_lock_allows_acquisition(tmp_path):
    """A stale cron lock doesn't block new acquisition."""
    lock_file = tmp_path / ".pipeline.lock"

    # Write stale lock (dead PID)
    lock_data = {
        "pid": 99999999,
        "process_type": "cron",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    lock_file.write_text(json.dumps(lock_data))

    # Should acquire successfully since the old process is dead
    with pipeline_lock("cron", lock_path=lock_file) as acquired:
        assert acquired is not None
        assert acquired["process_type"] == "cron"


def test_corrupt_lock_file_ignored(tmp_path):
    """A corrupt lock file is treated as no lock."""
    lock_file = tmp_path / ".pipeline.lock"
    lock_file.write_text("not valid json{{{")

    result = check_lock(lock_file)
    assert result is None


def test_empty_lock_file_ignored(tmp_path):
    """An empty lock file is treated as no lock."""
    lock_file = tmp_path / ".pipeline.lock"
    lock_file.write_text("")

    result = check_lock(lock_file)
    assert result is None


def test_no_lock_file(tmp_path):
    """No lock file means no lock."""
    lock_file = tmp_path / ".pipeline.lock"
    result = check_lock(lock_file)
    assert result is None


def test_lock_file_contains_valid_json(tmp_path):
    """Lock file written by _write_lock contains valid JSON with expected fields."""
    lock_file = tmp_path / ".pipeline.lock"
    _write_lock(lock_file, "cron")

    data = json.loads(lock_file.read_text())
    assert data["pid"] == os.getpid()
    assert data["process_type"] == "cron"
    assert "started_at" in data
