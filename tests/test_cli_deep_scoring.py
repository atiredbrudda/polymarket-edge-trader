"""Tests for deep scoring CLI commands.

Tests for:
- leaderboard command with --depth flag
- expertise command
- specialists command
"""

import pytest
from click.testing import CliRunner
from decimal import Decimal
from datetime import datetime, UTC

from src.db.models import (
    Base,
    ExpertiseScore,
    Market,
    MarketClassification,
    Position,
    TaxonomyNode,
)
from src.cli.commands import cli


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


@pytest.fixture
def mock_session(mocker, in_memory_db):
    """Mock the session dependency."""
    from src.cli.commands import get_session

    mock_get_session = mocker.patch("src.cli.commands._get_dependencies")
    mock_session_factory = in_memory_db

    mock_get_session.return_value = (mock_session_factory, None, None, None, None)

    mock_session = mocker.MagicMock()
    mock_get_sess = mocker.patch("src.cli.commands.get_session")
    mock_get_sess.return_value.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_get_sess.return_value.__exit__ = mocker.MagicMock(return_value=False)

    return mock_session


class TestLeaderboardDepth:
    """Tests for leaderboard command structure (updated for lift-based leaderboard)."""

    def test_leaderboard_category_option_exists(self, runner):
        """Verify --category option is available (replaces old --depth)."""
        result = runner.invoke(cli, ["leaderboard", "--help"])
        assert "--category" in result.output or "-c" in result.output

    def test_leaderboard_has_top_n_option(self, runner):
        """Verify --top-n option is available."""
        result = runner.invoke(cli, ["leaderboard", "--help"])
        assert "--top-n" in result.output or "-n" in result.output


class TestExpertiseCommand:
    """Tests for expertise command."""

    def test_expertise_command_exists(self, runner):
        """Verify expertise command is registered."""
        result = runner.invoke(cli, ["--help"])
        assert "expertise" in result.output

    def test_expertise_help(self, runner):
        """Verify expertise command help text."""
        result = runner.invoke(cli, ["expertise", "--help"])
        assert "trader" in result.output.lower()


class TestSpecialistsCommand:
    """Tests for specialists command."""

    def test_specialists_command_exists(self, runner):
        """Verify specialists command is registered."""
        result = runner.invoke(cli, ["--help"])
        assert "specialists" in result.output

    def test_specialists_help(self, runner):
        """Verify specialists command help text."""
        result = runner.invoke(cli, ["specialists", "--help"])
        assert "hidden" in result.output.lower()
        assert "game" in result.output.lower()

    def test_specialists_options(self, runner):
        """Verify specialists has threshold options."""
        result = runner.invoke(cli, ["specialists", "--help"])
        assert "--game-threshold" in result.output
        assert "--deep-threshold" in result.output


class TestFormatters:
    """Tests for deep scoring formatters."""

    def test_format_expertise_breakdown(self):
        """Verify format_expertise_breakdown works."""
        from src.cli.formatters import format_expertise_breakdown

        scores_by_depth = {
            1: [
                {
                    "slug": "esports.cs2",
                    "score": Decimal("75"),
                    "percentile": Decimal("80"),
                    "specialization": "specialist",
                },
            ],
            2: [
                {
                    "slug": "esports.cs2.iem-katowice",
                    "score": Decimal("85"),
                    "percentile": Decimal("90"),
                    "specialization": "specialist",
                },
            ],
            3: [],
        }

        result = format_expertise_breakdown("0xTrader1", scores_by_depth)
        assert result is not None

    def test_format_specialists_table(self):
        """Verify format_specialists_table works."""
        from src.cli.formatters import format_specialists_table

        specialists = [
            {
                "trader_address": "0xTrader1",
                "game_score": Decimal("50"),
                "deep_slug": "esports.cs2.iem-katowice",
                "deep_depth": 2,
                "deep_score": Decimal("80"),
                "score_delta": Decimal("30"),
            }
        ]

        result = format_specialists_table(specialists, "esports.cs2")
        assert result is not None
        assert "esports.cs2" in result.title


@pytest.fixture
def runner():
    """Create CLI runner."""
    return CliRunner()
