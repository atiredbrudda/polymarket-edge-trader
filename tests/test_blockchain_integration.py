"""End-to-end integration tests for blockchain + API pipeline integration.

Tests the complete flow: discovery via API -> complete history via blockchain.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.api.models import MarketResponse, TradeResponse
from src.blockchain.models import BlockchainTrade
from src.db.models import Base, Market, Trade
from src.pipeline.filters import CategoryFilter
from src.pipeline.ingest import IngestionPipeline


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


@pytest.fixture
def mock_api_client():
    """Mock Polymarket API client."""
    client = Mock(spec=PolymarketClient)
    return client


@pytest.fixture
def mock_blockchain_client():
    """Mock blockchain client."""
    client = Mock()
    return client


@pytest.fixture
def category_filter():
    """CategoryFilter configured for eSports detail."""
    return CategoryFilter(detail_categories=["eSports"])


@pytest.fixture
def pipeline(mock_api_client, test_db, category_filter, mock_blockchain_client):
    """IngestionPipeline with both API and blockchain clients."""
    return IngestionPipeline(
        client=mock_api_client,
        session_factory=test_db,
        category_filter=category_filter,
        blockchain_client=mock_blockchain_client,
    )


def test_end_to_end_blockchain_ingestion(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Test complete flow: market discovery -> trader discovery -> blockchain backfill.

    This simulates the full pipeline:
    1. Discover markets from API
    2. Discover traders from market trades
    3. Backfill trader history from blockchain
    """
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"
    condition_id = "0xabcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"

    # Step 1: Mock market discovery
    market_response = MarketResponse(
        condition_id=condition_id,
        question="Test eSports Market: Team A vs Team B",
        category="eSports",
        active=True,
        outcome=None,
        end_date_iso=None,
        tokens=None,
    )

    # Step 2: Mock trader discovery from market trades
    api_trade = TradeResponse(
        id="api_trade_1",
        market=condition_id,
        trader=trader_address,
        side="BUY",
        size=Decimal("1.0"),
        price=Decimal("0.6"),
        timestamp=datetime(2024, 1, 1, 10, 0, 0),
        asset_ticker="YES",
    )

    # Step 3: Mock blockchain backfill with MORE trades than API
    blockchain_trades = [
        BlockchainTrade(
            block_number=12340 + i,
            transaction_hash=f"0xtx{i}",
            log_index=0,
            order_hash=f"0xorder{i}",
            maker=trader_address,
            taker="0xother",
            maker_asset_id=0,
            taker_asset_id=123456,
            maker_amount=1000000 * (i + 1),
            taker_amount=2000000 * (i + 1),
            fee=1000,
            timestamp=datetime(2024, 1, 1, 12, 0, i),
        )
        for i in range(5)
    ]

    # Configure mocks
    mock_api_client.get_market.return_value = market_response
    mock_api_client.get_market_trades.return_value = [api_trade]
    mock_blockchain_client.get_trades_by_trader.return_value = blockchain_trades

    # Manually simulate market ingestion and trader discovery
    session = test_db()
    try:
        # Add market
        market = Market(
            condition_id=condition_id,
            question=market_response.question,
            category=market_response.category,
            active=True,
        )
        session.add(market)
        session.commit()
    finally:
        session.close()

    # Discover traders from market
    new_traders = pipeline.discover_traders_from_market(condition_id)
    assert trader_address in new_traders

    # Backfill trader history using blockchain
    with patch.object(
        BlockchainTrade, "extract_condition_id", return_value=condition_id
    ):
        stats = pipeline.ingest_trader_history_blockchain(trader_address)

        # Verify blockchain returned more trades
        assert stats["trades_from_blockchain"] == 5
        assert stats["detail_count"] > 0

        # Verify database state
        session = test_db()
        try:
            trade_count = session.query(Trade).filter_by(
                trader_address=trader_address
            ).count()
            # Should have: 1 from discovery + 5 from blockchain (minus any duplicates)
            assert trade_count >= 5
        finally:
            session.close()


def test_blockchain_vs_api_trade_count(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Verify blockchain ingestion stores more trades than API limit.

    API has 100-trade limit. Blockchain has no limit.
    """
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"
    condition_id = "0xabcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"

    # Mock API returns 100 trades (simulating the limit)
    api_trades = [
        TradeResponse(
            id=f"api_trade_{i}",
            market=condition_id,
            trader=trader_address,
            side="BUY" if i % 2 == 0 else "SELL",
            size=Decimal("1.0"),
            price=Decimal("0.5"),
            timestamp=datetime(2024, 1, 1, 10, 0, i % 60),
            asset_ticker="YES",
        )
        for i in range(100)
    ]

    # Mock blockchain returns 150 trades (more than API limit)
    # All BUY trades to keep price consistent at 0.5
    blockchain_trades = [
        BlockchainTrade(
            block_number=12300 + i,
            transaction_hash=f"0xblockchain_tx_{i}",
            log_index=0,
            order_hash=f"0xorder{i}",
            maker=trader_address,
            taker="0xother",
            maker_asset_id=0,  # Always USDC (BUY)
            taker_asset_id=123456,
            maker_amount=1000000,  # 1 USDC
            taker_amount=2000000,  # 2 tokens -> price = 0.5
            fee=1000,
            timestamp=datetime(2024, 1, 1, 12, 0, i % 60),
        )
        for i in range(150)
    ]

    # Pre-populate market
    session = test_db()
    try:
        market = Market(
            condition_id=condition_id,
            question="Test Market",
            category="eSports",
            active=True,
        )
        session.add(market)
        session.commit()
    finally:
        session.close()

    mock_api_client.get_trader_trades.return_value = api_trades
    mock_api_client.get_market.return_value = MarketResponse(
        condition_id=condition_id,
        question="Test Market",
        category="eSports",
        active=True,
        outcome=None,
        end_date_iso=None,
        tokens=None,
    )
    mock_blockchain_client.get_trades_by_trader.return_value = blockchain_trades

    # First: Ingest via API (should get 100 trades)
    api_stats = pipeline.ingest_trader_history(trader_address)
    assert api_stats["detail_count"] == 100

    # Verify API trade count
    session = test_db()
    try:
        api_trade_count = session.query(Trade).filter_by(
            trader_address=trader_address
        ).count()
        assert api_trade_count == 100
    finally:
        session.close()

    # Clear blockchain client mock call count
    mock_blockchain_client.reset_mock()

    # Second: Ingest via blockchain (should get 150 trades)
    # Note: Blockchain trade IDs are different from API trade IDs (tx_hash_logindex vs api_trade_N)
    # So there won't be duplicates unless we reuse the same blockchain trades
    with patch.object(
        BlockchainTrade, "extract_condition_id", return_value=condition_id
    ):
        blockchain_stats = pipeline.ingest_trader_history_blockchain(trader_address)
        assert blockchain_stats["trades_from_blockchain"] == 150
        # In this test, blockchain trade IDs are unique, so no duplicates
        assert blockchain_stats["detail_count"] == 150  # All new trades stored

    # Verify total trades in database
    session = test_db()
    try:
        total_trades = session.query(Trade).filter_by(
            trader_address=trader_address
        ).count()
        assert total_trades == 250  # 100 from API + 150 from blockchain
    finally:
        session.close()


def test_blockchain_ingestion_with_mixed_categories(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Test blockchain ingestion routes trades correctly by category.

    eSports trades -> detail storage
    Other categories -> summary storage
    """
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"
    esports_condition = "0xaaaa1234567890abcdef1234567890abcdef1234567890abcdef1234567890aa"
    politics_condition = "0xbbbb1234567890abcdef1234567890abcdef1234567890abcdef1234567890bb"

    # Mock 3 eSports trades + 2 Politics trades
    blockchain_trades = [
        BlockchainTrade(
            block_number=12340 + i,
            transaction_hash=f"0xtx_esports_{i}",
            log_index=0,
            order_hash=f"0xorder_{i}",
            maker=trader_address,
            taker="0xother",
            maker_asset_id=0,
            taker_asset_id=123456,
            maker_amount=1000000,
            taker_amount=2000000,
            fee=1000,
            timestamp=datetime(2024, 1, 1, 12, 0, i),
        )
        for i in range(3)
    ] + [
        BlockchainTrade(
            block_number=12350 + i,
            transaction_hash=f"0xtx_politics_{i}",
            log_index=0,
            order_hash=f"0xorder_politics_{i}",
            maker=trader_address,
            taker="0xother",
            maker_asset_id=0,
            taker_asset_id=234567,
            maker_amount=1000000,
            taker_amount=2000000,
            fee=1000,
            timestamp=datetime(2024, 1, 2, 12, 0, i),
        )
        for i in range(2)
    ]

    # Pre-populate markets
    session = test_db()
    try:
        esports_market = Market(
            condition_id=esports_condition,
            question="eSports Market",
            category="eSports",
            active=True,
        )
        politics_market = Market(
            condition_id=politics_condition,
            question="Politics Market",
            category="Politics",
            active=True,
        )
        session.add(esports_market)
        session.add(politics_market)
        session.commit()
    finally:
        session.close()

    mock_blockchain_client.get_trades_by_trader.return_value = blockchain_trades

    # Mock extract_condition_id to alternate between conditions
    def mock_extract(self):
        if "esports" in self.transaction_hash:
            return esports_condition
        return politics_condition

    with patch.object(BlockchainTrade, "extract_condition_id", mock_extract):
        stats = pipeline.ingest_trader_history_blockchain(trader_address)

        # Verify routing
        assert stats["trades_from_blockchain"] == 5
        assert "eSports" in stats["categories"]
        assert "Politics" in stats["categories"]
        # 3 eSports trades go to detail storage
        assert stats["detail_count"] == 3
        # 2 Politics trades go to summary storage
        assert stats["summary_count"] == 1  # One summary per category
