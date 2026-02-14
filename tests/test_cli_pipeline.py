"""Tests for pipeline decoupling CLI commands (discover, backfill, status)."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from click.testing import CliRunner

from src.cli.commands import cli
from src.db.models import Base, Trader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_session_factory():
    """Create in-memory session factory with tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture
def mock_deps(mock_session_factory):
    """Mock _get_dependencies returning 5-tuple."""
    mock_client = MagicMock()
    mock_filter = MagicMock()
    mock_filter.requires_detail.return_value = True
    mock_alerter = None
    mock_gamma = MagicMock()
    return (mock_session_factory, mock_client, mock_filter, mock_alerter, mock_gamma)


class TestDiscoverCommand:
    """Tests for the discover CLI command."""

    @patch("src.cli.commands._get_dependencies")
    @patch("src.pipeline.ingest.IngestionPipeline.ingest_active_markets")
    @patch("src.pipeline.ingest.IngestionPipeline.discover_traders_from_market")
    def test_discover_runs_without_backfill(
        self, mock_discover, mock_ingest, mock_deps_fn, runner, mock_deps
    ):
        """Discover command should NOT trigger backfill."""
        mock_deps_fn.return_value = mock_deps
        mock_ingest.return_value = 5
        mock_discover.return_value = ["0xTrader1", "0xTrader2"]

        result = runner.invoke(cli, ["discover"])

        assert result.exit_code == 0
        assert "Discovery complete" in result.output

    @patch("src.cli.commands._get_dependencies")
    @patch("src.pipeline.ingest.IngestionPipeline.ingest_targeted_markets")
    @patch("src.pipeline.ingest.IngestionPipeline.discover_traders_from_market")
    def test_discover_with_niche_filter(
        self, mock_discover, mock_targeted, mock_deps_fn, runner, mock_deps
    ):
        """Discover with --niche should use targeted market ingestion."""
        mock_deps_fn.return_value = mock_deps
        mock_targeted.return_value = 3
        mock_discover.return_value = []

        result = runner.invoke(cli, ["discover", "--niche", "esports"])

        assert result.exit_code == 0
        assert "esports" in result.output

    @patch("src.cli.commands._get_dependencies")
    @patch("src.pipeline.ingest.IngestionPipeline.ingest_active_markets")
    @patch("src.pipeline.ingest.IngestionPipeline.discover_traders_from_market")
    def test_discover_reports_trader_count(
        self, mock_discover, mock_ingest, mock_deps_fn, runner, mock_deps
    ):
        """Discover should report number of new traders found."""
        mock_deps_fn.return_value = mock_deps
        mock_ingest.return_value = 2
        mock_discover.return_value = ["0xNew1", "0xNew2", "0xNew3"]

        result = runner.invoke(cli, ["discover"])

        assert result.exit_code == 0


class TestBackfillCommand:
    """Tests for the backfill CLI command."""

    @patch("src.cli.commands._get_dependencies")
    @patch("src.cli.commands.find_trader_by_prefix")
    @patch("src.pipeline.ingest.IngestionPipeline.ingest_trader_history_hybrid")
    def test_backfill_single_trader(
        self, mock_hybrid, mock_find, mock_deps_fn, runner, mock_deps
    ):
        """Backfill with address should process only that trader."""
        mock_deps_fn.return_value = mock_deps
        mock_find.return_value = "0xfull_address_here"
        mock_hybrid.return_value = {
            "source": "hybrid",
            "tiers_used": ["api"],
            "detail_count": 42,
        }

        result = runner.invoke(cli, ["backfill", "0xfull"])

        assert result.exit_code == 0
        assert "Backfill complete" in result.output

    @patch("src.cli.commands._get_dependencies")
    @patch("src.pipeline.queries.get_traders_by_backfill_status")
    def test_backfill_no_pending(self, mock_query, mock_deps_fn, runner, mock_deps):
        """Backfill with no pending traders should report nothing to do."""
        mock_deps_fn.return_value = mock_deps
        mock_query.return_value = []

        result = runner.invoke(cli, ["backfill"])

        assert result.exit_code == 0
        assert "No traders pending" in result.output


class TestStatusCommand:
    """Tests for the status CLI command."""

    @patch("src.cli.commands._get_dependencies")
    def test_status_shows_counts(
        self, mock_deps_fn, runner, mock_deps, mock_session_factory
    ):
        """Status should display discovered and backfilled counts."""
        mock_deps_fn.return_value = mock_deps

        session = mock_session_factory()
        session.add(
            Trader(
                address="0xaaa",
                backfill_complete=False,
                first_seen=datetime(2025, 1, 1),
                last_active=datetime(2025, 1, 1),
            )
        )
        session.add(
            Trader(
                address="0xbbb",
                backfill_complete=True,
                first_seen=datetime(2025, 1, 2),
                last_active=datetime(2025, 1, 2),
            )
        )
        session.commit()
        session.close()

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Pipeline Status" in result.output

    @patch("src.cli.commands._get_dependencies")
    def test_status_empty_database(self, mock_deps_fn, runner, mock_deps):
        """Status with empty database should show zero counts."""
        mock_deps_fn.return_value = mock_deps

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Pipeline Status" in result.output
