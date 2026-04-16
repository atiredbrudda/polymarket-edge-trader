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
            - clv_dominant_count: Count of Q5 traders with clv_zscore > 0
            - avg_entry_price: Average entry price across converging traders' positions
            - min_entry_price: Minimum entry price across converging traders' positions
            - tier: WATCH / CONSIDER / ACT based on q5_count thresholds
        Returns empty DataFrame if no convergence found or dependencies missing.

    Raises:
        click.ClickException: If required tables are missing

    Notes:
        - Returns empty DataFrame if no Q5 traders or no convergence found (no crash)
        - Returns empty DataFrame if no open positions exist (graceful handling)

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
    # CRITICAL: Filter to latest scoring run via MAX(computed_at) to avoid ghost signals
    # from stale Q5 records (each score run appends new lift_scores rows)
    query = """
        SELECT
            p.market_id,
            p.direction,
            m.event_slug,
            COUNT(DISTINCT p.trader_address) as q5_count,
            AVG(ls.composite_score) as avg_score,
            MIN(p.entry_timestamp) as first_position_time,
            MAX(p.last_trade_timestamp) as last_position_time,
            COUNT(CASE WHEN ls.clv_zscore > 0 THEN 1 END) as clv_dominant_count,
            AVG(p.avg_entry_price) as avg_entry_price,
            MIN(p.avg_entry_price) as min_entry_price
        FROM positions p
        JOIN lift_scores ls ON ls.trader_address = p.trader_address
        JOIN markets m ON m.condition_id = p.market_id
        WHERE p.resolved = 0
          AND COALESCE(p.data_incomplete, 0) = 0
          AND ls.quintile = 5
          AND ls.category = :niche_slug
          AND ls.computed_at = (
              SELECT MAX(computed_at) FROM lift_scores WHERE category = :niche_slug
          )
          AND p.size > 0
          AND (m.end_date IS NULL OR datetime(m.end_date) > datetime('now'))
        GROUP BY p.market_id, p.direction
        HAVING COUNT(DISTINCT p.trader_address) >= 2
    """

    # Execute query and return DataFrame
    # Empty DataFrame returned if no convergence found (no crash)
    df = pd.read_sql_query(query, db.conn, params={"niche_slug": niche_slug})

    if df.empty:
        return df

    # Post-processing: correlated signal detection (Fix 3)
    df = _apply_opposing_direction_cancellation(df)
    df = _apply_event_grouping(df)

    return df


def _apply_opposing_direction_cancellation(df: pd.DataFrame) -> pd.DataFrame:
    """Layer 1: Cancel opposing Q5 traders on the same market.

    When Q5 traders are on both LONG and SHORT sides of the same market,
    compute net_q5_count = |LONG_count - SHORT_count|. Re-tier based on net.
    """
    # Build a map of market_id -> {direction: q5_count}
    market_directions = df.groupby("market_id")["direction"].nunique()
    contested_markets = set(market_directions[market_directions > 1].index)

    net_counts = []
    for _, row in df.iterrows():
        if row["market_id"] in contested_markets:
            # Get the opposing side's count
            same_market = df[df["market_id"] == row["market_id"]]
            opposing = same_market[same_market["direction"] != row["direction"]]
            opposing_count = int(opposing["q5_count"].iloc[0]) if len(opposing) > 0 else 0
            net = abs(int(row["q5_count"]) - opposing_count)
            net_counts.append(net)
        else:
            # No opposition — net equals raw count
            net_counts.append(int(row["q5_count"]))

    df["net_q5_count"] = net_counts

    # Re-tier based on net_q5_count instead of raw q5_count
    df["tier"] = df["net_q5_count"].apply(_compute_tier)

    return df


def _apply_event_grouping(df: pd.DataFrame) -> pd.DataFrame:
    """Layer 2: Flag correlated signals sharing the same event_slug.

    Counts how many signals share each event_slug so the bridge script
    can treat them as one bet for sizing purposes.
    """
    # Count signals per event_slug (only where event_slug is not null)
    has_event = df["event_slug"].notna()
    df["event_group_size"] = 1
    if has_event.any():
        event_counts = df.loc[has_event].groupby("event_slug")["market_id"].transform("count")
        df.loc[has_event, "event_group_size"] = event_counts.astype(int)

    return df


def _compute_tier(net_q5_count: int) -> str:
    """Compute signal tier from net Q5 count.

    Thresholds set 2026-04-16 per consensus rebuild (see wiki: Consensus Signal).
    Per-trade ROI is flat from min=2 through 10 (~65-70%), so the threshold is
    about filtering noise, not chasing higher edge. Revisit when Q5 panel >= 1000.
    """
    if net_q5_count >= 5:
        return "ACT"
    elif net_q5_count >= 3:
        return "CONSIDER"
    else:
        return "WATCH"


def _assert_dependencies(db: sqlite_utils.Database, niche_slug: str) -> None:
    """Assert all dependencies exist before running convergence detection.

    Only validates table existence, not data presence. Returns gracefully
    if tables exist but are empty (query will return empty DataFrame).

    Args:
        db: sqlite-utils Database instance
        niche_slug: Niche category to validate

    Raises:
        click.ClickException: With clear message if any required table missing
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
