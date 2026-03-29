"""Tests for scoring metrics calculations.

Verifies formulas against GUIDE.md §"Happy Path — Row-by-Row Trace":
- CLV: (resolution_price - entry_price) / entry_price
- ROI: total_pnl / total_capital_deployed
- Sharpe: mean(returns) / std(returns, ddof=1)
"""

import pandas as pd
import pytest

from polymarket_analytics.scoring.metrics import (
    calculate_all_metrics,
    calculate_clv,
    calculate_roi,
    calculate_sharpe,
)


class TestCLVCalculation:
    """Tests for calculate_clv function."""

    def test_clv_calculation_matches_guide(self):
        """Test CLV calculation matches GUIDE.md happy path.

        GUIDE.md §"Happy Path — Row-by-Row Trace":
        - Entry price: 0.60
        - Outcome: YES (resolution_price = 1.0)
        - Expected CLV: (1.0 - 0.60) / 0.60 = 0.667
        """
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice"],
                "avg_entry_price": [0.60],
                "outcome": ["YES"],
            }
        )

        result = calculate_clv(positions)

        assert len(result) == 1
        assert result.iloc[0]["trader_address"] == "0xAlice"
        # (1.0 - 0.60) / 0.60 = 0.40 / 0.60 = 0.666...
        assert pytest.approx(result.iloc[0]["clv_raw"], 0.001) == 0.667

    def test_clv_no_outcome_loss(self):
        """Test CLV for NO outcome (resolution_price = 0.0).

        Entry price: 0.40, Outcome: NO
        Expected CLV: (0.0 - 0.40) / 0.40 = -1.0
        """
        positions = pd.DataFrame(
            {"trader_address": ["0xBob"], "avg_entry_price": [0.40], "outcome": ["NO"]}
        )

        result = calculate_clv(positions)

        assert pytest.approx(result.iloc[0]["clv_raw"], 0.001) == -1.0

    def test_clv_multiple_positions_same_trader(self):
        """Test CLV aggregates mean across multiple positions."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xAlice", "0xAlice"],
                "avg_entry_price": [0.60, 0.50, 0.40],
                "outcome": ["YES", "YES", "NO"],
            }
        )

        # Position 1: (1.0 - 0.60) / 0.60 = 0.667
        # Position 2: (1.0 - 0.50) / 0.50 = 1.0
        # Position 3: (0.0 - 0.40) / 0.40 = -1.0
        # Mean: (0.667 + 1.0 - 1.0) / 3 = 0.222
        result = calculate_clv(positions)

        assert len(result) == 1
        assert pytest.approx(result.iloc[0]["clv_raw"], 0.01) == 0.222

    def test_clv_multiple_traders(self):
        """Test CLV calculates separately for multiple traders."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xBob"],
                "avg_entry_price": [0.60, 0.30],
                "outcome": ["YES", "NO"],
            }
        )

        result = calculate_clv(positions)

        assert len(result) == 2
        # Alice: (1.0 - 0.60) / 0.60 = 0.667
        # Bob: (0.0 - 0.30) / 0.30 = -1.0
        alice = result[result["trader_address"] == "0xAlice"].iloc[0]
        bob = result[result["trader_address"] == "0xBob"].iloc[0]
        assert pytest.approx(alice["clv_raw"], 0.001) == 0.667
        assert pytest.approx(bob["clv_raw"], 0.001) == -1.0


class TestROICalculation:
    """Tests for calculate_roi function."""

    def test_roi_calculation(self):
        """Test ROI calculation matches GUIDE.md formula.

        Total PnL: 40, Total capital deployed: 60
        Expected ROI: 40 / 60 = 0.667
        """
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice"],
                "pnl": [40.0],
                "size": [100.0],
                "avg_entry_price": [0.60],
            }
        )

        # Capital deployed = 100 * 0.60 = 60
        # ROI = 40 / 60 = 0.667
        result = calculate_roi(positions)

        assert len(result) == 1
        assert result.iloc[0]["trader_address"] == "0xAlice"
        assert pytest.approx(result.iloc[0]["roi_raw"], 0.001) == 0.667
        assert result.iloc[0]["total_pnl"] == 40.0

    def test_roi_division_by_zero_guard(self):
        """Test ROI handles zero capital_deployed gracefully.

        When capital_deployed = 0, ROI should return 0.0 (not exception/NaN).
        """
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice"],
                "pnl": [100.0],
                "size": [0.0],
                "avg_entry_price": [0.50],
            }
        )

        result = calculate_roi(positions)

        assert len(result) == 1
        assert result.iloc[0]["roi_raw"] == 0.0

    def test_roi_multiple_positions_aggregation(self):
        """Test ROI aggregates total_pnl and total_capital correctly."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xAlice"],
                "pnl": [40.0, -20.0],
                "size": [100.0, 50.0],
                "avg_entry_price": [0.60, 0.40],
            }
        )

        # Total PnL = 40 + (-20) = 20
        # Total capital = (100 * 0.60) + (50 * 0.40) = 60 + 20 = 80
        # ROI = 20 / 80 = 0.25
        result = calculate_roi(positions)

        assert len(result) == 1
        assert result.iloc[0]["total_pnl"] == 20.0
        assert pytest.approx(result.iloc[0]["roi_raw"], 0.001) == 0.25


class TestSharpeCalculation:
    """Tests for calculate_sharpe function."""

    def test_sharpe_with_sample_std(self):
        """Test Sharpe uses sample std (ddof=1) per statistics convention.

        Returns: [0.1, 0.2, 0.3]
        Expected: mean=0.2, std(ddof=1)=0.1, Sharpe=2.0
        """
        # Create positions with known returns
        # return = pnl / (size * entry_price)
        # For return of 0.1: pnl=10, capital=100 (size=100, price=1.0)
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xAlice", "0xAlice"],
                "pnl": [10.0, 20.0, 30.0],
                "size": [100.0, 100.0, 100.0],
                "avg_entry_price": [1.0, 1.0, 1.0],
            }
        )

        # Returns: [0.1, 0.2, 0.3]
        # mean = 0.2
        # std(ddof=1) = sqrt(((0.1-0.2)^2 + (0.2-0.2)^2 + (0.3-0.2)^2) / 2) = sqrt(0.02/2) = 0.1
        # Sharpe = 0.2 / 0.1 = 2.0
        result = calculate_sharpe(positions)

        assert len(result) == 1
        assert pytest.approx(result.iloc[0]["sharpe_raw"], 0.01) == 2.0

    def test_sharpe_handles_zero_std(self):
        """Test Sharpe returns 0.0 when all returns are identical (std=0).

        Returns: [0.1, 0.1, 0.1]
        Expected: Sharpe = 0.0 (not exception)
        """
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xAlice", "0xAlice"],
                "pnl": [10.0, 10.0, 10.0],
                "size": [100.0, 100.0, 100.0],
                "avg_entry_price": [1.0, 1.0, 1.0],
            }
        )

        result = calculate_sharpe(positions)

        assert len(result) == 1
        assert result.iloc[0]["sharpe_raw"] == 0.0

    def test_sharpe_handles_single_position(self):
        """Test Sharpe returns 0.0 for single position (not enough data for std)."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice"],
                "pnl": [10.0],
                "size": [100.0],
                "avg_entry_price": [1.0],
            }
        )

        result = calculate_sharpe(positions)

        assert len(result) == 1
        assert result.iloc[0]["sharpe_raw"] == 0.0

    def test_sharpe_multiple_traders(self):
        """Test Sharpe calculates separately for multiple traders."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xAlice", "0xBob", "0xBob", "0xBob"],
                "pnl": [10.0, 20.0, 15.0, 15.0, 15.0],
                "size": [100.0, 100.0, 100.0, 100.0, 100.0],
                "avg_entry_price": [1.0, 1.0, 1.0, 1.0, 1.0],
            }
        )

        result = calculate_sharpe(positions)

        assert len(result) == 2
        # Alice: returns [0.1, 0.2], mean=0.15, std(ddof=1)=0.0707, Sharpe=2.12
        # Bob: returns [0.15, 0.15, 0.15], std=0, Sharpe=0.0
        alice = result[result["trader_address"] == "0xAlice"].iloc[0]
        bob = result[result["trader_address"] == "0xBob"].iloc[0]
        assert pytest.approx(alice["sharpe_raw"], 0.01) == 2.12
        assert bob["sharpe_raw"] == 0.0


class TestCalculateAllMetrics:
    """Tests for calculate_all_metrics convenience function."""

    def test_all_metrics_merged_correctly(self):
        """Test calculate_all_metrics returns merged DataFrame with all metrics."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xAlice"],
                "pnl": [40.0, -20.0],
                "size": [100.0, 50.0],
                "avg_entry_price": [0.60, 0.40],
                "outcome": ["YES", "NO"],
            }
        )

        result = calculate_all_metrics(positions)

        assert len(result) == 1
        assert "trader_address" in result.columns
        assert "clv_raw" in result.columns
        assert "roi_raw" in result.columns
        assert "sharpe_raw" in result.columns
        assert "position_count" in result.columns
        assert result.iloc[0]["position_count"] == 2

    def test_all_metrics_multiple_traders(self):
        """Test calculate_all_metrics handles multiple traders."""
        positions = pd.DataFrame(
            {
                "trader_address": ["0xAlice", "0xBob"],
                "pnl": [40.0, -15.0],
                "size": [100.0, 50.0],
                "avg_entry_price": [0.60, 0.30],
                "outcome": ["YES", "YES"],
            }
        )

        result = calculate_all_metrics(positions)

        assert len(result) == 2
        assert set(result["trader_address"].tolist()) == {"0xAlice", "0xBob"}
