"""Database connection factory with WAL mode and foreign key enforcement."""

from pathlib import Path

import sqlite_utils


def get_db(db_path: Path) -> sqlite_utils.Database:
    """Create database connection with WAL mode and foreign key enforcement.

    Args:
        db_path: Path to SQLite database file

    Returns:
        sqlite_utils.Database instance with WAL mode enabled and FK enforcement

    WAL mode is enabled at connection time and persists in the database file.
    Foreign keys are enforced on every connection via PRAGMA.
    """
    db = sqlite_utils.Database(db_path)
    db.enable_wal()  # Enable WAL mode for read concurrency (SCHM-02)
    db.execute("PRAGMA busy_timeout = 30000")  # Wait up to 30s on lock contention
    db.execute("PRAGMA foreign_keys = ON")  # Enforce foreign key constraints
    # 10000 pages ≈ 40MB WAL before checkpoint — 10× fewer checkpoint lock spikes
    # on the 14.6 GB DB (default 1000 pages = 3.9MB churns far too often).
    db.execute("PRAGMA wal_autocheckpoint = 10000")
    # 200MB page cache — default -2000 (2MB) hits disk on every monitor SELECT.
    db.execute("PRAGMA cache_size = -200000")
    return db
