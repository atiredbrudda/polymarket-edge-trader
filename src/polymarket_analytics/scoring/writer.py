"""Database write operations for lift_scores table.

This module provides functions for upserting scoring results to the lift_scores table
with idempotent INSERT OR REPLACE pattern.
"""

import hashlib
from datetime import datetime, timezone

import pandas as pd
import sqlite_utils


def generate_lift_score_id(
    trader_address: str, niche_slug: str, window_end: str
) -> str:
    """Generate unique ID for a lift_scores row.

    Args:
        trader_address: Wallet address
        niche_slug: Niche category (e.g., 'esports')
        window_end: Window end date as ISO timestamp

    Returns:
        SHA256 hash (first 16 chars) of trader_address + niche_slug + window_end
    """
    key = f"{trader_address}+{niche_slug}+{window_end}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def write_lift_scores(
    db: sqlite_utils.Database,
    scores_df: pd.DataFrame,
    niche_slug: str,
    window_days: int,
    window_end: str,
) -> int:
    """Upsert scoring results to lift_scores table.

    Args:
        db: sqlite-utils Database instance
        scores_df: DataFrame with columns:
            - trader_address: wallet address
            - clv_raw, clv_zscore: CLV metrics
            - roi_raw, roi_zscore: ROI metrics
            - sharpe_raw, sharpe_zscore: Sharpe metrics
            - composite_score: combined z-score
            - quintile: quintile rank (1-5)
            - position_count: number of positions
            - total_pnl: total profit/loss
        niche_slug: Niche category (e.g., 'esports')
        window_days: Scoring window in days
        window_end: Window end timestamp (ISO format)

    Returns:
        Number of rows upserted

    Notes:
        - Generates id as SHA256 hash of trader_address + niche_slug + window_end
        - Calculates window_start = window_end - window_days
        - Uses INSERT OR REPLACE for idempotency
        - Sets computed_at to current ISO timestamp
    """
    # Calculate window_start from window_end
    from datetime import timedelta

    window_end_dt = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
    window_start_dt = window_end_dt - timedelta(days=window_days)
    window_start = window_start_dt.isoformat().replace("+00:00", "Z")

    computed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    upserted = 0
    for _, row in scores_df.iterrows():
        # Generate unique ID
        score_id = generate_lift_score_id(row["trader_address"], niche_slug, window_end)

        # Prepare record for upsert
        record = {
            "id": score_id,
            "trader_address": row["trader_address"],
            "category": niche_slug,
            "composite_score": float(row["composite_score"]),
            "clv_raw": float(row["clv_raw"]),
            "clv_zscore": float(row["clv_zscore"]),
            "roi_raw": float(row["roi_raw"]),
            "roi_zscore": float(row["roi_zscore"]),
            "sharpe_raw": float(row["sharpe_raw"]),
            "sharpe_zscore": float(row["sharpe_zscore"]),
            "quintile": int(row["quintile"]),
            "position_count": int(row["position_count"]),
            "total_pnl": float(row["total_pnl"]),
            "window_start": window_start,
            "window_end": window_end,
            "computed_at": computed_at,
        }

        # Upsert using id as primary key
        db["lift_scores"].upsert(record, pk="id", alter=True)
        upserted += 1

    return upserted
