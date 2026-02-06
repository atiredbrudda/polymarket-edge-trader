"""
Timeframe window calculation and position filtering.

Pure functions for time-based filtering. All timestamps are UTC, timezone-naive
(per existing codebase pattern).

Design principles:
- Pure functions, no state
- Duck-typed position input (works with any object having last_trade_timestamp)
- Accept `now` parameter for deterministic testing
"""

from datetime import datetime, timedelta
from typing import Any


# Timeframe window definitions
TIMEFRAME_WINDOWS = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "all": None,
}


def get_timeframe_bounds(
    window_key: str,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime]:
    """
    Get start and end datetime bounds for a timeframe window.

    Args:
        window_key: Window identifier ("7d", "30d", "90d", "all")
        now: End time (defaults to utcnow if not provided)

    Returns:
        Tuple of (start, end) where:
        - end is the current time
        - start is end minus the window duration
        - start is None for "all" window (no lower bound)

    Raises:
        ValueError: If window_key is not in TIMEFRAME_WINDOWS

    Examples:
        >>> get_timeframe_bounds("7d", datetime(2026, 2, 6, 14, 0, 0))
        (datetime(2026, 1, 30, 14, 0, 0), datetime(2026, 2, 6, 14, 0, 0))

        >>> get_timeframe_bounds("all", datetime(2026, 2, 6, 14, 0, 0))
        (None, datetime(2026, 2, 6, 14, 0, 0))
    """
    if window_key not in TIMEFRAME_WINDOWS:
        raise ValueError(f"Unknown window key: {window_key}")

    if now is None:
        now = datetime.utcnow()

    window_duration = TIMEFRAME_WINDOWS[window_key]

    if window_duration is None:
        # "all" window - no lower bound
        return (None, now)

    start = now - window_duration
    return (start, now)


def filter_positions_by_window(
    positions: list[Any],
    window_key: str,
    now: datetime | None = None,
) -> list[Any]:
    """
    Filter positions by timeframe window based on last_trade_timestamp.

    Duck-typed positions with last_trade_timestamp attribute.

    Args:
        positions: List of position-like objects with last_trade_timestamp
        window_key: Window identifier ("7d", "30d", "90d", "all")
        now: Current time for window calculation (defaults to utcnow)

    Returns:
        Filtered list of positions where last_trade_timestamp falls within window bounds.
        For "all" window, returns all positions (including those with None timestamp).
        For time-based windows, excludes positions with None timestamp.

    Examples:
        >>> positions = [
        ...     MockPosition("m1", datetime(2026, 2, 3)),  # 3 days ago
        ...     MockPosition("m2", datetime(2026, 1, 25)), # 12 days ago
        ... ]
        >>> filtered = filter_positions_by_window(positions, "7d", datetime(2026, 2, 6))
        >>> len(filtered)
        1
    """
    if not positions:
        return []

    start, end = get_timeframe_bounds(window_key, now=now)

    # "all" window - return everything
    if start is None:
        return positions

    # Time-based window - filter by timestamp
    filtered = []
    for position in positions:
        if position.last_trade_timestamp is None:
            # Exclude positions with no timestamp for time-based windows
            continue

        if start <= position.last_trade_timestamp <= end:
            filtered.append(position)

    return filtered


def get_all_timeframe_snapshots(
    positions: list[Any],
    now: datetime | None = None,
) -> dict[str, list[Any]]:
    """
    Generate filtered position lists for all timeframe windows.

    Convenience function that applies filter_positions_by_window for each
    timeframe window.

    Args:
        positions: List of position-like objects with last_trade_timestamp
        now: Current time for window calculation (defaults to utcnow)

    Returns:
        Dictionary mapping window keys to filtered position lists:
        {"7d": [...], "30d": [...], "90d": [...], "all": [...]}

    Examples:
        >>> snapshots = get_all_timeframe_snapshots(positions)
        >>> snapshots["7d"]  # Positions from last 7 days
        >>> snapshots["all"]  # All positions
    """
    return {
        window_key: filter_positions_by_window(positions, window_key, now=now)
        for window_key in TIMEFRAME_WINDOWS.keys()
    }
