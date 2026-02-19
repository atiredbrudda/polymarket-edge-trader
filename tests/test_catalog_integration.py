"""Integration tests for catalog-backed JBecker backfill path."""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    Market,
    MarketClassification,
    TokenCatalog,
    Trader,
    TaxonomyNode,
)
from src.pipeline.filters import CategoryFilter
from src.pipeline.ingest import IngestionPipeline


MOCK_JBECKER_TRADE = {
    "id": "trade_001",
    "maker": "0xtrader123456789012345678901234567890abcd",
    "taker": "0xexchange456789012345678901234567890abcdef",
    "maker_asset_id": "111",
    "taker_asset_id": "222",
    "maker_amount": "1000000",
    "taker_amount": "700000",
    "timestamp": 1700000000,
    "block_number": 50000000,
    "transaction_hash": "0xabcdef1234567890",
    "order_hash": "0xfedcba0987654321",
    "side": "BUY",
    "price": "0.65",
    "_fetched_at": "2024-01-01T00:00:00",
    "_contract": "ctf_exchange",
}


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def pipeline(in_memory_db):
    """Create IngestionPipeline with mocked clients."""
    mock_api_client = Mock()
    mock_jbecker_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=lambda: in_memory_db,
        category_filter=category_filter,
        jbecker_client=mock_jbecker_client,
    )
    pipeline._catalog_built = True  # Skip actual catalog build
    return pipeline


def test_catalog_lookup_creates_market_record(in_memory_db, pipeline):
    """Test that catalog lookup creates Market + MarketClassification records."""
    catalog_entry = TokenCatalog(
        token_id="111",
        condition_id="cond_abc",
        question="Will NaVi win IEM Katowice?",
        niche_slug="esports",
        node_path="eSports.CS2.IEM Katowice",
        depth=2,
        market_type="match",
    )
    in_memory_db.add(catalog_entry)

    trader = Trader(
        address="0xtrader123456789012345678901234567890abcd",
        first_seen=datetime.utcnow(),
        last_active=datetime.utcnow(),
    )
    in_memory_db.add(trader)
    in_memory_db.commit()

    pipeline.jbecker_client.query_trader_history.return_value = [MOCK_JBECKER_TRADE]

    stats = pipeline.ingest_trader_history_jbecker(
        "0xtrader123456789012345678901234567890abcd",
        token_cache=({}, {}),
    )

    market = in_memory_db.query(Market).filter_by(condition_id="cond_abc").first()
    assert market is not None
    assert market.question == "Will NaVi win IEM Katowice?"
    assert market.category == "eSports"

    classification = (
        in_memory_db.query(MarketClassification).filter_by(market_id="cond_abc").first()
    )
    assert classification is not None
    assert classification.node_path == "eSports.CS2.IEM Katowice"


def test_catalog_lookup_skips_duplicate_market(in_memory_db, pipeline):
    """Test that check-first pattern prevents duplicate Market rows."""
    catalog_entry = TokenCatalog(
        token_id="111",
        condition_id="cond_abc",
        question="Will NaVi win?",
        niche_slug="esports",
        node_path="eSports.CS2",
        depth=1,
        market_type="match",
    )
    in_memory_db.add(catalog_entry)

    existing_market = Market(
        condition_id="cond_abc",
        question="Will NaVi win?",
        category="eSports",
        active=False,
    )
    in_memory_db.add(existing_market)

    trader = Trader(
        address="0xtrader123456789012345678901234567890abcd",
        first_seen=datetime.utcnow(),
        last_active=datetime.utcnow(),
    )
    in_memory_db.add(trader)
    in_memory_db.commit()

    pipeline.jbecker_client.query_trader_history.return_value = [MOCK_JBECKER_TRADE]

    stats = pipeline.ingest_trader_history_jbecker(
        "0xtrader123456789012345678901234567890abcd",
        token_cache=({}, {}),
    )

    markets = in_memory_db.query(Market).filter_by(condition_id="cond_abc").all()
    assert len(markets) == 1


def test_catalog_miss_falls_to_existing_path(in_memory_db, pipeline):
    """Test that tokens not in catalog fall through to Gamma API path."""
    in_memory_db.query(TokenCatalog).delete()

    trader = Trader(
        address="0xtrader123456789012345678901234567890abcd",
        first_seen=datetime.utcnow(),
        last_active=datetime.utcnow(),
    )
    in_memory_db.add(trader)
    in_memory_db.commit()

    pipeline.jbecker_client.query_trader_history.return_value = [MOCK_JBECKER_TRADE]
    pipeline.gamma_client = None

    stats = pipeline.ingest_trader_history_jbecker(
        "0xtrader123456789012345678901234567890abcd",
        token_cache=({}, {}),
    )

    assert stats["skipped_invalid"] >= 1


def test_catalog_built_flag_cached(in_memory_db):
    """Test that _catalog_built flag prevents repeated catalog builds."""
    mock_api_client = Mock()
    mock_jbecker_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=lambda: in_memory_db,
        category_filter=category_filter,
        jbecker_client=mock_jbecker_client,
    )

    assert pipeline._catalog_built is False

    pipeline._catalog_built = True
    pipeline.jbecker_client.query_trader_history.return_value = []

    stats = pipeline.ingest_trader_history_jbecker(
        "0xtrader123456789012345678901234567890abcd",
        token_cache=({}, {}),
    )

    assert pipeline._catalog_built is True


def test_zero_token_id_skipped(in_memory_db, pipeline):
    """Test that token_id '0' (USDC side) is not in catalog path."""
    zero_trade = {
        "id": "trade_002",
        "maker": "0xtrader123456789012345678901234567890abcd",
        "taker": "0xexchange",
        "maker_asset_id": "0",
        "taker_asset_id": "222",
        "maker_amount": "1000000",
        "taker_amount": "700000",
        "timestamp": 1700000000,
        "block_number": 50000000,
        "transaction_hash": "0xabcdef",
        "order_hash": "0xfedcba",
        "side": "BUY",
        "price": "0.65",
    }

    trader = Trader(
        address="0xtrader123456789012345678901234567890abcd",
        first_seen=datetime.utcnow(),
        last_active=datetime.utcnow(),
    )
    in_memory_db.add(trader)
    in_memory_db.commit()

    pipeline.jbecker_client.query_trader_history.return_value = [zero_trade]

    stats = pipeline.ingest_trader_history_jbecker(
        "0xtrader123456789012345678901234567890abcd",
        token_cache=({}, {}),
    )

    markets = in_memory_db.query(Market).all()
    for m in markets:
        assert m.condition_id != "0"
