"""Tests for z-score normalization and quintile assignment.

Tests cover:
- Z-score computation with standard cases
- Edge cases: zero std, single value
- Quintile distribution and tied scores handling
- Full pipeline integration
"""

import numpy as np
import pandas as pd
import pytest

from src.polymarket_analytics.scoring.normalization import (
    assign_quintiles,
    compute_normalized_scores,
    zscore_normalize,
)


class TestZscoreNormalize:
    """Tests for zscore_normalize function."""

    def test_zscore_normalize_standard_case(self):
        """Z-scores computed correctly for standard distribution."""
        # Create values: [1, 2, 3, 4, 5]
        df = pd.DataFrame({"values": [1, 2, 3, 4, 5]})

        result = zscore_normalize(df, "values")

        # Expected: mean=3, std(ddof=1)=1.581...
        # z-scores should have mean ≈ 0, std ≈ 1
        assert len(result) == 5
        assert result.mean() == pytest.approx(0.0, abs=1e-10)
        assert result.std(ddof=1) == pytest.approx(1.0, abs=1e-10)
        # Middle value (3) should have z-score = 0
        assert result.iloc[2] == pytest.approx(0.0, abs=1e-10)
        # First value (1) should have negative z-score
        assert result.iloc[0] < 0
        # Last value (5) should have positive z-score
        assert result.iloc[4] > 0

    def test_zscore_normalize_zero_std(self):
        """Z-score returns 0.0 when all values are identical (std=0)."""
        # All identical values
        df = pd.DataFrame({"values": [5, 5, 5, 5, 5]})

        result = zscore_normalize(df, "values")

        # All z-scores should be 0.0, not NaN or exception
        assert len(result) == 5
        assert all(result == 0.0)
        assert not result.isna().any()

    def test_zscore_normalize_single_value(self):
        """Z-score returns 0.0 for single value (std undefined)."""
        df = pd.DataFrame({"values": [42]})

        result = zscore_normalize(df, "values")

        # Single value should return z-score = 0.0
        assert len(result) == 1
        assert result.iloc[0] == 0.0
        assert not np.isnan(result.iloc[0])

    def test_zscore_normalize_preserves_index(self):
        """Z-score result preserves original DataFrame index."""
        df = pd.DataFrame({"values": [1, 2, 3, 4, 5]}, index=[10, 20, 30, 40, 50])

        result = zscore_normalize(df, "values")

        assert list(result.index) == [10, 20, 30, 40, 50]


class TestAssignQuintiles:
    """Tests for assign_quintiles function."""

    def test_assign_quintiles_distribution(self):
        """Quintiles distribute ~20% of traders per quintile."""
        # Create 100 traders with unique composite scores
        np.random.seed(42)
        df = pd.DataFrame({"composite_score": np.random.randn(100)})

        result = assign_quintiles(df)

        # All 5 quintiles should be present
        assert set(result.unique()) == {1, 2, 3, 4, 5}
        # Each quintile should have roughly 20% (~20 traders)
        value_counts = result.value_counts()
        for quintile in [1, 2, 3, 4, 5]:
            count = value_counts.get(quintile, 0)
            # Allow some variance: between 15 and 25 (20 ± 5)
            assert 15 <= count <= 25, f"Quintile {quintile} has {count} traders"

    def test_assign_quintiles_tied_scores(self):
        """pd.qcut handles tied scores gracefully with duplicates='drop'."""
        # Create traders with many identical composite scores
        df = pd.DataFrame(
            {"composite_score": [1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 5.0, 5.0]}
        )

        # Should not raise exception
        result = assign_quintiles(df)

        # Quintiles should be assigned (may be fewer than 5 unique due to ties)
        assert len(result) == 10
        assert result.min() >= 1
        assert result.max() <= 5
        assert not result.isna().any()

    def test_assign_quintiles_all_identical(self):
        """All identical scores fallback to middle quintile (3)."""
        df = pd.DataFrame({"composite_score": [5.0, 5.0, 5.0, 5.0, 5.0]})

        result = assign_quintiles(df)

        # All should get quintile 3 (middle)
        assert all(result == 3)
        assert len(result) == 5

    def test_assign_quintiles_returns_int(self):
        """Quintile values are integers."""
        df = pd.DataFrame({"composite_score": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]})

        result = assign_quintiles(df)

        # All values should be integers (any numpy integer type)
        assert np.issubdtype(result.dtype, np.integer)
        assert all(result.astype(int) == result)


class TestComputeNormalizedScores:
    """Tests for compute_normalized_scores function."""

    def test_compute_normalized_scores_full_pipeline(self):
        """Full pipeline: z-scores, composite, and quintiles computed."""
        # Create DataFrame with 10 traders
        df = pd.DataFrame(
            {
                "trader_address": [f"0x{i:03d}" for i in range(10)],
                "clv_raw": np.random.randn(10),
                "roi_raw": np.random.randn(10),
                "sharpe_raw": np.random.randn(10),
            }
        )

        result = compute_normalized_scores(df)

        # Output should have all expected columns
        assert "clv_zscore" in result.columns
        assert "roi_zscore" in result.columns
        assert "sharpe_zscore" in result.columns
        assert "composite_score" in result.columns
        assert "quintile" in result.columns

        # Composite should equal sum of z-scores (within tolerance)
        expected_composite = (
            result["clv_zscore"] + result["roi_zscore"] + result["sharpe_zscore"]
        )
        pd.testing.assert_series_equal(
            result["composite_score"], expected_composite, check_names=False
        )

        # Z-scores should have mean ≈ 0, std ≈ 1
        for col in ["clv_zscore", "roi_zscore", "sharpe_zscore"]:
            assert result[col].mean() == pytest.approx(0.0, abs=1e-10)
            assert result[col].std(ddof=1) == pytest.approx(1.0, abs=1e-10)

        # Quintiles should be 1-5
        assert result["quintile"].min() >= 1
        assert result["quintile"].max() <= 5

    def test_compute_normalized_scores_does_not_modify_input(self):
        """Input DataFrame is not modified."""
        df = pd.DataFrame(
            {
                "clv_raw": [1, 2, 3, 4, 5],
                "roi_raw": [0.1, 0.2, 0.3, 0.4, 0.5],
                "sharpe_raw": [0.5, 0.6, 0.7, 0.8, 0.9],
            }
        )
        original_columns = list(df.columns)

        compute_normalized_scores(df)

        # Original DataFrame should be unchanged
        assert list(df.columns) == original_columns

    def test_compute_normalized_scores_zero_std_handling(self):
        """Zero std in any metric is handled gracefully."""
        # All traders have identical CLV
        df = pd.DataFrame(
            {
                "clv_raw": [0.5, 0.5, 0.5, 0.5, 0.5],  # Zero std
                "roi_raw": [0.1, 0.2, 0.3, 0.4, 0.5],
                "sharpe_raw": [0.5, 0.6, 0.7, 0.8, 0.9],
            }
        )

        result = compute_normalized_scores(df)

        # Should not crash, clv_zscore should all be 0
        assert all(result["clv_zscore"] == 0.0)
        # Other z-scores should be computed normally
        assert result["roi_zscore"].std(ddof=1) == pytest.approx(1.0, abs=1e-10)
        assert result["sharpe_zscore"].std(ddof=1) == pytest.approx(1.0, abs=1e-10)

    def test_compute_normalized_scores_preserves_original_columns(self):
        """Original columns are preserved in output."""
        df = pd.DataFrame(
            {
                "trader_address": ["0x001", "0x002", "0x003"],
                "clv_raw": [0.1, 0.2, 0.3],
                "roi_raw": [0.05, 0.10, 0.15],
                "sharpe_raw": [0.8, 0.9, 1.0],
                "extra_col": ["a", "b", "c"],
            }
        )

        result = compute_normalized_scores(df)

        # Original columns should still exist
        assert "trader_address" in result.columns
        assert "clv_raw" in result.columns
        assert "roi_raw" in result.columns
        assert "sharpe_raw" in result.columns
        assert "extra_col" in result.columns
