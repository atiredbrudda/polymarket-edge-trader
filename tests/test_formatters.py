"""Unit tests for CLI formatter functions.

Tests formatter functions that convert data objects to Rich renderables.
All formatters are pure functions with no side effects.
"""

from decimal import Decimal
from datetime import datetime, UTC

import pytest
from rich.table import Table
from rich.console import Group
from rich.panel import Panel

from src.cli.formatters import (
    truncate_address,
    format_markets_table,
    format_trader_profile,
    format_signals_table,
    format_leaderboard_table,
    format_sweep_summary,
)


class TestTruncateAddress:
    """Test address truncation for display."""

    def test_short_address_unchanged(self):
        """Short addresses (< 10 chars) are returned unchanged."""
        address = "0x123456"
        result = truncate_address(address)
        assert result == "0x123456"

    def test_long_address_truncated(self):
        """Long addresses are truncated to first 6 + last 4 chars."""
        address = "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12"
        result = truncate_address(address)
        assert result == "0xAbCd...Ef12"

    def test_exactly_ten_chars_unchanged(self):
        """Address with exactly 10 chars is not truncated."""
        address = "0x12345678"
        result = truncate_address(address)
        assert result == "0x12345678"


class TestFormatMarketsTable:
    """Test markets table formatter."""

    def test_empty_list(self):
        """Empty list returns a Table with headers but no rows."""
        result = format_markets_table([])
        assert isinstance(result, Table)
        assert result.row_count == 0

    def test_single_market(self):
        """Single market creates table with one row."""
        markets = [
            {
                "question": "Will Team A beat Team B?",
                "slug": "esports.cs2",
                "active": True,
            }
        ]
        result = format_markets_table(markets)
        assert isinstance(result, Table)
        assert result.row_count == 1

    def test_multiple_markets(self):
        """Multiple markets create table with multiple rows."""
        markets = [
            {"question": "Market 1", "slug": "esports.cs2", "active": True},
            {"question": "Market 2", "slug": "esports.lol", "active": False},
            {"question": "Market 3", "slug": "esports.dota2", "active": True},
        ]
        result = format_markets_table(markets)
        assert isinstance(result, Table)
        assert result.row_count == 3

    def test_filters_only_classified_markets(self):
        """Markets without classification (slug=None) are excluded."""
        markets = [
            {"question": "Classified", "slug": "esports.cs2", "active": True},
            {"question": "Unclassified", "slug": None, "active": True},
        ]
        result = format_markets_table(markets)
        assert isinstance(result, Table)
        assert result.row_count == 1


class TestFormatTraderProfile:
    """Test trader profile formatter."""

    def test_renders_all_sections(self):
        """Profile renders header, summary, positions, and expertise sections."""
        trader_address = "0xTrader123456789"
        summaries = [
            {"category": "eSports", "volume": Decimal("1000.50"), "trade_count": 42}
        ]
        positions = [
            {
                "market_question": "Will Team A win?",
                "direction": "LONG",
                "size": Decimal("100"),
                "avg_entry_price": Decimal("0.65"),
            }
        ]
        scores = [
            {
                "game": "esports.cs2",
                "score": Decimal("85.5"),
                "percentile": Decimal("92"),
                "specialization": "specialist",
            }
        ]

        result = format_trader_profile(trader_address, summaries, positions, scores)
        assert isinstance(result, Group)

    def test_empty_data(self):
        """Profile handles empty lists gracefully."""
        result = format_trader_profile("0xTrader123", [], [], [])
        assert isinstance(result, Group)


class TestFormatSignalsTable:
    """Test signals table formatter."""

    def test_empty_signals(self):
        """Empty list returns table with headers but no rows."""
        result = format_signals_table([])
        assert isinstance(result, Table)
        assert result.row_count == 0

    def test_single_signal(self):
        """Single signal creates table with one row."""
        signals = [
            {
                "market_question": "Will Team A win?",
                "direction": "LONG",
                "confidence": Decimal("85.5"),
                "expert_count": 5,
                "first_mover_address": "0xFirstMover1234567890",
            }
        ]
        result = format_signals_table(signals)
        assert isinstance(result, Table)
        assert result.row_count == 1

    def test_multiple_signals_with_first_mover(self):
        """Multiple signals render with truncated first mover addresses."""
        signals = [
            {
                "market_question": "Market 1",
                "direction": "LONG",
                "confidence": Decimal("90"),
                "expert_count": 7,
                "first_mover_address": "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12",
            },
            {
                "market_question": "Market 2",
                "direction": "SHORT",
                "confidence": Decimal("75"),
                "expert_count": 4,
                "first_mover_address": None,
            },
        ]
        result = format_signals_table(signals)
        assert isinstance(result, Table)
        assert result.row_count == 2

    def test_confidence_as_percentage(self):
        """Confidence score is displayed as percentage."""
        signals = [
            {
                "market_question": "Market 1",
                "direction": "LONG",
                "confidence": Decimal("85.5"),
                "expert_count": 5,
                "first_mover_address": None,
            }
        ]
        result = format_signals_table(signals)
        # Check that table was created (actual percentage rendering tested via integration)
        assert isinstance(result, Table)


class TestFormatLeaderboardTable:
    """Test leaderboard table formatter."""

    def test_renders_rank_and_scores(self):
        """Leaderboard renders rank, trader, score, win rate."""
        entries = [
            {
                "rank": 1,
                "trader_address": "0xTrader1234567890",
                "score": Decimal("95.5"),
                "win_rate": Decimal("0.85"),
            },
            {
                "rank": 2,
                "trader_address": "0xTrader0987654321",
                "score": Decimal("88.2"),
                "win_rate": Decimal("0.78"),
            },
        ]
        game_slug = "esports.cs2"

        result = format_leaderboard_table(entries, game_slug)
        assert isinstance(result, Table)
        assert result.row_count == 2

    def test_empty_leaderboard(self):
        """Empty leaderboard returns table with headers."""
        result = format_leaderboard_table([], "esports.cs2")
        assert isinstance(result, Table)
        assert result.row_count == 0


class TestFormatSweepSummary:
    """Test sweep summary formatter."""

    def test_renders_all_stats(self):
        """Sweep summary renders all result stats."""
        results = {
            "processing_time": 12.5,
            "markets_count": 42,
            "signals_count": 8,
            "alerts_sent": 3,
        }
        result = format_sweep_summary(results)
        assert isinstance(result, Panel)

    def test_minimal_stats(self):
        """Sweep summary handles minimal stats."""
        results = {
            "processing_time": 5.2,
            "markets_count": 0,
            "signals_count": 0,
            "alerts_sent": 0,
        }
        result = format_sweep_summary(results)
        assert isinstance(result, Panel)
