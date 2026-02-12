"""Tests for blockchain event decoder."""

from unittest.mock import Mock

import pytest
from web3 import Web3

from src.blockchain.decoder import (
    CTF_EXCHANGE,
    NEGRISK_CTF_EXCHANGE,
    ORDER_FILLED_ABI,
    ORDER_FILLED_TOPIC,
    POLYMARKET_START_BLOCK,
    decode_order_filled,
)
from src.blockchain.models import BlockchainTrade


def test_constants_defined():
    """Test that all required constants are defined."""
    assert CTF_EXCHANGE == "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    assert NEGRISK_CTF_EXCHANGE == "0xC5d563A36AE78145C45a50134d48A1215220f80a"
    assert ORDER_FILLED_TOPIC == "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
    assert POLYMARKET_START_BLOCK == 33605403
    assert ORDER_FILLED_ABI["name"] == "OrderFilled"
    assert ORDER_FILLED_ABI["type"] == "event"


def test_decode_order_filled_valid_log():
    """Test decoding a valid OrderFilled event log."""
    # Mock Web3 instance
    w3 = Mock()

    # Mock contract and event processing
    mock_contract = Mock()
    mock_event = Mock()
    mock_decoded = {
        "args": {
            "orderHash": b"\x12" * 32,
            "maker": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "taker": "0x28C6c06298d514Db089934071355E5743bf21d60",
            "makerAssetId": 0,  # USDC = buy
            "takerAssetId": 12345678901234567890,
            "makerAmountFilled": 1000000,  # 1 USDC in wei
            "takerAmountFilled": 2000000,  # 2 tokens
            "fee": 10000,
        }
    }

    mock_event.process_log = Mock(return_value=mock_decoded)
    mock_contract.events.OrderFilled = Mock(return_value=mock_event)
    w3.eth = Mock()
    w3.eth.contract = Mock(return_value=mock_contract)

    # Create test log
    log = {
        "address": CTF_EXCHANGE,
        "blockNumber": 40000000,
        "transactionHash": b"\xab" * 32,
        "logIndex": 5,
        "topics": [ORDER_FILLED_TOPIC],
    }

    # Decode the log
    trade = decode_order_filled(log, w3)

    # Verify BlockchainTrade fields
    assert isinstance(trade, BlockchainTrade)
    assert trade.block_number == 40000000
    assert trade.transaction_hash == ("ab" * 32)
    assert trade.log_index == 5
    assert trade.order_hash == ("12" * 32)
    assert trade.maker == "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
    assert trade.taker == "0x28C6c06298d514Db089934071355E5743bf21d60"
    assert trade.maker_asset_id == 0
    assert trade.taker_asset_id == 12345678901234567890
    assert trade.maker_amount == 1000000
    assert trade.taker_amount == 2000000
    assert trade.fee == 10000


def test_decode_order_filled_invalid_log():
    """Test that decoding an invalid log raises ValueError."""
    w3 = Mock()

    # Mock contract that raises exception during processing
    mock_contract = Mock()
    mock_event = Mock()
    mock_event.process_log = Mock(side_effect=ValueError("Invalid log"))
    mock_contract.events.OrderFilled = Mock(return_value=mock_event)
    w3.eth = Mock()
    w3.eth.contract = Mock(return_value=mock_contract)

    log = {
        "address": CTF_EXCHANGE,
        "blockNumber": 40000000,
        "transactionHash": b"\xab" * 32,
        "logIndex": 5,
        "topics": [ORDER_FILLED_TOPIC],
    }

    # Should raise ValueError
    with pytest.raises(ValueError, match="Invalid log"):
        decode_order_filled(log, w3)


def test_decode_preserves_hex_format():
    """Test that transaction and order hashes are converted to hex strings."""
    w3 = Mock()

    mock_contract = Mock()
    mock_event = Mock()
    mock_decoded = {
        "args": {
            "orderHash": b"\x01\x02\x03\x04" + b"\x00" * 28,
            "maker": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "taker": "0x28C6c06298d514Db089934071355E5743bf21d60",
            "makerAssetId": 0,
            "takerAssetId": 12345,
            "makerAmountFilled": 1000000,
            "takerAmountFilled": 2000000,
            "fee": 10000,
        }
    }

    mock_event.process_log = Mock(return_value=mock_decoded)
    mock_contract.events.OrderFilled = Mock(return_value=mock_event)
    w3.eth = Mock()
    w3.eth.contract = Mock(return_value=mock_contract)

    log = {
        "address": CTF_EXCHANGE,
        "blockNumber": 40000000,
        "transactionHash": b"\xaa\xbb\xcc\xdd" + b"\x00" * 28,
        "logIndex": 5,
        "topics": [ORDER_FILLED_TOPIC],
    }

    trade = decode_order_filled(log, w3)

    # Verify hex format (no 0x prefix in our implementation)
    assert isinstance(trade.transaction_hash, str)
    assert isinstance(trade.order_hash, str)
    # Should be hex strings
    assert trade.transaction_hash.startswith("aabbccdd")
    assert trade.order_hash.startswith("01020304")
