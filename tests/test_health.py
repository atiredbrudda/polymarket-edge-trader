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
# Plan 09-02 stubs (preflight checks)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Implemented in plan 09-02")
def test_preflight_memory_fail():
    pass


@pytest.mark.skip(reason="Implemented in plan 09-02")
def test_preflight_disk_fail():
    pass


@pytest.mark.skip(reason="Implemented in plan 09-02")
def test_staleness_warn():
    pass


@pytest.mark.skip(reason="Implemented in plan 09-02")
def test_preflight_fail_sends_alert():
    pass


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
