"""
Tests for timeframe window calculation and position filtering.
"""

import pytest
from datetime import datetime, timedelta
from dataclasses import dataclass


# Mock position object for testing
@dataclass
class MockPosition:
    market_id: str
    last_trade_timestamp: datetime | None


def test_timeframe_windows_constant():
    """Test TIMEFRAME_WINDOWS constant has correct keys and values."""
    from src.evaluation.timeframes import TIMEFRAME_WINDOWS

    assert "7d" in TIMEFRAME_WINDOWS
    assert "30d" in TIMEFRAME_WINDOWS
    assert "90d" in TIMEFRAME_WINDOWS
    assert "all" in TIMEFRAME_WINDOWS

    assert TIMEFRAME_WINDOWS["7d"] == timedelta(days=7)
    assert TIMEFRAME_WINDOWS["30d"] == timedelta(days=30)
    assert TIMEFRAME_WINDOWS["90d"] == timedelta(days=90)
    assert TIMEFRAME_WINDOWS["all"] is None


def test_get_timeframe_bounds_7d():
    """Test get_timeframe_bounds for 7 day window."""
    from src.evaluation.timeframes import get_timeframe_bounds

    now = datetime(2026, 2, 6, 14, 0, 0)
    start, end = get_timeframe_bounds("7d", now=now)

    assert end == now
    assert start == datetime(2026, 1, 30, 14, 0, 0)  # 7 days before


def test_get_timeframe_bounds_30d():
    """Test get_timeframe_bounds for 30 day window."""
    from src.evaluation.timeframes import get_timeframe_bounds

    now = datetime(2026, 2, 6, 14, 0, 0)
    start, end = get_timeframe_bounds("30d", now=now)

    assert end == now
    assert start == datetime(2026, 1, 7, 14, 0, 0)  # 30 days before


def test_get_timeframe_bounds_90d():
    """Test get_timeframe_bounds for 90 day window."""
    from src.evaluation.timeframes import get_timeframe_bounds

    now = datetime(2026, 2, 6, 14, 0, 0)
    start, end = get_timeframe_bounds("90d", now=now)

    assert end == now
    assert start == datetime(2025, 11, 8, 14, 0, 0)  # 90 days before


def test_get_timeframe_bounds_all():
    """Test get_timeframe_bounds for all-time window."""
    from src.evaluation.timeframes import get_timeframe_bounds

    now = datetime(2026, 2, 6, 14, 0, 0)
    start, end = get_timeframe_bounds("all", now=now)

    assert end == now
    assert start is None  # No lower bound


def test_get_timeframe_bounds_invalid_window():
    """Test get_timeframe_bounds raises ValueError for unknown window."""
    from src.evaluation.timeframes import get_timeframe_bounds

    with pytest.raises(ValueError, match="Unknown window"):
        get_timeframe_bounds("invalid")


def test_get_timeframe_bounds_default_now():
    """Test get_timeframe_bounds uses utcnow when now not provided."""
    from src.evaluation.timeframes import get_timeframe_bounds

    before = datetime.utcnow()
    start, end = get_timeframe_bounds("7d")
    after = datetime.utcnow()

    # End should be approximately now (within a few seconds)
    assert before <= end <= after


def test_filter_positions_by_window_empty_list():
    """Test filter_positions_by_window with empty list."""
    from src.evaluation.timeframes import filter_positions_by_window

    result = filter_positions_by_window([], "7d")
    assert result == []


def test_filter_positions_by_window_7d():
    """Test filter_positions_by_window filters correctly for 7d window."""
    from src.evaluation.timeframes import filter_positions_by_window

    now = datetime(2026, 2, 6, 14, 0, 0)

    positions = [
        MockPosition("market1", datetime(2026, 2, 3, 14, 0, 0)),  # 3 days ago - INCLUDE
        MockPosition("market2", datetime(2026, 1, 25, 14, 0, 0)),  # 12 days ago - EXCLUDE
        MockPosition("market3", datetime(2026, 2, 5, 14, 0, 0)),  # 1 day ago - INCLUDE
    ]

    result = filter_positions_by_window(positions, "7d", now=now)

    assert len(result) == 2
    assert result[0].market_id == "market1"
    assert result[1].market_id == "market3"


def test_filter_positions_by_window_boundary():
    """Test filter_positions_by_window at exact boundary."""
    from src.evaluation.timeframes import filter_positions_by_window

    now = datetime(2026, 2, 6, 14, 0, 0)
    exactly_7d_ago = datetime(2026, 1, 30, 14, 0, 0)

    positions = [
        MockPosition("market1", exactly_7d_ago),  # Exactly at boundary - INCLUDE
        MockPosition("market2", exactly_7d_ago - timedelta(seconds=1)),  # Just before - EXCLUDE
    ]

    result = filter_positions_by_window(positions, "7d", now=now)

    assert len(result) == 1
    assert result[0].market_id == "market1"


def test_filter_positions_by_window_all():
    """Test filter_positions_by_window with 'all' returns all positions."""
    from src.evaluation.timeframes import filter_positions_by_window

    now = datetime(2026, 2, 6, 14, 0, 0)

    positions = [
        MockPosition("market1", datetime(2026, 2, 3, 14, 0, 0)),
        MockPosition("market2", datetime(2020, 1, 1, 14, 0, 0)),  # Very old
        MockPosition("market3", datetime(2026, 2, 5, 14, 0, 0)),
    ]

    result = filter_positions_by_window(positions, "all", now=now)

    assert len(result) == 3
    assert result == positions


def test_filter_positions_by_window_none_timestamp():
    """Test filter_positions_by_window excludes positions with None timestamp for time-based windows."""
    from src.evaluation.timeframes import filter_positions_by_window

    now = datetime(2026, 2, 6, 14, 0, 0)

    positions = [
        MockPosition("market1", datetime(2026, 2, 3, 14, 0, 0)),  # INCLUDE
        MockPosition("market2", None),  # EXCLUDE for 7d
        MockPosition("market3", datetime(2026, 2, 5, 14, 0, 0)),  # INCLUDE
    ]

    result = filter_positions_by_window(positions, "7d", now=now)

    assert len(result) == 2
    assert all(p.last_trade_timestamp is not None for p in result)


def test_filter_positions_by_window_none_timestamp_all():
    """Test filter_positions_by_window includes positions with None timestamp for 'all' window."""
    from src.evaluation.timeframes import filter_positions_by_window

    now = datetime(2026, 2, 6, 14, 0, 0)

    positions = [
        MockPosition("market1", datetime(2026, 2, 3, 14, 0, 0)),
        MockPosition("market2", None),  # INCLUDE for 'all'
        MockPosition("market3", datetime(2026, 2, 5, 14, 0, 0)),
    ]

    result = filter_positions_by_window(positions, "all", now=now)

    assert len(result) == 3
    assert result == positions


def test_get_all_timeframe_snapshots():
    """Test get_all_timeframe_snapshots returns all windows."""
    from src.evaluation.timeframes import get_all_timeframe_snapshots

    now = datetime(2026, 2, 6, 14, 0, 0)

    positions = [
        MockPosition("market1", datetime(2026, 2, 3, 14, 0, 0)),  # 3d ago - in 7d, 30d, 90d, all
        MockPosition("market2", datetime(2026, 1, 25, 14, 0, 0)),  # 12d ago - in 30d, 90d, all
        MockPosition("market3", datetime(2025, 12, 1, 14, 0, 0)),  # 67d ago - in 90d, all
        MockPosition("market4", datetime(2025, 10, 1, 14, 0, 0)),  # 128d ago - in all only
    ]

    result = get_all_timeframe_snapshots(positions, now=now)

    assert set(result.keys()) == {"7d", "30d", "90d", "all"}

    assert len(result["7d"]) == 1  # market1
    assert len(result["30d"]) == 2  # market1, market2
    assert len(result["90d"]) == 3  # market1, market2, market3
    assert len(result["all"]) == 4  # all markets


def test_get_all_timeframe_snapshots_empty():
    """Test get_all_timeframe_snapshots with empty list."""
    from src.evaluation.timeframes import get_all_timeframe_snapshots

    result = get_all_timeframe_snapshots([])

    assert set(result.keys()) == {"7d", "30d", "90d", "all"}
    assert all(len(v) == 0 for v in result.values())
