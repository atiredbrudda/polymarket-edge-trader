"""Signal writer module for persisting detection results.

This module provides functions for upserting detected signals to the signals table
with proper first_seen timestamp preservation and alerted flag reset.

Key behaviors:
- upsert_signal: Insert new signal or update existing (preserving first_seen)
- upsert_signals_batch: Process DataFrame with Rich progress bar
- avg_score stored with NUMERIC(10,6) precision via raw SQL
"""

import hashlib
from datetime import datetime, timezone

import pandas as pd
import sqlite_utils
from rich.console import Console

console = Console()


def upsert_signal(
    db: sqlite_utils.Database,
    market_id: str,
    direction: str,
    q5_count: int,
    avg_score: float,
    first_seen: str,
    last_updated: str,
) -> str:
    """Upsert a signal record to the signals table.

    Uses INSERT OR REPLACE pattern with unique index on (market_id, direction).
    Preserves first_seen timestamp on updates, resets alerted=0 for re-alerting.

    Args:
        db: sqlite-utils Database instance
        market_id: Market condition ID
        direction: LONG or SHORT
        q5_count: Number of Q5 traders converging
        avg_score: Average composite score of Q5 traders
        first_seen: Timestamp of first detection (ISO format)
        last_updated: Timestamp of this detection (ISO format)

    Returns:
        Signal ID (existing or newly generated)

    Notes:
        - Uses raw SQL for NUMERIC(10,6) avg_score column (per GUIDE.md)
        - Signal ID format: sig_{market_id[:8]}_{direction}_{timestamp}
        - On update: preserves first_seen, resets alerted=0
    """
    # Check for existing signal with same (market_id, direction)
    existing = db.execute(
        """
        SELECT id, first_seen FROM signals
        WHERE market_id = :market_id AND direction = :direction
        """,
        {"market_id": market_id, "direction": direction},
    ).fetchone()

    if existing:
        # Update existing signal, preserve first_seen
        signal_id = existing["id"]
        # Use raw SQL for NUMERIC(10,6) avg_score precision
        db.execute(
            """
            UPDATE signals SET
                q5_count = :q5_count,
                avg_score = :avg_score,
                last_updated = :last_updated,
                alerted = 0
            WHERE id = :id
            """,
            {
                "id": signal_id,
                "q5_count": q5_count,
                "avg_score": avg_score,
                "last_updated": last_updated,
            },
        )
    else:
        # Insert new signal with stable ID
        # ID format: sig_{market_id[:8]}_{direction}_{timestamp}
        timestamp = int(datetime.now().timestamp())
        signal_id = f"sig_{market_id[:8]}_{direction}_{timestamp}"

        # Use raw SQL for NUMERIC(10,6) avg_score precision
        db.execute(
            """
            INSERT INTO signals (id, market_id, direction, q5_count, avg_score, first_seen, last_updated, alerted)
            VALUES (:id, :market_id, :direction, :q5_count, :avg_score, :first_seen, :last_updated, 0)
            """,
            {
                "id": signal_id,
                "market_id": market_id,
                "direction": direction,
                "q5_count": q5_count,
                "avg_score": avg_score,
                "first_seen": first_seen,
                "last_updated": last_updated,
                "alerted": 0,
            },
        )

    return signal_id


def generate_signal_id(market_id: str, direction: str, first_seen: str) -> str:
    """Generate unique ID for a signal record.

    Args:
        market_id: Market condition ID
        direction: LONG or SHORT
        first_seen: Timestamp of first detection (ISO format)

    Returns:
        Stable ID based on market_id + direction + first_seen
    """
    key = f"{market_id}+{direction}+{first_seen}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def upsert_signals_batch(
    db: sqlite_utils.Database, convergence_df: pd.DataFrame, niche_slug: str
) -> int:
    """Upsert all detected signals from convergence DataFrame.

    Iterates over convergence results, upserting each signal with progress bar.
    Skips rows with invalid data (None values).

    Args:
        db: sqlite-utils Database instance
        convergence_df: DataFrame from detect_convergence with columns:
            - market_id: Market condition ID
            - direction: LONG or SHORT
            - q5_count: Number of Q5 traders converging
            - avg_score: Average composite score
            - first_position_time: Earliest entry timestamp
            - last_position_time: Most recent trade timestamp
        niche_slug: Niche category (for logging)

    Returns:
        Number of signals inserted/updated

    Notes:
        - Uses Rich progress bar for iteration (per UX-02 requirement)
        - now timestamp used for last_updated on all signals
        - Skips rows with None/NaN values in critical columns
    """
    if convergence_df.empty:
        console.print("[yellow]No signals to upsert.[/yellow]")
        return 0

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    upserted = 0
    total = len(convergence_df)

    with console.status(f"[bold green]Upserting {total} signal(s)...", spinner="dots"):
        for _, row in convergence_df.iterrows():
            # Skip rows with invalid data
            if pd.isna(row["market_id"]) or pd.isna(row["direction"]):
                continue

            upsert_signal(
                db=db,
                market_id=str(row["market_id"]),
                direction=str(row["direction"]),
                q5_count=int(row["q5_count"]),
                avg_score=float(row["avg_score"])
                if not pd.isna(row["avg_score"])
                else 0.0,
                first_seen=str(row["first_position_time"]),
                last_updated=now,
            )
            upserted += 1

    return upserted
