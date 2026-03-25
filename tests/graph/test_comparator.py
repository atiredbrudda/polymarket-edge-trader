"""Tests for Graph vs API/JBecker trade comparator."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, MagicMock

import pytest

from src.graph.comparator import (
    TradeComparator,
    ComparisonResult,
    build_ground_truth_test_set,
)


class TestComparisonResult:
    """Test ComparisonResult dataclass."""

    def test_default_initialization(self):
        """Test default field values."""
        result = ComparisonResult(
            trader_address="0xTrader123",
            source_a_count=100,
            source_b_count=95,
        )

        assert result.trader_address == "0xTrader123"
        assert result.source_a_count == 100
        assert result.source_b_count == 95
        assert result.source_a_name == "Graph"
        assert result.source_b_name == "API/JBecker"
        assert result.matched_by_market_side_timestamp == 0
        assert result.unmatched_source_a == 0
        assert result.unmatched_source_b == 0
        assert result.market_id_divergences == []
        assert result.sample_matches == []


class TestTradeComparator:
    """Test TradeComparator class."""

    @pytest.fixture
    def mock_graph_client(self):
        """Create mock Graph client."""
        client = Mock()
        client.get_trader_trades.return_value = [
            {
                "id": "0xtrade1",
                "maker": "0xTrader123",
                "taker": "0xOther456",
                "makerAmountFilled": "500000",
                "takerAmountFilled": "1000000",
                "makerAssetId": "123",
                "takerAssetId": "456",
                "fee": "1000",
                "timestamp": "1234567890",
                "blockNumber": "82466624",
                "transactionHash": "0xabc",
                "side": "BUY",
                "price": "0.5",
            },
            {
                "id": "0xtrade2",
                "maker": "0xTrader123",
                "taker": "0xOther789",
                "makerAmountFilled": "1000000",
                "takerAmountFilled": "2000000",
                "makerAssetId": "789",
                "takerAssetId": "012",
                "fee": "2000",
                "timestamp": "1234567900",
                "blockNumber": "82466625",
                "transactionHash": "0xdef",
                "side": "SELL",
                "price": "0.6",
            },
        ]
        return client

    @pytest.fixture
    def mock_api_client(self):
        """Create mock API client."""
        client = Mock()
        client.get_trader_trades.return_value = [
            {
                "id": "0xtrade1",
                "market": "123",
                "maker": "0xTrader123",
                "side": "BUY",
                "size": Decimal("1.0"),
                "price": Decimal("0.5"),
                "timestamp": datetime.fromtimestamp(1234567890),
                "asset_ticker": "YES",
            },
            {
                "id": "0xtrade2",
                "market": "789",
                "maker": "0xTrader123",
                "side": "SELL",
                "size": Decimal("2.0"),
                "price": Decimal("0.6"),
                "timestamp": datetime.fromtimestamp(1234567900),
                "asset_ticker": "NO",
            },
        ]
        return client

    def test_initialization(self):
        """Test comparator initialization."""
        comparator = TradeComparator(
            graph_client=Mock(),
            api_client=Mock(),
        )

        assert comparator.graph_client is not None
        assert comparator.api_client is not None
        assert comparator.jbecker_dataset is None

    def test_normalize_trade_for_comparison_graph(self):
        """Test normalization of Graph trades."""
        comparator = TradeComparator()

        graph_trade = {
            "makerAssetId": "123",
            "takerAssetId": "0",
            "makerAmountFilled": "500000",
            "takerAmountFilled": "1000000",
            "side": "BUY",
            "timestamp": "1234567890",
            "price": "0.5",
        }

        normalized = comparator._normalize_trade_for_comparison(graph_trade, "graph")

        assert normalized["market"] == "123"  # Non-USDC asset
        assert normalized["side"] == "BUY"
        assert normalized["timestamp"] == 1234567890
        assert normalized["size"] == 0.5  # makerAmount (token side)
        assert normalized["price"] == 0.5

    def test_normalize_trade_for_comparison_api(self):
        """Test normalization of API trades."""
        comparator = TradeComparator()

        api_trade = {
            "market": "123",
            "side": "BUY",
            "size": Decimal("1.5"),
            "price": Decimal("0.6"),
            "timestamp": datetime.fromtimestamp(1234567890),
        }

        normalized = comparator._normalize_trade_for_comparison(api_trade, "api")

        assert normalized["market"] == "123"
        assert normalized["side"] == "BUY"
        assert normalized["timestamp"] == 1234567890
        assert normalized["size"] == 1.5
        assert normalized["price"] == 0.6

    def test_trades_match_exact(self):
        """Test exact trade matching."""
        comparator = TradeComparator()

        trade_a = {
            "market": "123",
            "side": "BUY",
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }
        trade_b = {
            "market": "123",
            "side": "BUY",
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }

        assert comparator._trades_match(trade_a, trade_b) is True

    def test_trades_match_with_timestamp_tolerance(self):
        """Test matching with timestamp tolerance."""
        comparator = TradeComparator()

        trade_a = {
            "market": "123",
            "side": "BUY",
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }
        trade_b = {
            "market": "123",
            "side": "BUY",
            "timestamp": 1234567920,  # 30 seconds later
            "size": 1.0,
            "price": 0.5,
        }

        # Should match within 60s tolerance
        assert comparator._trades_match(trade_a, trade_b) is True

    def test_trades_mismatch_market(self):
        """Test mismatch on market_id."""
        comparator = TradeComparator()

        trade_a = {
            "market": "123",
            "side": "BUY",
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }
        trade_b = {
            "market": "456",  # Different market
            "side": "BUY",
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }

        assert comparator._trades_match(trade_a, trade_b) is False

    def test_trades_mismatch_side(self):
        """Test mismatch on side."""
        comparator = TradeComparator()

        trade_a = {
            "market": "123",
            "side": "BUY",
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }
        trade_b = {
            "market": "123",
            "side": "SELL",  # Different side
            "timestamp": 1234567890,
            "size": 1.0,
            "price": 0.5,
        }

        assert comparator._trades_match(trade_a, trade_b) is False

    def test_compare_trader_with_matching_trades(
        self, mock_graph_client, mock_api_client
    ):
        """Test comparison when trades match."""
        comparator = TradeComparator(
            graph_client=mock_graph_client,
            api_client=mock_api_client,
        )

        result = comparator.compare_trader("0xTrader123")

        assert result.trader_address == "0xTrader123"
        assert result.source_a_count == 2
        assert result.source_b_count == 2
        assert result.matched_by_market_side_timestamp >= 0

    def test_compare_trader_no_graph_client(self, mock_api_client):
        """Test comparison without Graph client."""
        comparator = TradeComparator(
            graph_client=None,
            api_client=mock_api_client,
        )

        result = comparator.compare_trader("0xTrader123")

        assert result.source_a_count == 0
        assert result.source_b_count == 2

    def test_compare_trader_no_api_client(self, mock_graph_client):
        """Test comparison without API client."""
        comparator = TradeComparator(
            graph_client=mock_graph_client,
            api_client=None,
        )

        result = comparator.compare_trader("0xTrader123")

        assert result.source_a_count == 2
        assert result.source_b_count == 0

    def test_compare_multiple_traders(self, mock_graph_client, mock_api_client):
        """Test comparison for multiple traders."""
        comparator = TradeComparator(
            graph_client=mock_graph_client,
            api_client=mock_api_client,
        )

        traders = ["0xTrader123", "0xTrader456", "0xTrader789"]
        results = comparator.compare_multiple_traders(traders)

        assert len(results) == 3
        assert all(isinstance(r, ComparisonResult) for r in results)

    def test_compare_multiple_traders_saves_results(
        self, mock_graph_client, mock_api_client, tmp_path
    ):
        """Test that results are saved to file."""
        comparator = TradeComparator(
            graph_client=mock_graph_client,
            api_client=mock_api_client,
        )

        output_path = tmp_path / "results.json"
        traders = ["0xTrader123"]

        comparator.compare_multiple_traders(traders, output_path)

        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)
        assert len(data) == 1


class TestBuildGroundTruthTestSet:
    """Test build_ground_truth_test_set function."""

    def test_build_test_set_splits_correctly(self, tmp_path):
        """Test that traders are split into test/validation sets."""
        mock_graph = Mock()
        mock_graph.get_trader_trades.return_value = []

        mock_api = Mock()
        mock_api.get_trader_trades.return_value = []

        traders = [f"0xTrader{i:03d}" for i in range(10)]

        summary = build_ground_truth_test_set(
            trader_addresses=traders,
            output_dir=tmp_path,
            graph_client=mock_graph,
            api_client=mock_api,
        )

        assert summary["total_traders"] == 10
        assert summary["test_traders"] == 5
        assert summary["validation_traders"] == 5

        # Check output files exist
        assert (tmp_path / "test_set_comparison.json").exists()
        assert (tmp_path / "validation_set_comparison.json").exists()
        assert (tmp_path / "summary.json").exists()

    def test_build_test_set_with_fewer_traders(self, tmp_path):
        """Test with fewer than 10 traders."""
        mock_graph = Mock()
        mock_graph.get_trader_trades.return_value = []

        mock_api = Mock()
        mock_api.get_trader_trades.return_value = []

        traders = [f"0xTrader{i:03d}" for i in range(3)]

        summary = build_ground_truth_test_set(
            trader_addresses=traders,
            output_dir=tmp_path,
            graph_client=mock_graph,
            api_client=mock_api,
        )

        # All go to test set, validation is empty
        assert summary["test_traders"] == 3
        assert summary["validation_traders"] == 0

    def test_build_test_set_generates_valid_summary(self, tmp_path):
        """Test that summary has correct structure."""
        mock_graph = Mock()
        mock_graph.get_trader_trades.return_value = [
            {
                "id": "0xtrade1",
                "maker": "0xTrader000",
                "taker": "0xOther",
                "makerAmountFilled": "500000",
                "takerAmountFilled": "1000000",
                "makerAssetId": "123",
                "takerAssetId": "456",
                "timestamp": "1234567890",
                "side": "BUY",
                "price": "0.5",
            }
        ] * 10

        mock_api = Mock()
        mock_api.get_trader_trades.return_value = [
            {
                "id": "0xtrade1",
                "market": "123",
                "side": "BUY",
                "size": Decimal("1.0"),
                "price": Decimal("0.5"),
                "timestamp": datetime.fromtimestamp(1234567890),
            }
        ] * 10

        traders = [f"0xTrader{i:03d}" for i in range(2)]

        summary = build_ground_truth_test_set(
            trader_addresses=traders,
            output_dir=tmp_path,
            graph_client=mock_graph,
            api_client=mock_api,
        )

        # Check summary structure
        assert "generated_at" in summary
        assert "test_results" in summary
        assert "validation_results" in summary

        # Check test result structure
        if summary["test_results"]:
            result = summary["test_results"][0]
            assert "trader" in result
            assert "graph_trades" in result
            assert "api_trades" in result
            assert "matched" in result
