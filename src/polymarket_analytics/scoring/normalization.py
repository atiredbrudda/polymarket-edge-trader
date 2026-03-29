"""Z-score normalization and quintile assignment for trader scoring.

This module provides functions for:
- Z-score normalization of raw metrics (CLV, ROI, Sharpe)
- Quintile assignment via pd.qcut with tied-score handling
- Composite score computation combining all z-scores
"""

import numpy as np
import pandas as pd


def zscore_normalize(metrics_df: pd.DataFrame, column: str) -> pd.Series:
    """Compute z-score for a metric column.

    z = (value - mean) / std
    - Uses sample std (ddof=1) for unbiased estimate
    - Returns 0 for traders when std == 0 (all traders have same value)
    - Returns 0 for single-value inputs (std undefined)

    Args:
        metrics_df: DataFrame containing the column to normalize
        column: Name of the column to compute z-scores for

    Returns:
        Series with z-scores, same index as input
    """
    values = metrics_df[column]
    mean_val = values.mean()
    std_val = values.std(ddof=1)  # Sample standard deviation

    # Handle zero std or NaN (all traders identical or single value)
    if std_val == 0 or np.isnan(std_val):
        return pd.Series(0.0, index=metrics_df.index)

    return (values - mean_val) / std_val


def assign_quintiles(metrics_df: pd.DataFrame) -> pd.Series:
    """Assign quintile ranks based on composite score.

    Uses pd.qcut with duplicates='drop' to handle tied scores.
    Quintile 5 = top 20% (smart money), Quintile 1 = bottom 20%

    Args:
        metrics_df: DataFrame containing 'composite_score' column

    Returns:
        Series with quintile assignments (1-5)
    """
    try:
        quintiles = pd.qcut(
            metrics_df["composite_score"],
            q=5,
            labels=[1, 2, 3, 4, 5],
            duplicates="drop",  # Handle tied scores by dropping duplicate bins
        ).astype(int)
        return quintiles
    except ValueError as e:
        # Fallback: if all scores are identical, assign middle quintile
        if "Bin edges must be unique" in str(e):
            return pd.Series(3, index=metrics_df.index)
        else:
            raise


def compute_normalized_scores(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """Compute z-scores, composite score, and quintiles for all traders.

    Takes a DataFrame with raw metrics and adds:
    - clv_zscore: Z-score normalized CLV
    - roi_zscore: Z-score normalized ROI
    - sharpe_zscore: Z-score normalized Sharpe
    - composite_score: Sum of all three z-scores
    - quintile: Quintile assignment (1-5)

    Args:
        metrics_df: DataFrame with columns: clv_raw, roi_raw, sharpe_raw

    Returns:
        DataFrame with all z-scores, composite_score, and quintile added
    """
    # Create a copy to avoid modifying the original
    result = metrics_df.copy()

    # Compute z-scores for each metric
    result["clv_zscore"] = zscore_normalize(result, "clv_raw")
    result["roi_zscore"] = zscore_normalize(result, "roi_raw")
    result["sharpe_zscore"] = zscore_normalize(result, "sharpe_raw")

    # Compute composite score = sum of z-scores
    result["composite_score"] = (
        result["clv_zscore"] + result["roi_zscore"] + result["sharpe_zscore"]
    )

    # Assign quintiles
    result["quintile"] = assign_quintiles(result)

    return result
