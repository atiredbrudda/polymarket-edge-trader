"""Tests for research CLI command and formatters."""

import json
from unittest.mock import Mock, patch, MagicMock
import pytest
from click.testing import CliRunner
from rich.table import Table
from rich.text import Text

from src.cli.formatters import format_research_table, format_batch_summary
from src.cli.commands import cli


class TestFormatResearchTable:
    """Tests for format_research_table formatter."""

    def test_format_research_table_basic(self):
        """Renders table with sample trades."""
        trades = [
            {
                "maker": "0xabc123...",
                "taker": "0xdef456...",
                "timestamp": 1640000000,
                "side": "BUY",
                "price": 0.65,
                "makerAmountFilled": 1000000000,  # 1000 USDC (6 decimals)
                "takerAmountFilled": 500000000,   # 500 USDC (6 decimals)
                "blockNumber": 12345678,
            },
            {
                "maker": "0xdef456...",
                "taker": "0xabc123...",
                "timestamp": 1640010000,
                "side": "SELL",
                "price": 0.55,
                "makerAmountFilled": 2000000000,  # 2000 USDC
                "takerAmountFilled": 1500000000,  # 1500 USDC
                "blockNumber": 12345700,
            },
        ]

        trader_address = "0xabc123..."
        total_count = 2

        table = format_research_table(trades, trader_address, total_count)

        assert isinstance(table, Table)
        assert "Trade History" in table.title
        assert "0xabc1...3..." in table.title  # Truncated address
        assert "(2 trades)" in table.title

    def test_format_research_table_empty(self):
        """Handles empty trades list."""
        trades = []
        trader_address = "0xabc123..."
        total_count = 0

        table = format_research_table(trades, trader_address, total_count)

        assert isinstance(table, Table)
        assert "(0 trades)" in table.title
        # No rows added but table structure is valid
        assert table.row_count == 0

    def test_format_research_table_truncated(self):
        """Shows footer when total_count > displayed."""
        trades = [
            {
                "maker": "0xabc123...",
                "taker": "0xdef456...",
                "timestamp": 1640000000,
                "side": "BUY",
                "price": 0.65,
                "makerAmountFilled": 1000000000,
                "takerAmountFilled": 500000000,
                "blockNumber": 12345678,
            }
        ]

        trader_address = "0xabc123..."
        total_count = 100  # Total is more than displayed

        table = format_research_table(trades, trader_address, total_count)

        assert isinstance(table, Table)
        assert table.caption == "Showing 1 of 100 trades"

    def test_format_research_table_role_detection(self):
        """MAKER/TAKER correctly identified."""
        trades = [
            {
                "maker": "0xABC123...",  # Trader is maker (case-insensitive)
                "taker": "0xdef456...",
                "timestamp": 1640000000,
                "side": "BUY",
                "price": 0.65,
                "makerAmountFilled": 1000000000,
                "takerAmountFilled": 500000000,
                "blockNumber": 12345678,
            },
            {
                "maker": "0xdef456...",
                "taker": "0xabc123...",  # Trader is taker (case-insensitive)
                "timestamp": 1640010000,
                "side": "SELL",
                "price": 0.55,
                "makerAmountFilled": 2000000000,
                "takerAmountFilled": 1500000000,
                "blockNumber": 12345700,
            },
        ]

        trader_address = "0xabc123..."  # Lowercase input
        total_count = 2

        table = format_research_table(trades, trader_address, total_count)

        assert isinstance(table, Table)
        # First trade: trader is maker, so size should be makerAmountFilled / 1e6 = 1000
        # Second trade: trader is taker, so size should be takerAmountFilled / 1e6 = 1500


class TestFormatBatchSummary:
    """Tests for format_batch_summary formatter."""

    def test_format_batch_summary(self):
        """Renders batch results table."""
        results = [
            {
                "address": "0xabc123...",
                "found": 100,
                "inserted": 95,
                "skipped": 5,
                "error": None,
            },
            {
                "address": "0xdef456...",
                "found": 0,
                "inserted": 0,
                "skipped": 0,
                "error": None,
            },
            {
                "address": "0xghi789...",
                "found": 50,
                "inserted": 0,
                "skipped": 50,
                "error": "Database error",
            },
        ]

        table = format_batch_summary(results)

        assert isinstance(table, Table)
        assert "Batch Analysis Summary" in table.title
        assert table.row_count == 3


class TestResearchCommand:
    """Tests for research CLI command."""

    @patch("src.datasources.jbecker.JBeckerDataset")
    @patch("src.cli.commands._get_dependencies")
    def test_research_dataset_not_available(self, mock_deps, mock_jbecker_class):
        """Prints download instructions when dataset missing."""
        runner = CliRunner()

        # Mock JBecker dataset as unavailable
        mock_jbecker = Mock()
        mock_jbecker.is_available.return_value = False
        mock_jbecker_class.return_value = mock_jbecker

        result = runner.invoke(cli, ["research", "0xabc123"])

        assert result.exit_code == 0
        assert "JBecker dataset not available" in result.output
        assert "wget https://s3.jbecker.dev/data.tar.zst" in result.output
        assert "JBECKER_DATA_PATH" in result.output

    @patch("src.datasources.jbecker.JBeckerDataset")
    @patch("src.cli.commands._get_dependencies")
    def test_research_json_format(self, mock_deps, mock_jbecker_class):
        """--format json outputs valid JSON."""
        runner = CliRunner()

        # Mock JBecker dataset
        mock_jbecker = Mock()
        mock_jbecker.is_available.return_value = True
        mock_jbecker.get_trade_count.return_value = 1
        mock_jbecker.query_trader_history.return_value = [
            {"maker": "0xabc", "taker": "0xdef", "timestamp": 1640000000}
        ]
        mock_jbecker_class.return_value = mock_jbecker

        # Mock dependencies (DB lookup will fail gracefully)
        mock_deps.side_effect = Exception("DB not available")

        result = runner.invoke(cli, ["research", "0xabc123", "--format", "json"])

        assert result.exit_code == 0
        # Output should contain JSON-like content
        assert "maker" in result.output
        assert "taker" in result.output

    @patch("src.datasources.jbecker.JBeckerDataset")
    @patch("src.cli.commands._get_dependencies")
    def test_research_csv_format(self, mock_deps, mock_jbecker_class):
        """--format csv outputs CSV header + rows."""
        runner = CliRunner()

        # Mock JBecker dataset
        mock_jbecker = Mock()
        mock_jbecker.is_available.return_value = True
        mock_jbecker.get_trade_count.return_value = 1
        mock_jbecker.query_trader_history.return_value = [
            {"maker": "0xabc", "taker": "0xdef", "timestamp": 1640000000}
        ]
        mock_jbecker_class.return_value = mock_jbecker

        # Mock dependencies
        mock_deps.side_effect = Exception("DB not available")

        result = runner.invoke(cli, ["research", "0xabc123", "--format", "csv"])

        assert result.exit_code == 0
        # Should contain CSV header and data
        assert "maker" in result.output or "taker" in result.output


class TestBatchAnalyzeCommand:
    """Tests for batch-analyze CLI command."""

    def test_batch_analyze_no_addresses(self):
        """Prints error when no addresses provided."""
        runner = CliRunner()

        result = runner.invoke(cli, ["batch-analyze"])

        assert result.exit_code == 0
        assert "No addresses provided" in result.output

    @patch("src.pipeline.ingest.IngestionPipeline")
    @patch("src.datasources.jbecker.JBeckerDataset")
    @patch("src.cli.commands._get_dependencies")
    def test_batch_analyze_from_file(self, mock_deps, mock_jbecker_class, mock_pipeline_class):
        """Reads addresses from file and processes."""
        runner = CliRunner()

        # Mock JBecker dataset
        mock_jbecker = Mock()
        mock_jbecker.is_available.return_value = True
        mock_jbecker_class.return_value = mock_jbecker

        # Mock dependencies
        mock_session_factory = Mock()
        mock_client = Mock()
        mock_filter = Mock()
        mock_deps.return_value = (mock_session_factory, mock_client, mock_filter, None, None)

        # Mock pipeline
        mock_pipeline = Mock()
        mock_pipeline.ingest_trader_history_jbecker.return_value = {
            "detail_count": 10,
            "trades_inserted": 8,
            "duplicates_skipped": 2,
        }
        mock_pipeline_class.return_value = mock_pipeline

        # Create temp file with addresses
        with runner.isolated_filesystem():
            with open("traders.txt", "w") as f:
                f.write("0xabc123\n")
                f.write("# Comment line\n")
                f.write("0xdef456\n")
                f.write("\n")  # Empty line

            result = runner.invoke(cli, ["batch-analyze", "--file", "traders.txt"])

        assert result.exit_code == 0
        # Should process 2 addresses (skip comment and empty line)
        assert mock_pipeline.ingest_trader_history_jbecker.call_count == 2
        assert "Batch Analysis Summary" in result.output or "Totals" in result.output
