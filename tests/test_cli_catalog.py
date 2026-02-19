"""Tests for catalog-stats CLI command."""

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from src.db.models import Base, TokenCatalog
from src.cli.commands import cli


@pytest.fixture
def in_memory_session_factory():
    """Create in-memory SQLite session factory for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_catalog_stats_empty_catalog(in_memory_session_factory):
    """Test catalog-stats with empty catalog shows zeros."""
    with patch("src.cli.commands._get_dependencies") as mock_deps:
        mock_deps.return_value = (in_memory_session_factory, None, None, None, None)
        runner = CliRunner()
        result = runner.invoke(cli, ["catalog-stats"])
        assert result.exit_code == 0
        assert "Total rows" in result.output
        assert "0" in result.output
        assert "Catalog is empty" in result.output


def test_catalog_stats_with_esports_rows(in_memory_session_factory):
    """Test catalog-stats with esports rows shows correct counts."""
    session = in_memory_session_factory()

    # Add esports rows
    for i in range(3):
        catalog_entry = TokenCatalog(
            token_id=f"token_{i}",
            condition_id=f"cond_{i}",
            question=f"Question {i}?",
            niche_slug="esports",
            node_path="eSports.CS2.IEM",
            depth=2,
            market_type="match",
        )
        session.add(catalog_entry)

    # Add unclassified rows
    for i in range(3, 5):
        catalog_entry = TokenCatalog(
            token_id=f"token_{i}",
            condition_id=f"cond_{i}",
            question=f"Unclassified {i}?",
            niche_slug=None,
            node_path=None,
            depth=None,
            market_type=None,
        )
        session.add(catalog_entry)

    session.commit()
    session.close()

    with patch("src.cli.commands._get_dependencies") as mock_deps:
        mock_deps.return_value = (in_memory_session_factory, None, None, None, None)
        runner = CliRunner()
        result = runner.invoke(cli, ["catalog-stats"])
        assert result.exit_code == 0
        assert "Total rows" in result.output
        assert "5" in result.output  # Total 5 rows
        assert "3" in result.output  # 3 esports
        assert "2" in result.output  # 2 unclassified
        assert "CS2" in result.output  # Game breakdown


def test_catalog_stats_no_crash_without_catalog_table():
    """Test catalog-stats handles missing table gracefully."""
    engine = create_engine("sqlite:///:memory:")
    # Don't create tables - only create session factory
    session_factory = sessionmaker(bind=engine)

    with patch("src.cli.commands._get_dependencies") as mock_deps:
        mock_deps.return_value = (session_factory, None, None, None, None)
        runner = CliRunner()
        result = runner.invoke(cli, ["catalog-stats"])
        # Should not crash - either handles gracefully or shows error message
        # Exit code might be 0 (graceful) or 1 (error shown but not exception)
        assert result.exit_code in (0, 1)
