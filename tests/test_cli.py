"""Unit tests for CLI commands.

Tests Click command group and subcommands using CliRunner.
"""

import pytest
from click.testing import CliRunner

from src.cli.commands import cli, find_trader_by_prefix


class TestCLIGroup:
    """Test CLI command group."""

    def test_help_shows_all_subcommands(self):
        """CLI group --help shows all subcommands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "markets" in result.output
        assert "trader" in result.output
        assert "signals" in result.output
        assert "leaderboard" in result.output
        assert "score" in result.output
        assert "detect" in result.output


class TestMarketsCommand:
    """Test markets subcommand."""

    def test_help_shows_options(self):
        """markets --help shows category option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["markets", "--help"])
        assert result.exit_code == 0
        assert "--category" in result.output or "-c" in result.output


class TestTraderCommand:
    """Test trader subcommand."""

    def test_help_shows_address_argument(self):
        """trader --help shows address argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["trader", "--help"])
        assert result.exit_code == 0
        assert "ADDRESS" in result.output or "address" in result.output


class TestSignalsCommand:
    """Test signals subcommand."""

    def test_help_shows_window_option(self):
        """signals --help shows time window option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["signals", "--help"])
        assert result.exit_code == 0
        assert "--window" in result.output or "-w" in result.output


class TestLeaderboardCommand:
    """Test leaderboard subcommand."""

    def test_help_shows_game_argument(self):
        """leaderboard --help shows game slug argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["leaderboard", "--help"])
        assert result.exit_code == 0
        assert "GAME_SLUG" in result.output or "game" in result.output


class TestScoreCommand:
    """Test score subcommand."""

    def test_help_shows_options(self):
        """score --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["score", "--help"])
        assert result.exit_code == 0
        assert "Options:" in result.output


class TestFindTraderByPrefix:
    """Test partial address matching helper."""

    @pytest.fixture
    def mock_session(self, mocker):
        """Mock SQLAlchemy session."""
        return mocker.MagicMock()

    def test_no_matches(self, mock_session, mocker):
        """No matches returns None and prints error."""
        # Mock query result
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = find_trader_by_prefix(mock_session, "0xNonExistent")
        assert result is None

    def test_single_match(self, mock_session, mocker):
        """Single match returns full address."""
        # Mock query result
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value.all.return_value = ["0xTrader123456"]
        mock_session.execute.return_value = mock_result

        result = find_trader_by_prefix(mock_session, "0xTrader")
        assert result == "0xTrader123456"

    def test_multiple_matches(self, mock_session, mocker):
        """Multiple matches returns None and prints error."""
        # Mock query result
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            "0xTrader123456",
            "0xTrader789012",
        ]
        mock_session.execute.return_value = mock_result

        result = find_trader_by_prefix(mock_session, "0xTrader")
        assert result is None

    def test_normalizes_input(self, mock_session, mocker):
        """Input is normalized (lowercase, strip, add 0x prefix)."""
        # Mock query result
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value.all.return_value = ["0xtrader123"]
        mock_session.execute.return_value = mock_result

        # Test with uppercase and spaces
        result = find_trader_by_prefix(mock_session, "  0xTRADER  ")
        assert result == "0xtrader123"

    def test_adds_0x_prefix_if_missing(self, mock_session, mocker):
        """Adds 0x prefix if missing."""
        # Mock query result
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value.all.return_value = ["0xtrader123"]
        mock_session.execute.return_value = mock_result

        result = find_trader_by_prefix(mock_session, "trader")
        # Should add 0x prefix before query
        assert result == "0xtrader123"
