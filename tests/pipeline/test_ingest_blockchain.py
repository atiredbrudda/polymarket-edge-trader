"""Integration tests for blockchain-based trade ingestion.

Tests the integration between PolygonBlockchainClient and IngestionPipeline
for complete trader history backfill without API limitations.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.api.models import MarketResponse
from src.blockchain.models import BlockchainTrade
from src.db.models import Base, BlockchainSyncState, Market, Trader, Trade
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
    """IngestionPipeline with mocked blockchain client."""
    return IngestionPipeline(
        client=mock_api_client,
        session_factory=test_db,
        category_filter=category_filter,
        blockchain_client=mock_blockchain_client,
    )


def test_ingest_trader_history_blockchain_no_client(
    mock_api_client, test_db, category_filter
):
    """Test ValueError raised when blockchain_client not configured."""
    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=test_db,
        category_filter=category_filter,
        blockchain_client=None,
    )

    with pytest.raises(ValueError, match="Blockchain client not configured"):
        pipeline.ingest_trader_history_blockchain("0x1234567890abcdef")


def test_ingest_trader_history_blockchain_success(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Test successful blockchain ingestion with sync state creation."""
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"
    condition_id = "0xabcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"

    # Mock blockchain trade
    blockchain_trade = BlockchainTrade(
        block_number=12345,
        transaction_hash="0xabc123",
        log_index=0,
        order_hash="0xdef456",
        maker=trader_address,
        taker="0xother",
        maker_asset_id=0,  # USDC (is_buy=True)
        taker_asset_id=123456,
        maker_amount=1000000,  # 1 USDC
        taker_amount=2000000,  # 2 tokens
        fee=1000,
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )

    # Mock blockchain client response
    mock_blockchain_client.get_trades_by_trader.return_value = [blockchain_trade]

    # Mock extract_condition_id
    with patch.object(
        BlockchainTrade, "extract_condition_id", return_value=condition_id
    ):
        # Mock API market response
        market_response = MarketResponse(
            condition_id=condition_id,
            question="Test eSports Market",
            category="eSports",
            active=True,
            outcome=None,
            end_date_iso=None,
            tokens=None,
        )
        mock_api_client.get_market.return_value = market_response

        # Execute ingestion
        stats = pipeline.ingest_trader_history_blockchain(trader_address)

        # Verify stats
        assert stats["trades_from_blockchain"] == 1
        assert stats["detail_count"] == 1
        assert stats["already_in_db"] == 0
        assert "eSports" in stats["categories"]

        # Verify database state
        session = test_db()
        try:
            # Check sync state created
            sync_state = (
                session.query(BlockchainSyncState)
                .filter_by(trader_address=trader_address)
                .first()
            )
            assert sync_state is not None
            assert sync_state.last_queried_block == 12345
            assert sync_state.total_trades_found == 1

            # Check trade stored
            trade = session.query(Trade).first()
            assert trade is not None
            assert trade.trader_address == trader_address
            assert trade.side == "BUY"

            # Check trader marked as backfill complete
            trader = session.query(Trader).filter_by(address=trader_address).first()
            assert trader is None  # Not created yet since no prior discovery
        finally:
            session.close()


def test_ingest_trader_history_blockchain_deduplication(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Test deduplication when trades already exist in database."""
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"
    condition_id = "0xabcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"
    trade_id = "0xabc123_0"

    # Pre-populate database with existing trade
    session = test_db()
    try:
        market = Market(
            condition_id=condition_id,
            question="Test Market",
            category="eSports",
            active=True,
        )
        session.add(market)

        existing_trade = Trade(
            market_id=condition_id,
            trader_address=trader_address,
            side="BUY",
            size=Decimal("2.0"),
            price=Decimal("0.5"),
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            trade_id=trade_id,
        )
        session.add(existing_trade)
        session.commit()
    finally:
        session.close()

    # Mock blockchain trade with same trade_id
    blockchain_trade = BlockchainTrade(
        block_number=12345,
        transaction_hash="0xabc123",
        log_index=0,
        order_hash="0xdef456",
        maker=trader_address,
        taker="0xother",
        maker_asset_id=0,
        taker_asset_id=123456,
        maker_amount=1000000,
        taker_amount=2000000,
        fee=1000,
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )

    mock_blockchain_client.get_trades_by_trader.return_value = [blockchain_trade]

    with patch.object(
        BlockchainTrade, "extract_condition_id", return_value=condition_id
    ):
        # Execute ingestion
        stats = pipeline.ingest_trader_history_blockchain(trader_address)

        # Verify deduplication
        assert stats["trades_from_blockchain"] == 1
        assert stats["detail_count"] == 0
        assert stats["already_in_db"] == 1

        # Verify only one trade in database
        session = test_db()
        try:
            trade_count = session.query(Trade).count()
            assert trade_count == 1
        finally:
            session.close()


def test_ingest_trader_history_blockchain_incremental(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Test incremental sync resumes from last queried block."""
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"
    last_block = 10000

    # Pre-populate sync state
    session = test_db()
    try:
        sync_state = BlockchainSyncState(
            trader_address=trader_address,
            last_queried_block=last_block,
            total_trades_found=5,
        )
        session.add(sync_state)
        session.commit()
    finally:
        session.close()

    # Mock blockchain client to return no new trades
    mock_blockchain_client.get_trades_by_trader.return_value = []

    # Execute incremental ingestion
    stats = pipeline.ingest_trader_history_blockchain(
        trader_address, use_incremental=True
    )

    # Verify blockchain client called with from_block = last_block + 1
    mock_blockchain_client.get_trades_by_trader.assert_called_once()
    call_kwargs = mock_blockchain_client.get_trades_by_trader.call_args[1]
    assert call_kwargs["from_block"] == last_block + 1

    # Verify stats for empty result
    assert stats["trades_from_blockchain"] == 0
    assert stats["detail_count"] == 0


def test_ingest_trader_history_hybrid_uses_blockchain_last_resort(
    pipeline, mock_blockchain_client
):
    """Test hybrid method uses blockchain as last resort when other sources fail."""
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"

    # Mock blockchain client to return empty list
    mock_blockchain_client.get_trades_by_trader.return_value = []

    # Execute hybrid ingestion with blockchain as last resort
    # (no jbecker_client configured, so it will fall through to blockchain)
    stats = pipeline.ingest_trader_history_hybrid(
        trader_address, fallback_to_blockchain=True
    )

    # Verify blockchain method was called (as fallback when no JBecker/API data)
    mock_blockchain_client.get_trades_by_trader.assert_called_once()


def test_ingest_trader_history_hybrid_falls_back_to_api(
    mock_api_client, test_db, category_filter
):
    """Test hybrid method falls back to API when blockchain unavailable."""
    trader_address = "0x1234567890abcdef1234567890abcdef12345678"

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=test_db,
        category_filter=category_filter,
        blockchain_client=None,
    )

    # Mock API client
    mock_api_client.get_trader_trades.return_value = []

    # Execute hybrid ingestion (blockchain unavailable, so API is used)
    stats = pipeline.ingest_trader_history_hybrid(
        trader_address, fallback_to_blockchain=False
    )

    # Verify API method was called
    mock_api_client.get_trader_trades.assert_called_once_with(trader_address)


def test_run_full_sweep_with_blockchain(
    pipeline, mock_api_client, mock_blockchain_client, test_db
):
    """Test run_full_sweep uses blockchain for backfill when flag set.

    Note: After Phase 9 JBecker integration, blockchain is used as LAST RESORT
    in the hybrid tier (JBecker -> API -> Graph -> Blockchain). This test
    verifies blockchain fallback still works when JBecker client is None.
    """
    # Pre-populate database with trader needing backfill
    session = test_db()
    try:
        trader = Trader(
            address="0x1234567890abcdef1234567890abcdef12345678",
            backfill_complete=False,
        )
        session.add(trader)
        session.commit()
    finally:
        session.close()

    # Mock API client for market ingestion
    mock_api_client.get_market.return_value = None  # Return None to skip test market
    mock_api_client.get_markets.return_value = []

    # Mock blockchain client for trader backfill
    mock_blockchain_client.get_trades_by_trader.return_value = []

    # Execute sweep with JBecker disabled (None), blockchain as fallback
    # This tests backward compatibility from Phase 8
    stats = pipeline.run_full_sweep(
        use_jbecker=False,  # Disable JBecker tier (pipeline.jbecker_client is already None)
        use_blockchain_fallback=True,
    )

    # Verify blockchain client was called for trader backfill
    assert mock_blockchain_client.get_trades_by_trader.called
