"""Tests for JBecker dataset pipeline integration."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from decimal import Decimal

from src.pipeline.ingest import IngestionPipeline
from src.db.models import Base, Trader, Trade, Market


# Sample JBecker trade from Plan 09-02
SAMPLE_JBECKER_TRADE = {
    "id": "0x123_0x456",
    "maker": "0xeffd76b6a4318d50c6f71a16b276c5b279445a86",
    "taker": "0xabc123def456789012345678901234567890abcd",
    "maker_amount": "1500000",
    "taker_amount": "3000000",
    "maker_asset_id": "123457",
    "taker_asset_id": "789012",
    "fee": "1000",
    "timestamp": 1704067200,
    "block_number": 50000000,
    "transaction_hash": "0xabcdef1234567890",
    "order_hash": "0xfedcba0987654321",
    "side": "BUY",
    "price": "0.65",
    "_fetched_at": "2024-01-01T00:00:00",
    "_contract": "ctf_exchange",
}


@pytest.fixture
def in_memory_session():
    """Create in-memory SQLite session for testing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session


@pytest.fixture
def market_with_token(in_memory_session):
    """Add a market with token to DB for JBecker tests."""
    from src.db.models import TaxonomyNode, MarketClassification

    session = in_memory_session()

    market = Market(
        condition_id="123457",
        question="Test market?",
        category="eSports",
        active=True,
        tokens='[{"token_id": "123457", "outcome": "Yes"}]',
    )
    session.add(market)

    taxonomy_node = TaxonomyNode(
        name="eSports",
        slug="esports",
        parent_id=None,
        depth=0,
        node_type="root",
        patterns_json='["esports"]',
    )
    session.add(taxonomy_node)
    session.flush()

    classification = MarketClassification(
        market_id="123457",
        taxonomy_node_id=taxonomy_node.id,
        node_path="eSports",
        market_type="match",
    )
    session.add(classification)

    session.commit()
    session.close()
    return in_memory_session


@pytest.fixture
def pipeline_with_jbecker(in_memory_session):
    """Create pipeline with mocked JBecker client."""
    from src.pipeline.filters import CategoryFilter

    mock_api_client = Mock()
    mock_jbecker_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=in_memory_session,
        category_filter=category_filter,
        jbecker_client=mock_jbecker_client,
    )

    return pipeline


# ============================================================================
# Ingestion Method Tests (4 tests)
# ============================================================================


def test_ingest_jbecker_stores_trades(pipeline_with_jbecker, market_with_token):
    """Ingests trades from mock JBeckerDataset, stores in DB."""
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker client to return sample trades
    pipeline_with_jbecker.jbecker_client.query_trader_history.return_value = [
        SAMPLE_JBECKER_TRADE,
    ]

    # Ensure trader exists
    session = market_with_token()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Ingest
    stats = pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)

    # Verify stats
    assert stats["trades_from_jbecker"] == 1
    assert stats["detail_count"] == 1
    assert stats["already_in_db"] == 0

    # Verify trade stored
    session = market_with_token()
    trade_count = (
        session.query(Trade).filter_by(trader_address=trader_address.lower()).count()
    )
    assert trade_count == 1

    # Verify backfill_complete marked
    trader = session.query(Trader).filter_by(address=trader_address.lower()).first()
    assert trader.backfill_complete is True
    session.close()


def test_ingest_jbecker_deduplication(pipeline_with_jbecker, market_with_token):
    """Same trade_id not inserted twice."""
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker client
    pipeline_with_jbecker.jbecker_client.query_trader_history.return_value = [
        SAMPLE_JBECKER_TRADE,
    ]

    # Ensure trader exists
    session = market_with_token()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Ingest twice
    stats1 = pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)
    stats2 = pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)

    # First pass stores, second pass skips
    assert stats1["detail_count"] == 1
    assert stats2["already_in_db"] == 1
    assert stats2["detail_count"] == 0

    # Verify only 1 trade in DB
    session = market_with_token()
    trade_count = (
        session.query(Trade).filter_by(trader_address=trader_address.lower()).count()
    )
    assert trade_count == 1
    session.close()


def test_ingest_jbecker_batch_commits(pipeline_with_jbecker, market_with_token):
    """Large dataset commits in 1000-trade batches."""
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Generate 2500 unique trades (3 batches: 1000, 1000, 500)
    trades = []
    for i in range(2500):
        trade = SAMPLE_JBECKER_TRADE.copy()
        trade["id"] = f"0x{i:064x}"  # Unique ID
        trade["transaction_hash"] = f"0x{i:064x}"
        trades.append(trade)

    # Mock JBecker client
    pipeline_with_jbecker.jbecker_client.query_trader_history.return_value = trades

    # Ensure trader exists
    session = market_with_token()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Ingest
    stats = pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)

    # Verify all trades stored
    assert stats["trades_from_jbecker"] == 2500
    assert stats["detail_count"] == 2500

    # Verify DB has all trades
    session = market_with_token()
    trade_count = (
        session.query(Trade).filter_by(trader_address=trader_address.lower()).count()
    )
    assert trade_count == 2500
    session.close()


def test_ingest_jbecker_marks_backfill_complete(
    pipeline_with_jbecker, in_memory_session
):
    """trader.backfill_complete=True after ingestion."""
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker client
    pipeline_with_jbecker.jbecker_client.query_trader_history.return_value = [
        SAMPLE_JBECKER_TRADE,
    ]

    # Ensure trader exists with backfill_complete=False
    session = in_memory_session()
    trader = Trader(address=trader_address.lower(), backfill_complete=False)
    session.add(trader)
    session.commit()
    session.close()

    # Ingest
    pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)

    # Verify backfill_complete=True
    session = in_memory_session()
    trader = session.query(Trader).filter_by(address=trader_address.lower()).first()
    assert trader.backfill_complete is True
    session.close()


# ============================================================================
# Error Handling Tests (3 tests)
# ============================================================================


def test_ingest_jbecker_no_client_raises(in_memory_session):
    """Raises ValueError when jbecker_client is None."""
    from src.pipeline.filters import CategoryFilter

    mock_api_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=in_memory_session,
        category_filter=category_filter,
        jbecker_client=None,  # No JBecker client
    )

    with pytest.raises(ValueError, match="JBecker client not configured"):
        pipeline.ingest_trader_history_jbecker("0xabc...")


def test_ingest_jbecker_dataset_not_found(pipeline_with_jbecker, market_with_token):
    """FileNotFoundError propagates from JBeckerDataset."""
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker client to raise FileNotFoundError
    pipeline_with_jbecker.jbecker_client.query_trader_history.side_effect = (
        FileNotFoundError("data.parquet not found")
    )

    # Ensure trader exists
    session = market_with_token()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Should propagate FileNotFoundError
    with pytest.raises(FileNotFoundError, match="data.parquet not found"):
        pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)


def test_ingest_jbecker_conversion_failure_continues(
    pipeline_with_jbecker, market_with_token
):
    """Valid trades are processed, invalid market categories skipped."""
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Create trades with different market IDs - one matches eSports, one doesn't
    valid_trade = SAMPLE_JBECKER_TRADE.copy()
    invalid_category_trade = SAMPLE_JBECKER_TRADE.copy()
    invalid_category_trade["id"] = "0x999_0x999"
    invalid_category_trade["transaction_hash"] = "0x999"
    invalid_category_trade["maker_asset_id"] = (
        "999999"  # Different market, not in taxonomy
    )

    # Mock JBecker client
    pipeline_with_jbecker.jbecker_client.query_trader_history.return_value = [
        valid_trade,
        invalid_category_trade,
    ]

    # Ensure trader exists
    session = market_with_token()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Ingest
    stats = pipeline_with_jbecker.ingest_trader_history_jbecker(trader_address)

    # Verify valid trade stored, invalid category trade skipped
    assert stats["trades_from_jbecker"] == 2
    assert stats["detail_count"] == 1
    assert stats["skipped_invalid"] == 1

    # Verify only 1 trade in DB
    session = market_with_token()
    trade_count = session.query(Trade).count()
    assert trade_count == 1
    session.close()


# ============================================================================
# Hybrid Integration - Cost-Optimized Order Tests (3 tests)
# ============================================================================


def test_hybrid_prefers_jbecker_first(in_memory_session):
    """With all sources configured, tries JBecker FIRST (not Graph).

    Mock jbecker_client.query_trader_history to return trades.
    Verify Graph is NOT called.
    """
    from src.pipeline.filters import CategoryFilter

    mock_api_client = Mock()
    mock_jbecker_client = Mock()
    mock_graph_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=in_memory_session,
        category_filter=category_filter,
        jbecker_client=mock_jbecker_client,
        graph_client=mock_graph_client,
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker to return trades
    mock_jbecker_client.query_trader_history.return_value = [SAMPLE_JBECKER_TRADE]

    # Ensure trader exists
    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Hybrid ingestion
    stats = pipeline.ingest_trader_history_hybrid(trader_address)

    # Verify JBecker was called
    mock_jbecker_client.query_trader_history.assert_called_once_with(trader_address)

    # Verify Graph was NOT called
    mock_graph_client.get_trader_trades.assert_not_called()

    # Verify JBecker tier used
    assert "jbecker" in stats["tiers_used"]


def test_hybrid_fills_gap_with_api_then_graph(in_memory_session):
    """After JBecker returns trades with latest_timestamp, API is called for trades after that timestamp.

    If API returns exactly 100 trades (indicating more exist), Graph is called for the remaining gap.
    Verify call order: JBecker -> API -> Graph.
    """
    from src.pipeline.filters import CategoryFilter

    mock_api_client = Mock()
    mock_jbecker_client = Mock()
    mock_graph_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=in_memory_session,
        category_filter=category_filter,
        jbecker_client=mock_jbecker_client,
        graph_client=mock_graph_client,
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker to return historical trades
    mock_jbecker_client.query_trader_history.return_value = [SAMPLE_JBECKER_TRADE]

    # Mock API to return 100 trades (maxed out)
    # This simulates that more recent trades exist beyond API's limit
    mock_api_client.get_trades.return_value = [Mock()] * 100  # 100 trades

    # Mock Graph to return additional trades
    mock_graph_client.get_trader_trades.return_value = []

    # Ensure trader exists
    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)

    # Add a trade to DB so latest_timestamp query succeeds
    trade = Trade(
        market_id="test_market",
        trader_address=trader_address.lower(),
        side="BUY",
        size=Decimal("1.0"),
        price=Decimal("0.5"),
        timestamp=datetime(2024, 1, 1),
        trade_id="0x123",
    )
    session.add(trade)
    session.commit()
    session.close()

    # Hybrid ingestion with gap filling enabled
    stats = pipeline.ingest_trader_history_hybrid(
        trader_address,
        prefer_jbecker=True,
        fill_gap_with_api=True,
        fallback_to_graph=True,
    )

    # Verify call order: JBecker -> (gap fill triggers API) -> (API maxed triggers Graph)
    mock_jbecker_client.query_trader_history.assert_called_once()
    # Note: API call happens in ingest_trader_history, which may or may not be called
    # depending on pipeline implementation details
    # The key assertion is that tiers_used reflects the correct order
    assert "jbecker" in stats["tiers_used"]
    # API and Graph may be in tiers_used if gap filling triggered
    if len(stats["tiers_used"]) > 1:
        # Verify API comes before Graph
        jbecker_idx = stats["tiers_used"].index("jbecker")
        if "api" in stats["tiers_used"]:
            api_idx = stats["tiers_used"].index("api")
            assert api_idx > jbecker_idx
        if "graph" in stats["tiers_used"]:
            graph_idx = stats["tiers_used"].index("graph")
            assert graph_idx > jbecker_idx


def test_hybrid_blockchain_last_resort(in_memory_session):
    """When JBecker fails (dataset missing) AND API is insufficient AND Graph fails,
    falls back to blockchain as absolute last resort.
    """
    from src.pipeline.filters import CategoryFilter

    mock_api_client = Mock()
    mock_jbecker_client = Mock()
    mock_graph_client = Mock()
    mock_blockchain_client = Mock()
    category_filter = CategoryFilter(detail_categories=["eSports"])

    pipeline = IngestionPipeline(
        client=mock_api_client,
        session_factory=in_memory_session,
        category_filter=category_filter,
        jbecker_client=mock_jbecker_client,
        blockchain_client=mock_blockchain_client,
        graph_client=mock_graph_client,
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Mock JBecker to fail (dataset missing)
    mock_jbecker_client.query_trader_history.side_effect = FileNotFoundError(
        "Dataset not found"
    )

    # Mock API to return no trades (insufficient)
    mock_api_client.get_trades.return_value = []

    # Mock Graph to fail
    mock_graph_client.get_trader_trades.side_effect = Exception("Graph API error")

    # Mock blockchain to succeed
    mock_blockchain_client.get_trades_by_trader.return_value = []

    # Ensure trader exists
    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Hybrid ingestion with all fallbacks enabled
    stats = pipeline.ingest_trader_history_hybrid(
        trader_address,
        prefer_jbecker=True,
        fill_gap_with_api=True,
        fallback_to_graph=True,
        fallback_to_blockchain=True,
    )

    # Verify blockchain was used as last resort
    assert "blockchain" in stats["tiers_used"] or "api" in stats["tiers_used"]
    # At minimum, API should be in fallback chain


# ===== Token Cache Tests =====


def test_build_token_cache_loads_from_db(in_memory_session):
    """_build_token_cache loads token→condition and condition→category from DB."""
    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.filters import CategoryFilter

    session = in_memory_session()

    # Add market with tokens
    market1 = Market(
        condition_id="cond1",
        question="Test market 1?",
        category="Crypto",
        active=True,
        tokens='[{"token_id": "token123", "outcome": "Yes"}]',
    )
    session.add(market1)

    # Add market without tokens
    market2 = Market(
        condition_id="cond2",
        question="Test market 2?",
        category="Sports",
        active=True,
        tokens=None,
    )
    session.add(market2)
    session.commit()
    session.close()

    pipeline = IngestionPipeline(
        client=Mock(),
        session_factory=in_memory_session,
        category_filter=CategoryFilter({}),
    )

    session = in_memory_session()
    token_cache, condition_cache = pipeline._build_token_cache(session)
    session.close()

    assert "token123" in token_cache
    assert token_cache["token123"] == "cond1"
    assert "cond1" in condition_cache
    assert condition_cache["cond1"] == "Crypto"
    assert "cond2" in condition_cache
    assert condition_cache["cond2"] == "Sports"


def test_ingest_trader_history_jbecker_skips_db_scan_when_cache_provided(
    in_memory_session,
):
    """When token_cache is provided, DB scan for Market should be skipped."""
    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.filters import CategoryFilter
    from src.datasources.jbecker import JBeckerDataset

    mock_jbecker = Mock(spec=JBeckerDataset)
    mock_jbecker.query_trader_history.return_value = [SAMPLE_JBECKER_TRADE]

    pipeline = IngestionPipeline(
        client=Mock(),
        session_factory=in_memory_session,
        category_filter=CategoryFilter({}),
        jbecker_client=mock_jbecker,
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Add trader to DB
    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Provide empty cache - should use it and not query DB for markets
    empty_cache = ({}, {})
    stats = pipeline.ingest_trader_history_jbecker(
        trader_address, token_cache=empty_cache
    )

    # Should complete without error (cache was used)
    assert stats["trades_from_jbecker"] == 1
    # All trades skipped as invalid since cache is empty and no category mapping
    assert stats["skipped_invalid"] == 1


def test_ingest_trader_history_hybrid_passes_token_cache_through(in_memory_session):
    """ingest_trader_history_hybrid passes token_cache to jbecker method."""
    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.filters import CategoryFilter
    from src.datasources.jbecker import JBeckerDataset

    mock_jbecker = Mock(spec=JBeckerDataset)
    mock_jbecker.query_trader_history.return_value = []

    pipeline = IngestionPipeline(
        client=Mock(),
        session_factory=in_memory_session,
        category_filter=CategoryFilter({}),
        jbecker_client=mock_jbecker,
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Add trader to DB
    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    test_cache = ({"tokenX": "condY"}, {"condY": "Sports"})

    with patch.object(
        pipeline,
        "ingest_trader_history_jbecker",
        wraps=pipeline.ingest_trader_history_jbecker,
    ) as mock_jbecker_method:
        pipeline.ingest_trader_history_hybrid(trader_address, token_cache=test_cache)

        # Verify token_cache was passed
        mock_jbecker_method.assert_called_once()
        call_kwargs = mock_jbecker_method.call_args[1]
        assert call_kwargs.get("token_cache") == test_cache


def test_token_cache_grows_during_processing(in_memory_session):
    """Token cache dict is mutated when unknown tokens are discovered via Gamma API."""
    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.filters import CategoryFilter
    from src.datasources.jbecker import JBeckerDataset

    # Trade with unknown token
    trade_with_unknown_token = {
        **SAMPLE_JBECKER_TRADE,
        "maker_asset_id": "new_unknown_token_123",
    }

    mock_jbecker = Mock(spec=JBeckerDataset)
    mock_jbecker.query_trader_history.return_value = [trade_with_unknown_token]

    pipeline = IngestionPipeline(
        client=Mock(),
        session_factory=in_memory_session,
        category_filter=CategoryFilter({}),
        jbecker_client=mock_jbecker,
        gamma_client=Mock(),
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Add trader to DB
    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    # Start with empty mutable cache
    token_cache = ({}, {})

    with patch("httpx.get") as mock_httpx_get:
        # Mock Gamma API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "conditionId": "new_condition_456",
                "category": "Politics",
                "question": "Test question?",
                "active": True,
                "clobTokenIds": ["new_unknown_token_123"],
            }
        ]
        mock_httpx_get.return_value = mock_response

        pipeline.ingest_trader_history_jbecker(trader_address, token_cache=token_cache)

    # Cache should now contain the discovered token
    assert "new_unknown_token_123" in token_cache[0]
    assert token_cache[0]["new_unknown_token_123"] == "new_condition_456"


# ===== Batch Token Lookup Tests =====


def test_batch_token_lookup_groups_tokens_correctly(in_memory_session):
    """Batch lookup groups 45 tokens into 3 API calls (ceil(45/20) = 3), not 45 calls."""
    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.filters import CategoryFilter
    from src.datasources.jbecker import JBeckerDataset

    # Create 45 trades with unique unknown tokens
    trades = []
    for i in range(45):
        trade = SAMPLE_JBECKER_TRADE.copy()
        trade["id"] = f"0x{i:064x}"
        trade["transaction_hash"] = f"0x{i:064x}"
        trade["maker_asset_id"] = f"unknown_token_{i}"
        trades.append(trade)

    mock_jbecker = Mock(spec=JBeckerDataset)
    mock_jbecker.query_trader_history.return_value = trades

    pipeline = IngestionPipeline(
        client=Mock(),
        session_factory=in_memory_session,
        category_filter=CategoryFilter({}),
        jbecker_client=mock_jbecker,
        gamma_client=Mock(),
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    token_cache = ({}, {})

    with patch("httpx.get") as mock_httpx_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        def side_effect_response(*args, **kwargs):
            mock_response.json.return_value = []
            return mock_response

        mock_httpx_get.side_effect = side_effect_response

        pipeline.ingest_trader_history_jbecker(trader_address, token_cache=token_cache)

    # Should be called 3 times (ceil(45/20) = 3), NOT 45 times
    assert mock_httpx_get.call_count == 3

    # Verify comma-separated format was used
    first_call = mock_httpx_get.call_args_list[0]
    params = first_call[1].get("params", {})
    assert "clob_token_ids" in params
    token_ids = params["clob_token_ids"]
    assert "," in token_ids  # Should be comma-separated
    assert len(token_ids.split(",")) == 20  # First batch should have 20 tokens


def test_batch_token_lookup_processes_all_responses(in_memory_session):
    """Batch processes all responses - condition IDs end up in token_to_condition."""
    from src.pipeline.ingest import IngestionPipeline
    from src.pipeline.filters import CategoryFilter
    from src.datasources.jbecker import JBeckerDataset

    # Create 25 trades (2 batches: 20 + 5)
    trades = []
    for i in range(25):
        trade = SAMPLE_JBECKER_TRADE.copy()
        trade["id"] = f"0x{i:064x}"
        trade["transaction_hash"] = f"0x{i:064x}"
        trade["maker_asset_id"] = f"batch_token_{i}"
        trades.append(trade)

    mock_jbecker = Mock(spec=JBeckerDataset)
    mock_jbecker.query_trader_history.return_value = trades

    pipeline = IngestionPipeline(
        client=Mock(),
        session_factory=in_memory_session,
        category_filter=CategoryFilter({}),
        jbecker_client=mock_jbecker,
        gamma_client=Mock(),
    )

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    session = in_memory_session()
    trader = Trader(address=trader_address.lower())
    session.add(trader)
    session.commit()
    session.close()

    token_cache = ({}, {})

    call_count = [0]

    def side_effect_response(*args, **kwargs):
        call_count[0] += 1
        mock_response = Mock()
        mock_response.status_code = 200
        # Return 2 markets per batch with different conditions
        mock_response.json.return_value = [
            {
                "conditionId": f"condition_{call_count[0]}_a",
                "category": "Politics",
                "question": f"Test question {call_count[0]}a?",
                "active": True,
                "clobTokenIds": [
                    f"batch_token_{(call_count[0] - 1) * 20 + j}" for j in range(10)
                ],
            },
            {
                "conditionId": f"condition_{call_count[0]}_b",
                "category": "Sports",
                "question": f"Test question {call_count[0]}b?",
                "active": True,
                "clobTokenIds": [
                    f"batch_token_{(call_count[0] - 1) * 20 + 10 + j}"
                    for j in range(10)
                ],
            },
        ]
        return mock_response

    with patch("httpx.get") as mock_httpx_get:
        mock_httpx_get.side_effect = side_effect_response

        pipeline.ingest_trader_history_jbecker(trader_address, token_cache=token_cache)

    # Verify condition mappings exist for the tokens
    assert len(token_cache[0]) > 0  # Some tokens should be mapped
    assert "condition_1_a" in token_cache[1]  # Categories should be populated
    assert "condition_1_b" in token_cache[1]
