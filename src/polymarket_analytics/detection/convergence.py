"""Convergence detection module for signal detection.

This module implements the core signal detection algorithm: finding markets where
≥2 Q5 (top quintile) traders converge on the same market with the same direction.

The detection uses SQL aggregation (GROUP BY market_id, direction) with HAVING
COUNT(DISTINCT trader_address) >= 2 to efficiently identify convergence signals.
"""

import click
import pandas as pd
import sqlite_utils


def detect_convergence(db: sqlite_utils.Database, niche_slug: str) -> pd.DataFrame:
    """Detect consensus signals from Q5 trader convergence.

    Executes SQL query to find markets where ≥2 Q5 traders have positions in the
    same direction (LONG or SHORT). Returns a DataFrame with convergence data.

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche category to scope detection (e.g., 'esports')

    Returns:
        pandas DataFrame with columns:
            - market_id: Market condition ID
            - direction: LONG or SHORT
            - q5_count: Number of Q5 traders converging
            - avg_score: Average composite score of Q5 traders
            - first_position_time: Earliest entry timestamp
            - last_position_time: Most recent trade timestamp
        Returns empty DataFrame if no convergence found or dependencies missing.

    Raises:
        click.ClickException: If required tables are missing or no Q5 traders exist

    Notes:
        - Filters lift_scores by quintile=5 AND category=niche_slug
        - Filters positions by resolved=0 AND size>0 (excludes FLAT positions)
        - Uses COUNT(DISTINCT trader_address) to avoid double-counting
        - LONG and SHORT directions produce separate signals
    """
    # Dependency assertions - fail loudly if prerequisites missing
    _assert_dependencies(db, niche_slug)

    # Convergence detection query
    # Pattern: GROUP BY market_id, direction with HAVING COUNT >= 2
    # Source: 06-RESEARCH.md Pattern 3, GUIDE.md hand-off rules
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

    # Execute query and return DataFrame
    # Empty DataFrame returned if no convergence found (no crash)
    return pd.read_sql_query(query, db.conn, params={"niche_slug": niche_slug})


def _assert_dependencies(db: sqlite_utils.Database, niche_slug: str) -> None:
    """Assert all dependencies exist before running convergence detection.

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche category to validate

    Raises:
        click.ClickException: With clear message if any dependency missing
    """
    # Assert lift_scores table exists
    if not db["lift_scores"].exists():
        raise click.ClickException(
            "lift_scores table does not exist. Run score command first."
        )

    # Assert positions table exists
    if not db["positions"].exists():
        raise click.ClickException(
            "positions table does not exist. Run build-positions command first."
        )

    # Assert lift_scores has Q5 traders for this niche
    q5_count = db.execute(
        """
        SELECT COUNT(*) FROM lift_scores
        WHERE quintile = 5 AND category = :niche_slug
        """,
        {"niche_slug": niche_slug},
    ).fetchone()[0]

    if q5_count == 0:
        raise click.ClickException(
            f"No Q5 (top quintile) traders found for niche '{niche_slug}'. "
            "Run score command to compute lift_scores first."
        )

    # Assert positions has unresolved positions with size > 0
    open_positions = db.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE resolved = 0 AND size > 0
        """
    ).fetchone()[0]

    if open_positions == 0:
        raise click.ClickException(
            "No open positions found (resolved=0 AND size>0). "
            "Run build-positions command to aggregate positions from trades."
        )
