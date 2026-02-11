"""Tests for Polygon blockchain client."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from src.blockchain.client import PolygonBlockchainClient
from src.blockchain.decoder import CTF_EXCHANGE, NEGRISK_CTF_EXCHANGE, POLYMARKET_START_BLOCK
from src.blockchain.models import BlockchainTrade


@pytest.fixture
def mock_web3():
    """Fixture for mocked Web3 instance."""
    with patch("src.blockchain.client.Web3") as mock_w3_class:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.block_number = 50000000
        mock_w3_class.return_value = mock_w3
        mock_w3_class.HTTPProvider = Mock()
        mock_w3_class.to_checksum_address = lambda addr: addr
        yield mock_w3


@pytest.fixture
def mock_settings():
    """Fixture for mocked settings."""
    settings = Mock()
    settings.polygon_rpc_url = "https://polygon-rpc.com"
    settings.blockchain_batch_size = 1000
    return settings


def test_client_initialization(mock_web3, mock_settings):
    """Test client initializes with default RPC."""
    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        client = PolygonBlockchainClient()

        assert client.w3 is not None
        assert client.rpc_url == "https://polygon-rpc.com"
        assert client._rate_limit_delay == 0.1


def test_client_initialization_fails_on_connection_error(mock_settings):
    """Test client raises ConnectionError if RPC connection fails."""
    with patch("src.blockchain.client.Web3") as mock_w3_class:
        mock_w3 = Mock()
        mock_w3.is_connected.return_value = False
        mock_w3_class.return_value = mock_w3
        mock_w3_class.HTTPProvider = Mock()

        with patch("src.blockchain.client.get_settings", return_value=mock_settings):
            with pytest.raises(ConnectionError, match="Failed to connect"):
                PolygonBlockchainClient()


def test_get_block_number(mock_web3, mock_settings):
    """Test get_block_number returns correct block number."""
    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        client = PolygonBlockchainClient()
        block_number = client.get_block_number()

        assert block_number == 50000000


def test_get_block_timestamp(mock_web3, mock_settings):
    """Test get_block_timestamp returns block timestamp."""
    mock_web3.eth.get_block.return_value = {"timestamp": 1705314600}

    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        client = PolygonBlockchainClient()
        timestamp = client.get_block_timestamp(40000000)

        assert timestamp == 1705314600
        mock_web3.eth.get_block.assert_called_once_with(40000000)


def test_get_order_filled_events(mock_web3, mock_settings):
    """Test get_order_filled_events returns decoded trades."""
    # Mock log response
    mock_log = {
        "address": CTF_EXCHANGE,
        "blockNumber": 40000000,
        "transactionHash": b"\xab" * 32,
        "logIndex": 5,
        "topics": ["0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"],
    }
    mock_web3.eth.get_logs.return_value = [mock_log]
    mock_web3.eth.get_block.return_value = {"timestamp": 1705314600}

    # Mock contract decoding
    mock_contract = Mock()
    mock_event = Mock()
    mock_decoded = {
        "args": {
            "orderHash": b"\x12" * 32,
            "maker": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "taker": "0x28C6c06298d514Db089934071355E5743bf21d60",
            "makerAssetId": 0,
            "takerAssetId": 12345,
            "makerAmountFilled": 1000000,
            "takerAmountFilled": 2000000,
            "fee": 10000,
        }
    }
    mock_event.process_log.return_value = mock_decoded
    mock_contract.events.OrderFilled.return_value = mock_event
    mock_web3.eth.contract.return_value = mock_contract

    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        with patch("src.blockchain.client.decode_order_filled") as mock_decode:
            # Create a BlockchainTrade to return
            mock_trade = BlockchainTrade(
                block_number=40000000,
                transaction_hash="ab" * 32,
                log_index=5,
                order_hash="12" * 32,
                maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                taker="0x28C6c06298d514Db089934071355E5743bf21d60",
                maker_asset_id=0,
                taker_asset_id=12345,
                maker_amount=1000000,
                taker_amount=2000000,
                fee=10000,
            )
            mock_decode.return_value = mock_trade

            client = PolygonBlockchainClient()
            trades = client.get_order_filled_events(40000000, 40001000)

            assert len(trades) == 1
            assert isinstance(trades[0], BlockchainTrade)
            assert trades[0].block_number == 40000000


def test_get_order_filled_events_empty_range(mock_web3, mock_settings):
    """Test get_order_filled_events with empty logs returns empty list."""
    mock_web3.eth.get_logs.return_value = []

    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        client = PolygonBlockchainClient()
        trades = client.get_order_filled_events(40000000, 40001000)

        assert trades == []


def test_get_order_filled_events_invalid_block_range(mock_web3, mock_settings):
    """Test get_order_filled_events raises ValueError for invalid range."""
    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        client = PolygonBlockchainClient()

        with pytest.raises(ValueError, match="from_block.*must be.*to_block"):
            client.get_order_filled_events(40001000, 40000000)


def test_get_order_filled_events_retry_on_failure(mock_web3, mock_settings):
    """Test get_order_filled_events retries on ConnectionError."""
    # First call fails, second succeeds
    mock_web3.eth.get_logs.side_effect = [ConnectionError("RPC error"), []]

    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        client = PolygonBlockchainClient()
        trades = client.get_order_filled_events(40000000, 40001000)

        # Should retry and eventually succeed
        assert trades == []
        assert mock_web3.eth.get_logs.call_count == 2


def test_get_trades_by_trader(mock_web3, mock_settings):
    """Test get_trades_by_trader returns only trader's trades."""
    trader_address = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"

    # Mock logs for different traders
    mock_web3.eth.get_logs.return_value = []
    mock_web3.eth.get_block.return_value = {"timestamp": 1705314600}

    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        with patch.object(PolygonBlockchainClient, "get_order_filled_events") as mock_get_events:
            # Return trades from multiple makers/takers
            mock_get_events.return_value = [
                BlockchainTrade(
                    block_number=40000000,
                    transaction_hash="abc1",
                    log_index=1,
                    order_hash="order1",
                    maker=trader_address,  # Match
                    taker="0xOTHER",
                    maker_asset_id=0,
                    taker_asset_id=12345,
                    maker_amount=1000000,
                    taker_amount=2000000,
                    fee=10000,
                ),
                BlockchainTrade(
                    block_number=40000001,
                    transaction_hash="abc2",
                    log_index=2,
                    order_hash="order2",
                    maker="0xOTHER",
                    taker=trader_address,  # Match
                    maker_asset_id=12345,
                    taker_asset_id=0,
                    maker_amount=2000000,
                    taker_amount=1000000,
                    fee=10000,
                ),
                BlockchainTrade(
                    block_number=40000002,
                    transaction_hash="abc3",
                    log_index=3,
                    order_hash="order3",
                    maker="0xOTHER1",
                    taker="0xOTHER2",  # No match
                    maker_asset_id=0,
                    taker_asset_id=12345,
                    maker_amount=1000000,
                    taker_amount=2000000,
                    fee=10000,
                ),
            ]

            client = PolygonBlockchainClient()
            trades = client.get_trades_by_trader(trader_address, from_block=40000000, to_block=40002000)

            # Should only return trades where trader is maker or taker
            assert len(trades) == 2
            assert all(
                t.maker.lower() == trader_address.lower() or t.taker.lower() == trader_address.lower()
                for t in trades
            )


def test_get_trades_by_trader_filters_correctly(mock_web3, mock_settings):
    """Test get_trades_by_trader filters by address correctly."""
    target_trader = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"

    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        with patch.object(PolygonBlockchainClient, "get_order_filled_events") as mock_get_events:
            # Mix of matching and non-matching trades
            mock_get_events.return_value = [
                BlockchainTrade(
                    block_number=40000000,
                    transaction_hash="abc1",
                    log_index=1,
                    order_hash="order1",
                    maker=target_trader,
                    taker="0xOTHER",
                    maker_asset_id=0,
                    taker_asset_id=12345,
                    maker_amount=1000000,
                    taker_amount=2000000,
                    fee=10000,
                ),
                BlockchainTrade(
                    block_number=40000001,
                    transaction_hash="abc2",
                    log_index=2,
                    order_hash="order2",
                    maker="0xOTHER1",
                    taker="0xOTHER2",
                    maker_asset_id=0,
                    taker_asset_id=12345,
                    maker_amount=1000000,
                    taker_amount=2000000,
                    fee=10000,
                ),
            ]

            client = PolygonBlockchainClient()
            trades = client.get_trades_by_trader(target_trader)

            assert len(trades) == 1
            assert trades[0].maker == target_trader


def test_get_trades_paginated_generator(mock_web3, mock_settings):
    """Test get_trades_paginated yields chunks correctly."""
    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        with patch.object(PolygonBlockchainClient, "get_order_filled_events") as mock_get_events:
            # Return different trades for each chunk
            mock_get_events.side_effect = [
                [
                    BlockchainTrade(
                        block_number=40000000,
                        transaction_hash="abc1",
                        log_index=1,
                        order_hash="order1",
                        maker="0xMAKER",
                        taker="0xTAKER",
                        maker_asset_id=0,
                        taker_asset_id=12345,
                        maker_amount=1000000,
                        taker_amount=2000000,
                        fee=10000,
                    )
                ],
                [
                    BlockchainTrade(
                        block_number=40001000,
                        transaction_hash="abc2",
                        log_index=2,
                        order_hash="order2",
                        maker="0xMAKER",
                        taker="0xTAKER",
                        maker_asset_id=0,
                        taker_asset_id=12345,
                        maker_amount=1000000,
                        taker_amount=2000000,
                        fee=10000,
                    )
                ],
                [],  # Last chunk empty
            ]

            client = PolygonBlockchainClient()
            chunks = list(client.get_trades_paginated(40000000, 40002000, chunk_size=1000))

            assert len(chunks) == 2  # Should only yield non-empty chunks
            assert len(chunks[0]) == 1
            assert len(chunks[1]) == 1


def test_rate_limiting_between_calls(mock_web3, mock_settings):
    """Test that rate limiting delay is applied between RPC calls."""
    with patch("src.blockchain.client.get_settings", return_value=mock_settings):
        with patch("src.blockchain.client.time.sleep") as mock_sleep:
            mock_web3.eth.get_logs.return_value = []

            client = PolygonBlockchainClient(rate_limit_delay=0.5)
            client.get_order_filled_events(40000000, 40001000)

            # Should have called sleep for rate limiting
            # Note: _rate_limited_call is used, which calls sleep
            assert mock_sleep.called
