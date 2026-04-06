"""Metrics calculation module for CLV, ROI, and Sharpe ratio.

Implements the three core scoring formulas from GUIDE.md §"Scoring Formula".
Each metric calculated per trader from position-level data using pandas
vectorized operations for efficiency.
"""

import pandas as pd


def calculate_clv(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate CLV (Closed-Loop Value) per trader.

    CLV = (resolution_price - entry_price) / entry_price

    Where resolution_price is:
    - 1.0 for YES outcome
    - 0.0 for NO outcome

    Args:
        positions_df: DataFrame with columns:
            - trader_address: wallet address
            - avg_entry_price: volume-weighted average entry price
            - outcome: 'YES' or 'NO'
            - direction: position direction (LONG, SHORT, FLAT)
            - avg_exit_price: volume-weighted average exit price (for FLAT positions)

    Returns:
        DataFrame with columns: [trader_address, clv_raw]
        where clv_raw is the mean CLV across all positions for that trader.

    References:
        GUIDE.md §"Scoring Formula" — CLV definition
        GUIDE.md §"Happy Path — Row-by-Row Trace" — example calculation
    """
    df = positions_df.copy()

    # Map outcome to resolution_price: YES -> 1.0, NO -> 0.0
    df["resolution_price"] = df["outcome"].map({"YES": 1.0, "NO": 0.0})

    # For FLAT positions, use avg_exit_price as resolution_price
    if "direction" in df.columns and "avg_exit_price" in df.columns:
        flat_mask = df["direction"] == "FLAT"
        if flat_mask.any():
            df.loc[flat_mask, "resolution_price"] = df.loc[flat_mask, "avg_exit_price"]

    # Drop rows where resolution_price is still NaN (edge case guard)
    df = df.dropna(subset=["resolution_price"])

    # CLV per position: (resolution_price - avg_entry_price) / avg_entry_price
    df["clv"] = (df["resolution_price"] - df["avg_entry_price"]) / df["avg_entry_price"]

    # Aggregate: mean CLV per trader
    trader_clv = df.groupby("trader_address")["clv"].mean().reset_index()
    trader_clv.columns = ["trader_address", "clv_raw"]

    return trader_clv


def calculate_roi(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate ROI (Return on Investment) per trader.

    ROI = total_pnl / total_capital_deployed

    Where:
    - total_pnl = sum of all position PnL for the trader
    - total_capital_deployed = sum of (size * avg_entry_price) for all positions

    Args:
        positions_df: DataFrame with columns:
            - trader_address: wallet address
            - pnl: profit/loss for the position
            - size: position size in tokens
            - avg_entry_price: volume-weighted average entry price

    Returns:
        DataFrame with columns: [trader_address, roi_raw, total_pnl]
        where roi_raw is guarded against division by zero (returns 0.0).

    References:
        GUIDE.md §"Scoring Formula" — ROI definition
    """
    df = positions_df.copy()

    # Capital deployed per position: size * avg_entry_price
    df["capital_deployed"] = df["size"] * df["avg_entry_price"]

    # Aggregate per trader: sum(pnl), sum(capital_deployed)
    trader_roi = (
        df.groupby("trader_address")
        .agg(
            total_pnl=("pnl", "sum"), total_capital_deployed=("capital_deployed", "sum")
        )
        .reset_index()
    )

    # ROI calculation with division guard
    def safe_roi(row: pd.Series) -> float:
        if row["total_capital_deployed"] > 0:
            return row["total_pnl"] / row["total_capital_deployed"]
        return 0.0

    trader_roi["roi_raw"] = trader_roi.apply(safe_roi, axis=1)

    return trader_roi[["trader_address", "roi_raw", "total_pnl"]]


def calculate_sharpe(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Sharpe ratio per trader.

    Sharpe = mean(trade_returns) / std(trade_returns)

    Where:
    - trade_return = pnl / capital_deployed for each position
    - Uses sample standard deviation (ddof=1) per statistics convention

    Edge cases handled:
    - Single position: returns 0.0 (not enough data for std)
    - Zero std (all returns identical): returns 0.0

    Args:
        positions_df: DataFrame with columns:
            - trader_address: wallet address
            - pnl: profit/loss for the position
            - size: position size in tokens
            - avg_entry_price: volume-weighted average entry price

    Returns:
        DataFrame with columns: [trader_address, sharpe_raw]

    References:
        GUIDE.md §"Scoring Formula" — Sharpe definition
        05-RESEARCH.md Pattern 4 — Sharpe calculation with sample std
    """
    df = positions_df.copy()

    # Capital deployed per position
    df["capital_deployed"] = df["size"] * df["avg_entry_price"]

    # Trade return per position with division guard
    def safe_return(row: pd.Series) -> float:
        if row["capital_deployed"] > 0:
            return row["pnl"] / row["capital_deployed"]
        return 0.0

    df["trade_return"] = df.apply(safe_return, axis=1)

    # Sharpe ratio calculation per trader
    def sharpe_ratio(returns: pd.Series) -> float:
        """Calculate Sharpe ratio from a series of returns.

        Uses sample std (ddof=1) per statistics convention.
        Returns 0.0 for single position or zero volatility.
        """
        import numpy as np

        if len(returns) < 2:
            return 0.0  # Not enough data for sample std

        mean_return = returns.mean()
        std_return = returns.std(ddof=1)  # Sample standard deviation

        # Check for zero or near-zero std (floating point tolerance)
        if np.isclose(std_return, 0.0) or pd.isna(std_return):
            return 0.0  # Zero volatility or NaN

        return mean_return / std_return

    # Group by trader and apply Sharpe calculation
    trader_sharpe = (
        df.groupby("trader_address")["trade_return"]
        .agg(sharpe_raw=sharpe_ratio)
        .reset_index()
    )

    return trader_sharpe


def calculate_all_metrics(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all three metrics (CLV, ROI, Sharpe) and merge.

    Convenience function that calls all three metric calculators
    and returns a single merged DataFrame.

    Args:
        positions_df: DataFrame with columns:
            - trader_address: wallet address
            - avg_entry_price: volume-weighted average entry price
            - pnl: profit/loss for the position
            - size: position size in tokens
            - outcome: 'YES' or 'NO'

    Returns:
        Merged DataFrame with columns:
            - trader_address
            - clv_raw
            - roi_raw
            - sharpe_raw
            - position_count

    References:
        GUIDE.md §"Scoring Formula" — all three formulas
    """
    # Calculate each metric
    clv_df = calculate_clv(positions_df)
    roi_df = calculate_roi(positions_df)
    sharpe_df = calculate_sharpe(positions_df)

    # Merge on trader_address
    metrics = clv_df.merge(roi_df, on="trader_address", how="outer")
    metrics = metrics.merge(sharpe_df, on="trader_address", how="outer")

    # Add position count per trader
    position_counts = positions_df.groupby("trader_address").size().reset_index()
    position_counts.columns = ["trader_address", "position_count"]
    metrics = metrics.merge(position_counts, on="trader_address", how="outer")

    return metrics
