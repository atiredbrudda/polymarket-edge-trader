"""Pytest fixtures for Polymarket Analytics integration tests.

Provides:
- test_db: Temporary SQLite database with schema initialized
- niche_config: Validated esports configuration
- sample_token_catalog: Sample token data for fixture ingestion
- Detection test helpers: create_q5_trader, create_position, create_market
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib

import pytest
import sqlite_utils

from polymarket_analytics.config.loader import load_niche_config
from polymarket_analytics.db.schema import init_database

# Fixed timestamp used across detection test helpers so all traders share the same
# computed_at — simulating a single scoring run. Required for MAX(computed_at)
# filter in convergence query to match all test traders, not just the last inserted.
_FIXED_COMPUTED_AT = "2026-01-01T12:00:00Z"


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


# =============================================================================
# Detection Test Helpers
# =============================================================================
# Helper functions for signal detection tests (Phase 6)
# These reduce duplication and make tests more readable.


def create_q5_trader(
    db: sqlite_utils.Database,
    trader_address: str,
    niche_slug: str,
    composite_score: float = 1.5,
) -> str:
    """Helper function to create a Q5 trader with lift_scores record.

    Args:
        db: sqlite-utils Database instance
        trader_address: Trader wallet address
        niche_slug: Niche category (e.g., 'esports')
        composite_score: Composite score for the trader

    Returns:
        trader_address for chaining
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db["traders"].insert(
        {
            "address": trader_address,
            "backfill_complete": 1,
            "first_seen": now,
            "last_seen": now,
            "created_at": now,
        },
        replace=True,
    )

    db["lift_scores"].insert(
        {
            "trader_address": trader_address,
            "category": niche_slug,
            "composite_score": composite_score,
            "clv_raw": 0.5,
            "clv_zscore": 1.0,
            "roi_raw": 0.3,
            "roi_zscore": 0.8,
            "sharpe_raw": 1.2,
            "sharpe_zscore": 0.7,
            "quintile": 5,
            "position_count": 10,
            "total_pnl": 500.0,
            "window_start": now,
            "window_end": now,
            "computed_at": _FIXED_COMPUTED_AT,
        },
        replace=True,
    )

    return trader_address


def create_qn_trader(
    db: sqlite_utils.Database,
    trader_address: str,
    niche_slug: str,
    quintile: int,
    composite_score: float = 0.5,
) -> None:
    """Helper function to create a non-Q5 trader with lift_scores record.

    Args:
        db: sqlite_utils Database instance
        trader_address: Trader wallet address
        niche_slug: Niche category (e.g., 'esports')
        quintile: Quintile value (1-4)
        composite_score: Composite score for the trader
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db["traders"].insert(
        {
            "address": trader_address,
            "backfill_complete": 1,
            "first_seen": now,
            "last_seen": now,
            "created_at": now,
        },
        replace=True,
    )

    db["lift_scores"].insert(
        {
            "trader_address": trader_address,
            "category": niche_slug,
            "composite_score": composite_score,
            "clv_raw": 0.1,
            "clv_zscore": -0.5,
            "roi_raw": 0.05,
            "roi_zscore": -0.3,
            "sharpe_raw": 0.2,
            "sharpe_zscore": -0.2,
            "quintile": quintile,
            "position_count": 5,
            "total_pnl": 50.0,
            "window_start": now,
            "window_end": now,
            "computed_at": _FIXED_COMPUTED_AT,
        },
        replace=True,
    )


def create_position(
    db: sqlite_utils.Database,
    trader_address: str,
    market_id: str,
    direction: str,
    size: float,
    avg_entry_price: float = 0.5,
    resolved: bool = False,
    outcome: str = None,
    pnl: float = None,
    entry_timestamp: str = None,
    last_trade_timestamp: str = None,
) -> dict:
    """Helper function to create a position record.

    Args:
        db: sqlite-utils Database instance
        trader_address: Trader wallet address
        market_id: Market condition ID
        direction: LONG or SHORT
        size: Position size (use 0 for FLAT)
        avg_entry_price: Average entry price
        resolved: Whether position is resolved
        outcome: WIN/LOSS/None
        pnl: Profit/loss value
        entry_timestamp: Entry timestamp (ISO format)
        last_trade_timestamp: Last trade timestamp (ISO format)

    Returns:
        Position data dict
    """
    now = datetime.now(timezone.utc)
    entry_ts = entry_timestamp or (now - timedelta(days=10)).isoformat().replace(
        "+00:00", "Z"
    )
    last_trade_ts = last_trade_timestamp or now.isoformat().replace("+00:00", "Z")

    position_id = hashlib.sha256(
        f"{trader_address}{market_id}{direction}".encode()
    ).hexdigest()[:16]

    position_data = {
        "id": position_id,
        "trader_address": trader_address,
        "market_id": market_id,
        "direction": direction,
        "size": size,
        "avg_entry_price": avg_entry_price,
        "entry_timestamp": entry_ts,
        "last_trade_timestamp": last_trade_ts,
        "trade_count": 1,
        "resolved": 1 if resolved else 0,
        "outcome": outcome,
        "pnl": pnl,
    }

    db["positions"].insert(position_data, replace=True)
    return position_data


def create_market(
    db: sqlite_utils.Database,
    condition_id: str,
    niche_slug: str,
    outcome: str = None,
    end_date: str = None,
) -> None:
    """Helper function to create a market record.

    Args:
        db: sqlite-utils Database instance
        condition_id: Market condition ID
        niche_slug: Niche category
        outcome: Market outcome (YES/NO/None for unresolved)
        end_date: Market end date (ISO format). Defaults to yesterday if not provided.
    """
    now = datetime.now(timezone.utc)
    db["markets"].insert(
        {
            "condition_id": condition_id,
            "question": f"Test market: {condition_id}",
            "category": niche_slug,
            "niche_slug": niche_slug,
            "outcome": outcome,
            "end_date": end_date
            or (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "active": outcome is None,
            "tokens": "[]",
            "created_at": (now - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        },
        replace=True,
    )
