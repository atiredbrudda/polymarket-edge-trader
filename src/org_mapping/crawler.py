"""Crawler cursor utilities for analyze command.

Persists batch processing state to allow resuming across sessions.
"""

import json
from pathlib import Path

CURSOR_FILE = Path(".planning/analyze_cursor.json")


def load_cursor() -> dict | None:
    """Load cursor state from disk.

    Returns:
        dict with keys last_trader, last_entity, last_game, processed
        or None if file doesn't exist.
    """
    if not CURSOR_FILE.exists():
        return None

    with open(CURSOR_FILE, "r") as f:
        return json.load(f)


def save_cursor(
    last_trader: str, last_entity: str, last_game: str | None, processed: int
) -> None:
    """Save cursor state to disk.

    Args:
        last_trader: Last trader address processed
        last_entity: Last entity type processed (team/tournament/game)
        last_game: Last game dimension processed (or None)
        processed: Number of entity rows processed
    """
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "last_trader": last_trader,
        "last_entity": last_entity,
        "last_game": last_game,
        "processed": processed,
    }

    with open(CURSOR_FILE, "w") as f:
        json.dump(data, f)


def clear_cursor() -> None:
    """Remove cursor file if it exists."""
    CURSOR_FILE.unlink(missing_ok=True)
