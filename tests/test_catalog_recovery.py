"""Tests for catalog recovery.

Tests the recover_esports_token_gaps() and _fetch_esports_events_index()
functions with mocked httpx and database.
"""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Market, Trade


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_fetch_esports_events_index_returns_dict_format():
    """Test _fetch_esports_events_index returns dict format tokens."""
    from src.catalog.recovery import _fetch_esports_events_index

    mock_events = [
        {
            "markets": [
                {
                    "conditionId": "cond1",
                    "clobTokenIds": ["tid1", "tid2"],
                }
            ]
        }
    ]

    with patch("src.catalog.recovery.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = mock_events

        result = _fetch_esports_events_index()

    assert result == {
        "cond1": [
            {"token_id": "tid1", "outcome": ""},
            {"token_id": "tid2", "outcome": ""},
        ]
    }


def test_fetch_esports_events_index_parses_json_string_clob_token_ids():
    """Test _fetch_esports_events_index parses JSON string clobTokenIds."""
    from src.catalog.recovery import _fetch_esports_events_index

    mock_events = [
        {
            "markets": [
                {
                    "conditionId": "cond1",
                    "clobTokenIds": '["tid1"]',  # JSON string, not list
                }
            ]
        }
    ]

    with patch("src.catalog.recovery.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = mock_events

        result = _fetch_esports_events_index()

    assert result == {
        "cond1": [{"token_id": "tid1", "outcome": ""}]
    }


def test_fetch_esports_events_index_paginates_until_empty():
    """Test _fetch_esports_events_index paginates until empty response."""
    from src.catalog.recovery import _fetch_esports_events_index

    full_page = [{"markets": [{"conditionId": f"cond{i}", "clobTokenIds": [f"tid{i}"]}]} for i in range(200)]
    empty_page = []

    with patch("src.catalog.recovery.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.side_effect = [full_page, empty_page]

        result = _fetch_esports_events_index()

    assert mock_get.call_count == 2
    assert len(result) == 200


def test_recover_no_gap_markets_returns_zero(in_memory_db):
    """Test recover_esports_token_gaps returns zero when no gap markets exist."""
    from src.catalog.recovery import recover_esports_token_gaps

    result = recover_esports_token_gaps(in_memory_db)

    assert result["found"] == 0
    assert result["populated"] == 0
    assert result["already_done"] == 0


def test_recover_populates_tokens_for_gap_market(in_memory_db):
    """Test recover_esports_token_gaps populates tokens for gap market."""
    from src.catalog.recovery import recover_esports_token_gaps

    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond1', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    in_memory_db.commit()

    market = Market(
        condition_id="cond1",
        question="Test market?",
        category="eSports",
        tokens=None,
    )
    in_memory_db.add(market)
    in_memory_db.commit()

    mock_events_index = {
        "cond1": [{"token_id": "tid1", "outcome": ""}]
    }

    with patch("src.catalog.recovery._fetch_esports_events_index", return_value=mock_events_index):
        with patch("src.catalog.patcher.patch_missing_catalog_entries", return_value={"patched": 0, "local": 0, "api": 0, "fallback": 0}):
            result = recover_esports_token_gaps(in_memory_db)

    assert result["found"] == 1
    assert result["populated"] == 1

    in_memory_db.refresh(market)
    assert market.tokens is not None
    tokens = json.loads(market.tokens)
    assert tokens == [{"token_id": "tid1", "outcome": ""}]


def test_recover_skips_already_populated_market(in_memory_db):
    """Test recover_esports_token_gaps skips markets that already have tokens."""
    from src.catalog.recovery import recover_esports_token_gaps

    # This market already has tokens - it's not a gap market
    market = Market(
        condition_id="cond1",
        question="Test market?",
        category="eSports",
        tokens='[{"token_id": "existing", "outcome": ""}]',
    )
    in_memory_db.add(market)
    in_memory_db.commit()

    # Even with a trade, since it has tokens it's not a gap
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond1', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    in_memory_db.commit()

    mock_events_index = {
        "cond1": [{"token_id": "tid1", "outcome": ""}]
    }

    with patch("src.catalog.recovery._fetch_esports_events_index", return_value=mock_events_index):
        with patch("src.catalog.patcher.patch_missing_catalog_entries", return_value={"patched": 0, "local": 0, "api": 0, "fallback": 0}):
            result = recover_esports_token_gaps(in_memory_db)

    # Market has tokens already so it's not a gap market
    assert result["found"] == 0
    assert result["populated"] == 0
    assert result["already_done"] == 0


def test_recover_handles_market_not_in_events_index(in_memory_db):
    """Test recover_esports_token_gaps handles market not in events index."""
    from src.catalog.recovery import recover_esports_token_gaps

    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond1', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    in_memory_db.commit()

    market = Market(
        condition_id="cond1",
        question="Test market?",
        category="eSports",
        tokens=None,
    )
    in_memory_db.add(market)
    in_memory_db.commit()

    mock_events_index = {}  # Empty - cond1 not found

    with patch("src.catalog.recovery._fetch_esports_events_index", return_value=mock_events_index):
        with patch("src.catalog.patcher.patch_missing_catalog_entries", return_value={"patched": 0, "local": 0, "api": 0, "fallback": 0}):
            result = recover_esports_token_gaps(in_memory_db)

    assert result["found"] == 1
    assert result["populated"] == 0

    in_memory_db.refresh(market)
    assert market.tokens is None


def test_recover_idempotent_second_run(in_memory_db):
    """Test recover_esports_token_gaps is idempotent on second run."""
    from src.catalog.recovery import recover_esports_token_gaps

    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond1', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    in_memory_db.commit()

    market = Market(
        condition_id="cond1",
        question="Test market?",
        category="eSports",
        tokens=None,
    )
    in_memory_db.add(market)
    in_memory_db.commit()

    mock_events_index = {
        "cond1": [{"token_id": "tid1", "outcome": ""}]
    }

    # First run - should populate tokens
    with patch("src.catalog.recovery._fetch_esports_events_index", return_value=mock_events_index):
        with patch("src.catalog.patcher.patch_missing_catalog_entries", return_value={"patched": 0, "local": 0, "api": 0, "fallback": 0}):
            result1 = recover_esports_token_gaps(in_memory_db)

    assert result1["populated"] == 1

    # Second run - since tokens are now populated, it's no longer a gap market
    # Should return found=0 (not a gap anymore)
    with patch("src.catalog.recovery._fetch_esports_events_index", return_value=mock_events_index):
        with patch("src.catalog.patcher.patch_missing_catalog_entries", return_value={"patched": 0, "local": 0, "api": 0, "fallback": 0}):
            result2 = recover_esports_token_gaps(in_memory_db)

    # After first run, market has tokens so it's not a gap anymore
    assert result2["found"] == 0
    assert result2["populated"] == 0
