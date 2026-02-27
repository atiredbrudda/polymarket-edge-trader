"""Tests for catalog patcher.

Tests the patch_missing_catalog_entries() function with mocked session and API.
Verifies:
- 3-tier detection and patch logic (local, API, fallback)
- Both token IDs inserted per binary market
- Idempotency on second run
- Category handling for esports, sports, politics, unknown
"""

import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, TokenCatalog, Market, GammaEvent


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_no_gaps_returns_zero(in_memory_db):
    """Test that function returns zero counts when no gaps exist."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO token_catalog (token_id, condition_id, question, niche_slug)
        VALUES ('token1', 'cond1', 'Test market?', 'esports')
    """))
    in_memory_db.commit()
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=None)
    
    assert result["patched"] == 0
    assert result["local"] == 0
    assert result["api"] == 0
    assert result["fallback"] == 0


def test_tier1_local_hit(in_memory_db):
    """Test Tier 1: local gamma_events lookup resolves the gap."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO gamma_events (event_id, clob_token_ids, tags, created_at, updated_at)
        VALUES ('evt1', '["token123"]', '[{"slug": "esports"}, {"slug": "dota-2"}]', datetime('now'), datetime('now'))
    """))
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond1', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    in_memory_db.commit()
    
    market = Market(
        condition_id="cond1",
        question="Test market?",
        category="eSports",
        tokens=json.dumps([{"token_id": "token123", "outcome": ""}])
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=None)
    
    assert result["local"] == 1
    tokens = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond1"
    ).all()
    assert len(tokens) > 0
    for token in tokens:
        if token.node_path:
            assert token.node_path.startswith("esports")


def test_tier1_null_tokens_falls_to_tier2(in_memory_db):
    """Test Tier 1 skipped when market.tokens is NULL - falls to Tier 2 API."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond1', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond1",
        question="Test market?",
        category="esports",
        tokens=None
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{
        "conditionId": "cond1",
        "clobTokenIds": ["token999"],
        "tags": [{"slug": "esports"}, {"slug": "cs2"}],
        "question": "Test market?"
    }]
    mock_httpx_get.return_value = mock_response
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    assert result["api"] == 1
    assert result["local"] == 0


def test_tier2_api_hit_with_esports_tags(in_memory_db):
    """Test Tier 2: API returns eSports tags, node_path extracted."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_api', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_api",
        question="CS2 match?",
        category="esports",
        tokens=None
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{
        "conditionId": "cond_api",
        "clobTokenIds": ["tokenA", "tokenB"],
        "tags": [{"slug": "esports"}, {"slug": "cs2"}],
        "question": "CS2 match?"
    }]
    mock_httpx_get.return_value = mock_response
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    assert result["api"] == 1
    tokens = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_api"
    ).all()
    assert len(tokens) == 2
    for token in tokens:
        if token.node_path:
            assert "esports" in token.node_path


def test_tier2_api_hit_no_esports_tags(in_memory_db):
    """Test Tier 2: API returns non-esports tags, fallback to niche_slug from tag."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_politics', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_politics",
        question="Election?",
        category="Politics",
        tokens=None
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{
        "conditionId": "cond_politics",
        "clobTokenIds": ["tokenX"],
        "tags": [{"slug": "politics"}, {"slug": "us-election"}],
        "question": "Election?"
    }]
    mock_httpx_get.return_value = mock_response
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    assert result["api"] == 1
    tokens = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_politics"
    ).all()
    assert len(tokens) == 1
    assert tokens[0].node_path is None
    assert tokens[0].niche_slug is not None


def test_tier3_fallback_on_api_failure(in_memory_db):
    """Test Tier 3: API fails, fallback to category-only insert."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_fallback', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_fallback",
        question="Sports bet?",
        category="Sports",
        tokens=json.dumps([{"token_id": "token_sport", "outcome": ""}])
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_httpx_get.side_effect = Exception("API Error")
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    assert result["fallback"] == 1
    tokens = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_fallback"
    ).all()
    assert len(tokens) >= 1
    assert tokens[0].node_path is None
    assert tokens[0].niche_slug is not None


def test_idempotent_second_run_inserts_nothing(in_memory_db):
    """Test that second run with same state returns patched=0 (idempotent)."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO token_catalog (token_id, condition_id, question, niche_slug)
        VALUES ('token1', 'cond_done', 'Already patched', 'esports')
    """))
    in_memory_db.commit()
    
    result1 = patch_missing_catalog_entries(in_memory_db, gamma_client=None)
    
    assert result1["patched"] == 0


def test_both_token_ids_inserted_per_condition(in_memory_db):
    """Test that both YES and NO token IDs are inserted per binary market."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_binary', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_binary",
        question="Binary market?",
        category="esports",
        tokens=None
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{
        "conditionId": "cond_binary",
        "clobTokenIds": ["token_yes", "token_no"],
        "tags": [{"slug": "esports"}],
        "question": "Binary market?"
    }]
    mock_httpx_get.return_value = mock_response
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    tokens = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_binary"
    ).all()
    assert len(tokens) == 2
    token_ids = {t.token_id for t in tokens}
    assert "token_yes" in token_ids
    assert "token_no" in token_ids


def test_niche_slug_from_category_sports(in_memory_db):
    """Test niche_slug derived from market.category when API fails."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_sport', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_sport",
        question="NBA bet?",
        category="Sports",
        tokens=json.dumps([{"token_id": "token_nba", "outcome": ""}])
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_httpx_get.side_effect = Exception("API down")
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    assert result["fallback"] == 1
    token = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_sport"
    ).first()
    assert token.niche_slug == "sports"


def test_esports_category_case_insensitive(in_memory_db):
    """Test that 'esports' (lowercase) is handled like 'eSports'."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_lower', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_lower",
        question="Dota bet?",
        category="esports",
        tokens=json.dumps([{"token_id": "token_dota", "outcome": ""}])
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=None)
    
    assert result["fallback"] == 1
    token = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_lower"
    ).first()
    assert token.niche_slug == "esports"


def test_unknown_category_uses_api_tag(in_memory_db):
    """Test that Unknown category uses niche_slug from API tag if available."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_unknown', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_unknown",
        question="Crypto bet?",
        category="Unknown",
        tokens=None
    )
    in_memory_db.add(market)
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{
        "conditionId": "cond_unknown",
        "clobTokenIds": ["token_crypto"],
        "tags": [{"slug": "crypto"}],
        "question": "Crypto bet?"
    }]
    mock_httpx_get.return_value = mock_response
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    token = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_unknown"
    ).first()
    assert token.niche_slug == "crypto"


def test_full_patch_flow_integration(in_memory_db):
    """Integration test: in-memory DB with mocked API, full patch flow."""
    from src.catalog.patcher import patch_missing_catalog_entries
    
    in_memory_db.execute(text("""
        INSERT INTO trades (id, market_id, trader_address, side, size, price, timestamp, created_at)
        VALUES (1, 'cond_full', '0xABC', 'BUY', 100, 0.5, datetime('now'), datetime('now'))
    """))
    
    market = Market(
        condition_id="cond_full",
        question="Integration test?",
        category="esports",
        tokens=None
    )
    in_memory_db.add(market)
    
    in_memory_db.execute(text("""
        INSERT INTO gamma_events (event_id, clob_token_ids, tags, created_at, updated_at)
        VALUES ('evt_full', '[]', '[]', datetime('now'), datetime('now'))
    """))
    in_memory_db.commit()
    
    mock_gamma_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{
        "conditionId": "cond_full",
        "clobTokenIds": ["token_int_yes", "token_int_no"],
        "tags": [{"slug": "esports"}, {"slug": "valorant"}],
        "question": "Integration test?"
    }]
    mock_httpx_get.return_value = mock_response
    
    result = patch_missing_catalog_entries(in_memory_db, gamma_client=mock_gamma_client)
    
    assert result["patched"] >= 1
    tokens = in_memory_db.query(TokenCatalog).filter(
        TokenCatalog.condition_id == "cond_full"
    ).all()
    assert len(tokens) == 2
