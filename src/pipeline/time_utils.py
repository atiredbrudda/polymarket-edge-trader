"""Time parsing utilities for CLI duration options."""

from datetime import datetime, timedelta, UTC

from pytimeparse import parse as parse_duration


def parse_closing_within(duration_str: str) -> datetime:
    """Parse duration string into future datetime threshold.

    Converts human-readable duration (e.g., "48h", "2d", "30m") into
    a UTC datetime representing now + duration.

    Args:
        duration_str: Duration string (e.g., "48h", "24h", "2d", "1w")

    Returns:
        Future UTC datetime (now + duration)

    Raises:
        ValueError: If duration_str cannot be parsed
    """
    if not duration_str:
        raise ValueError("Invalid time format: ''. Examples: 48h, 24h, 2d, 1w")

    seconds = parse_duration(duration_str)
    if seconds is None:
        raise ValueError(
            f"Invalid time format: '{duration_str}'. Examples: 48h, 24h, 2d, 1w"
        )

    return datetime.now(UTC) + timedelta(seconds=seconds)
