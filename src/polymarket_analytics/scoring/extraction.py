"""Data extraction module for scoring window queries.

Extracts resolved positions within a configurable rolling window (30 days default)
with all fields needed for CLV, ROI, and Sharpe calculation.
"""

import pandas as pd
import sqlite_utils


def extract_resolved_positions(
    db: sqlite_utils.Database, niche_slug: str, window_days: int = 30
) -> pd.DataFrame:
    """Extract resolved positions within the scoring window.

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche to filter by (e.g., 'esports')
        window_days: Rolling window in days (default: 30)

    Returns:
        pandas DataFrame with resolved position data including:
        - trader_address, market_id, direction, size
        - avg_entry_price, pnl, trade_count
        - outcome, end_date

        Returns empty DataFrame if no results (does not crash).

    SQL query:
        - JOINs positions + markets on market_id = condition_id
        - WHERE resolved = 1 AND niche_slug = :niche_slug
        - AND last_trade_timestamp >= datetime('now', '-' || :window_days || ' days')
        - Uses last_trade_timestamp for window filtering (not entry_timestamp)
          per GUIDE.md — captures positions actively traded late in window

    Example:
        >>> from polymarket_analytics.db.schema import init_database
        >>> db = init_database(db_path)
        >>> df = extract_resolved_positions(db, 'esports', window_days=30)
        >>> if len(df) > 0:
        ...     print(f"Found {len(df)} resolved positions")
    """
    query = """
        SELECT
            p.trader_address,
            p.market_id,
            p.direction,
            p.size,
            p.avg_entry_price,
            p.avg_exit_price,
            p.pnl,
            p.trade_count,
            m.outcome,
            m.end_date
        FROM positions p
        JOIN markets m ON m.condition_id = p.market_id
        WHERE p.resolved = 1
          AND m.niche_slug = :niche_slug
          AND p.last_trade_timestamp >= datetime('now', '-' || :window_days || ' days')
        ORDER BY p.trader_address, m.end_date
    """

    try:
        df = pd.read_sql_query(
            query,
            db.conn,
            params={"niche_slug": niche_slug, "window_days": window_days},
        )
        return df
    except Exception:
        # Return empty DataFrame with expected schema on any error
        return pd.DataFrame(
            columns=[
                "trader_address",
                "market_id",
                "direction",
                "size",
                "avg_entry_price",
                "avg_exit_price",
                "pnl",
                "trade_count",
                "outcome",
                "end_date",
            ]
        )
