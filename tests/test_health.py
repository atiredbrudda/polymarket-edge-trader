"""Tests for health monitoring infrastructure — notify.py and log.py.

Plans 09-01 through 09-03 share this test file.
Plans 09-02 and 09-03 tests are marked skip until implemented.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
import sqlite_utils


# ---------------------------------------------------------------------------
# Plan 09-01: notify.py tests
# ---------------------------------------------------------------------------


def test_send_alert_both_channels(monkeypatch):
    """Both Telegram and macOS channels fire on a successful alert."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    with patch("httpx.post") as mock_post, patch("subprocess.run") as mock_run:
        mock_post.return_value = MagicMock(status_code=200)
        mock_run.return_value = MagicMock(returncode=0)

        from polymarket_analytics.health.notify import send_alert

        send_alert("Test Title", "Test body")

        assert mock_post.call_count == 1
        call_kwargs = mock_post.call_args
        url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs.kwargs.get("url", "")
        if not url:
            # positional
            url = mock_post.call_args.args[0]
        assert "api.telegram.org" in url

        posted_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert posted_json["chat_id"] == "12345"
        assert "Test Title" in posted_json["text"] or "Test body" in posted_json["text"]

        assert mock_run.call_count == 1
        run_args = mock_run.call_args[0][0]
        assert "osascript" in run_args


def test_send_alert_no_credentials(monkeypatch):
    """Telegram is skipped when credentials are missing; macOS still fires."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with patch("httpx.post") as mock_post, patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        from polymarket_analytics.health.notify import send_alert

        send_alert("Title", "Body")

        mock_post.assert_not_called()
        assert mock_run.call_count == 1


def test_send_alert_telegram_error_no_raise(monkeypatch):
    """Telegram failure does not raise; macOS notification still fires."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    import httpx

    with patch("httpx.post", side_effect=httpx.ConnectTimeout("timeout")) as mock_post, \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        from polymarket_analytics.health.notify import send_alert

        # Must not raise
        send_alert("Title", "Body")

        assert mock_run.call_count == 1


def test_send_alert_osascript_sanitizes_quotes(monkeypatch):
    """Double quotes in title/body are replaced with single quotes in osascript args."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        from polymarket_analytics.health.notify import send_alert

        send_alert('Title with "quotes"', 'Body with "quotes"')

        assert mock_run.call_count == 1
        run_args = mock_run.call_args[0][0]
        # The osascript -e string argument (last element) must not contain literal "
        osascript_str = run_args[-1]
        # The inner content of the AppleScript display notification call should not have "
        # (only the outer wrapping quotes from AppleScript syntax are OK)
        # We check the sanitized values don't appear inside the AppleScript string
        assert '"quotes"' not in osascript_str


# ---------------------------------------------------------------------------
# Plan 09-01: log.py tests
# ---------------------------------------------------------------------------


def test_health_log_persisted():
    """write_health_log inserts a row into health_log table."""
    db = sqlite_utils.Database(memory=True)

    from polymarket_analytics.health.log import create_health_log_table, write_health_log

    create_health_log_table(db)
    write_health_log(
        db,
        tier="cron",
        status="pass",
        checks={"memory": {"status": "pass"}},
        summary="All clear",
        niche="esports",
    )

    rows = list(db.execute("SELECT * FROM health_log").fetchall())
    assert len(rows) == 1
    row = rows[0]
    # columns: id, tier, timestamp, status, checks, summary, niche
    assert row[1] == "cron"
    assert row[3] == "pass"
    assert row[6] == "esports"


def test_health_log_query_by_tier():
    """read_health_log filters correctly by tier."""
    db = sqlite_utils.Database(memory=True)

    from polymarket_analytics.health.log import (
        create_health_log_table,
        read_health_log,
        write_health_log,
    )

    create_health_log_table(db)
    write_health_log(db, tier="cron", status="pass", checks={}, summary="cron ok", niche="esports")
    write_health_log(
        db, tier="weekly", status="pass", checks={}, summary="weekly ok", niche="esports"
    )

    results = read_health_log(db, tier="weekly")
    assert len(results) == 1
    assert results[0]["tier"] == "weekly"


# ---------------------------------------------------------------------------
# Plan 09-02: preflight checks (checks.py)
# ---------------------------------------------------------------------------


def test_preflight_memory_fail():
    """preflight_checks returns a fail result when available RAM < 500 MB."""
    import psutil
    from unittest.mock import patch

    mock_mem = MagicMock()
    mock_mem.available = 200 * 1024 * 1024  # 200 MB

    with patch("psutil.virtual_memory", return_value=mock_mem):
        from polymarket_analytics.health.checks import preflight_checks
        results = preflight_checks(db_path="/tmp")

    memory_check = next(r for r in results if r["name"] == "memory")
    assert memory_check["status"] == "fail"


def test_preflight_memory_pass():
    """preflight_checks returns pass when available RAM >= 500 MB."""
    import psutil
    from unittest.mock import patch

    mock_mem = MagicMock()
    mock_mem.available = 2 * 1024 ** 3  # 2 GB

    with patch("psutil.virtual_memory", return_value=mock_mem):
        from polymarket_analytics.health.checks import preflight_checks
        results = preflight_checks(db_path="/tmp")

    memory_check = next(r for r in results if r["name"] == "memory")
    assert memory_check["status"] == "pass"


def test_preflight_disk_fail():
    """preflight_checks returns a fail result when free disk < 10 GB."""
    from unittest.mock import patch
    import shutil

    mock_disk = MagicMock()
    mock_disk.free = 5 * 1024 ** 3  # 5 GB

    with patch("shutil.disk_usage", return_value=mock_disk):
        from polymarket_analytics.health.checks import preflight_checks
        results = preflight_checks(db_path="/tmp")

    disk_check = next(r for r in results if r["name"] == "disk")
    assert disk_check["status"] == "fail"


def test_preflight_disk_pass():
    """preflight_checks returns pass when free disk >= 10 GB."""
    from unittest.mock import patch
    import shutil

    mock_disk = MagicMock()
    mock_disk.free = 50 * 1024 ** 3  # 50 GB

    with patch("shutil.disk_usage", return_value=mock_disk):
        from polymarket_analytics.health.checks import preflight_checks
        results = preflight_checks(db_path="/tmp")

    disk_check = next(r for r in results if r["name"] == "disk")
    assert disk_check["status"] == "pass"


def test_staleness_warn():
    """check_lift_scores_freshness returns warn when scores are >5h old."""
    from datetime import datetime, timezone, timedelta

    db = sqlite_utils.Database(memory=True)
    db.execute("""
        CREATE TABLE lift_scores (
            trader_address TEXT,
            category TEXT,
            composite_score REAL,
            quintile INTEGER,
            computed_at TEXT
        )
    """)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    db.execute("INSERT INTO lift_scores (trader_address, category, computed_at) VALUES (?, ?, ?)",
               ["0xabc", "esports", old_ts])
    db.conn.commit()

    from polymarket_analytics.health.checks import check_lift_scores_freshness
    result = check_lift_scores_freshness(db, "esports")
    assert result["status"] == "warn"


def test_staleness_pass():
    """check_lift_scores_freshness returns pass when scores are fresh (<5h)."""
    from datetime import datetime, timezone, timedelta

    db = sqlite_utils.Database(memory=True)
    db.execute("""
        CREATE TABLE lift_scores (
            trader_address TEXT,
            category TEXT,
            composite_score REAL,
            quintile INTEGER,
            computed_at TEXT
        )
    """)
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    db.execute("INSERT INTO lift_scores (trader_address, category, computed_at) VALUES (?, ?, ?)",
               ["0xabc", "esports", recent_ts])
    db.conn.commit()

    from polymarket_analytics.health.checks import check_lift_scores_freshness
    result = check_lift_scores_freshness(db, "esports")
    assert result["status"] == "pass"


def test_staleness_never_computed():
    """check_lift_scores_freshness returns warn with 'never' message when table is empty."""
    db = sqlite_utils.Database(memory=True)
    db.execute("""
        CREATE TABLE lift_scores (
            trader_address TEXT,
            category TEXT,
            computed_at TEXT
        )
    """)
    db.conn.commit()

    from polymarket_analytics.health.checks import check_lift_scores_freshness
    result = check_lift_scores_freshness(db, "esports")
    assert result["status"] == "warn"
    assert "never" in result["message"].lower()


def test_preflight_fail_sends_alert():
    """health-check --tier cron exits 1 and sends alert when preflight fails."""
    from click.testing import CliRunner
    from unittest.mock import patch, MagicMock
    import sqlite_utils

    # Mock preflight_checks to return a memory failure
    fail_result = [{
        "name": "memory",
        "status": "fail",
        "value": "200 MB",
        "threshold": "500 MB",
        "message": "Available RAM: 200 MB (threshold: 500 MB)",
    }]
    pass_freshness = {
        "name": "lift_scores_freshness",
        "status": "pass",
        "value": "1.0h",
        "threshold": "5h",
        "message": "lift_scores are 1.0h old (threshold: 5h)",
    }

    with patch("polymarket_analytics.health.checks.preflight_checks", return_value=fail_result), \
         patch("polymarket_analytics.health.checks.check_lift_scores_freshness", return_value=pass_freshness), \
         patch("polymarket_analytics.health.notify.send_alert") as mock_alert, \
         patch("polymarket_analytics.db.schema.init_database") as mock_db:
        mock_db.return_value = sqlite_utils.Database(memory=True)
        # Ensure health_log table exists
        db = mock_db.return_value
        db.execute("""
            CREATE TABLE IF NOT EXISTS health_log (
                id TEXT PRIMARY KEY,
                tier TEXT,
                timestamp TEXT,
                status TEXT,
                checks TEXT,
                summary TEXT,
                niche TEXT
            )
        """)

        from polymarket_analytics.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--niche", "esports", "health-check", "--tier", "cron"])

    assert result.exit_code == 1
    assert mock_alert.called
    alert_title = mock_alert.call_args[0][0]
    assert "FAILED" in alert_title
    assert "PRE-FLIGHT FAILED" in result.output


def test_cron_check_all_pass():
    """health-check --tier cron exits 0 when all checks pass."""
    from click.testing import CliRunner
    from unittest.mock import patch
    import sqlite_utils

    pass_preflight = [
        {
            "name": "memory",
            "status": "pass",
            "value": "2048 MB",
            "threshold": "500 MB",
            "message": "Available RAM: 2048 MB (threshold: 500 MB)",
        },
        {
            "name": "disk",
            "status": "pass",
            "value": "50.0 GB",
            "threshold": "10 GB",
            "message": "Free disk: 50.0 GB (threshold: 10 GB)",
        },
    ]
    pass_freshness = {
        "name": "lift_scores_freshness",
        "status": "pass",
        "value": "1.0h",
        "threshold": "5h",
        "message": "lift_scores are 1.0h old (threshold: 5h)",
    }

    with patch("polymarket_analytics.health.checks.preflight_checks", return_value=pass_preflight), \
         patch("polymarket_analytics.health.checks.check_lift_scores_freshness", return_value=pass_freshness), \
         patch("polymarket_analytics.health.notify.send_alert") as mock_alert, \
         patch("polymarket_analytics.db.schema.init_database") as mock_db:
        db = sqlite_utils.Database(memory=True)
        db.execute("""
            CREATE TABLE IF NOT EXISTS health_log (
                id TEXT PRIMARY KEY,
                tier TEXT,
                timestamp TEXT,
                status TEXT,
                checks TEXT,
                summary TEXT,
                niche TEXT
            )
        """)
        mock_db.return_value = db

        from polymarket_analytics.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--niche", "esports", "health-check", "--tier", "cron"])

    assert result.exit_code == 0, f"Output: {result.output}"
    # Check health_log has one row
    rows = list(db.execute("SELECT status FROM health_log").fetchall())
    assert len(rows) == 1
    assert rows[0][0] == "pass"


# ---------------------------------------------------------------------------
# Plan 09-03 stubs (daily summaries)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Implemented in plan 09-03")
def test_daily_summary():
    pass


@pytest.mark.skip(reason="Implemented in plan 09-03")
def test_q5_diff():
    pass


@pytest.mark.skip(reason="Implemented in plan 09-03")
def test_quiet_canary():
    pass
