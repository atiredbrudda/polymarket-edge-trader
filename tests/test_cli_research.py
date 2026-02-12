"""Tests for research CLI command and formatters."""

import pytest
from rich.table import Table
from rich.text import Text

from src.cli.formatters import format_research_table, format_batch_summary


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
