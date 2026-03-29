"""Pytest fixtures for Polymarket Analytics integration tests.

Provides:
- test_db: Temporary SQLite database with schema initialized
- niche_config: Validated esports configuration
- sample_token_catalog: Sample token data for fixture ingestion
"""

from pathlib import Path

import pytest
import sqlite_utils

from src.polymarket_analytics.config.loader import load_niche_config
from src.polymarket_analytics.db.schema import init_database


@pytest.fixture
def test_db(tmp_path: Path) -> sqlite_utils.Database:
    """Create temporary database with schema initialized.

    Args:
        tmp_path: Pytest-provided temporary directory path

    Yields:
        sqlite_utils.Database instance with all tables created

    The database is automatically cleaned up when the test completes
    (tmp_path handles cleanup).
    """
    db_path = tmp_path / "test.db"
    db = init_database(db_path)
    yield db


@pytest.fixture
def niche_config() -> dict:
    """Load validated esports configuration.

    Returns:
        NicheConfig instance for esports niche
    """
    config_path = Path("niches/esports.yaml")
    return load_niche_config(config_path)


@pytest.fixture
def sample_token_catalog() -> list[dict]:
    """Return sample token data for fixture ingestion.

    Returns:
        List of sample token entries for eSports markets

    Each entry contains:
        - token_id: Polymarket token ID (hex string)
        - condition_id: Market condition identifier
        - question: Market question text
        - niche_slug: Niche category slug
        - node_path: Hierarchy path for navigation
    """
    return [
        {
            "token_id": "0x1a2b3c4d5e6f",
            "condition_id": "esports-iem-katowice-faze-vs-navi",
            "question": "Will FaZe win IEM Katowice 2025?",
            "niche_slug": "esports",
            "node_path": "esports/cs2/iem-katowice-2025/final",
        },
        {
            "token_id": "0x2b3c4d5e6f7a",
            "condition_id": "esports-lol-worlds-t1-vs-geng",
            "question": "Will T1 win Worlds 2025?",
            "niche_slug": "esports",
            "node_path": "esports/lol/worlds-2025/final",
        },
        {
            "token_id": "0x3c4d5e6f7a8b",
            "condition_id": "esports-dota2-ti-team-liquid",
            "question": "Will Team Liquid win TI 2025?",
            "niche_slug": "esports",
            "node_path": "esports/dota2/ti-2025/final",
        },
    ]
