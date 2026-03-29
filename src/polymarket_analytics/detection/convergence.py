"""Convergence detection for Q5 trader positions.

This module queries lift_scores for Q5 traders, joins with open positions,
and uses SQL GROUP BY with HAVING COUNT >= 2 to detect convergence.
"""

import pandas as pd
import sqlite_utils


def detect_convergence(db: sqlite_utils.Database, niche_slug: str) -> pd.DataFrame:
    """Detect consensus signals where >= 2 Q5 traders converge on same market+direction.

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche category to scope detection (e.g., 'esports')

    Returns:
        DataFrame with columns:
            - market_id: Market condition ID
            - direction: LONG or SHORT
            - q5_count: Number of Q5 traders converging
            - avg_score: Average composite score of Q5 traders
            - first_position_time: Earliest entry timestamp
            - last_position_time: Most recent trade timestamp

    Notes:
        - Filters lift_scores by category = niche_slug AND quintile = 5
        - Filters positions by resolved = 0 AND size > 0 (excludes FLAT)
        - Uses COUNT(DISTINCT trader_address) to avoid double-counting
        - GROUP BY market_id, direction (LONG and SHORT are separate signals)
        - HAVING COUNT >= 2 enforces minimum convergence threshold
    """
    query = """
        SELECT
            p.market_id,
            p.direction,
            COUNT(DISTINCT p.trader_address) as q5_count,
            AVG(ls.composite_score) as avg_score,
            MIN(p.entry_timestamp) as first_position_time,
            MAX(p.last_trade_timestamp) as last_position_time
        FROM positions p
        JOIN lift_scores ls ON ls.trader_address = p.trader_address
        WHERE p.resolved = 0
          AND ls.quintile = 5
          AND ls.category = :niche_slug
          AND p.size > 0
        GROUP BY p.market_id, p.direction
        HAVING COUNT(DISTINCT p.trader_address) >= 2
    """

    df = pd.read_sql_query(query, db.conn, params={"niche_slug": niche_slug})
    return df
