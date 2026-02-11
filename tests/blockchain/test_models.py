"""Tests for blockchain trade models."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.blockchain.models import BlockchainTrade


def test_blockchain_trade_is_buy():
    """Test is_buy property for buy and sell trades."""
    # Buy trade: maker provides USDC (asset_id = 0)
    buy_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,  # USDC
        taker_asset_id=12345,
        maker_amount=1000000,
        taker_amount=2000000,
        fee=10000,
    )
    assert buy_trade.is_buy is True

    # Sell trade: taker provides USDC
    sell_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=12345,
        taker_asset_id=0,  # USDC
        maker_amount=2000000,
        taker_amount=1000000,
        fee=10000,
    )
    assert sell_trade.is_buy is False


def test_blockchain_trade_price_calculation():
    """Test price calculation for buy and sell trades."""
    # Buy trade: price = maker_amount / taker_amount / 1e6
    # 1 USDC for 2 tokens = 0.5 USDC per token
    buy_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,  # 1 USDC
        taker_amount=2000000,  # 2 tokens
        fee=10000,
    )
    assert buy_trade.price == Decimal("0.5")

    # Sell trade: price = taker_amount / maker_amount / 1e6
    # Selling 2 tokens for 1.4 USDC = 0.7 USDC per token
    sell_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=12345,
        taker_asset_id=0,
        maker_amount=2000000,  # 2 tokens
        taker_amount=1400000,  # 1.4 USDC
        fee=10000,
    )
    assert sell_trade.price == Decimal("0.7")


def test_blockchain_trade_price_edge_case_zero_amount():
    """Test price calculation with zero amount returns zero."""
    trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,
        taker_amount=0,  # Zero amount
        fee=10000,
    )
    assert trade.price == Decimal("0")


def test_blockchain_trade_size_calculation():
    """Test size calculation in USDC units."""
    # Buy trade: size = taker_amount / 1e6
    buy_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,
        taker_amount=2500000,  # 2.5 tokens
        fee=10000,
    )
    assert buy_trade.size == Decimal("2.5")

    # Sell trade: size = maker_amount / 1e6
    sell_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=12345,
        taker_asset_id=0,
        maker_amount=3750000,  # 3.75 tokens
        taker_amount=1000000,
        fee=10000,
    )
    assert sell_trade.size == Decimal("3.75")


def test_blockchain_trade_side():
    """Test side property returns BUY or SELL."""
    buy_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,
        taker_amount=2000000,
        fee=10000,
    )
    assert buy_trade.side == "BUY"

    sell_trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="abc123",
        log_index=0,
        order_hash="def456",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=12345,
        taker_asset_id=0,
        maker_amount=2000000,
        taker_amount=1000000,
        fee=10000,
    )
    assert sell_trade.side == "SELL"


def test_blockchain_trade_to_trade_id():
    """Test unique trade ID generation."""
    trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="0xabc123def456",
        log_index=7,
        order_hash="0xorder123",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,
        taker_amount=2000000,
        fee=10000,
    )
    assert trade.to_trade_id() == "0xabc123def456_7"


def test_blockchain_trade_to_api_response():
    """Test conversion to TradeResponse-compatible dict."""
    trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="0xabc123",
        log_index=5,
        order_hash="0xorder123",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,  # 1 USDC
        taker_amount=2000000,  # 2 tokens = 0.5 price
        fee=10000,
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
    )

    response = trade.to_api_response()

    assert response["id"] == "0xabc123_5"
    assert response["maker"] == "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
    assert response["side"] == "BUY"
    assert response["size"] == "2"
    assert response["price"] == "0.5"
    assert response["timestamp"] == 1705314600.0  # Unix timestamp
    assert "market" in response
    assert "asset_ticker" in response


def test_extract_condition_id():
    """Test condition ID extraction from asset ID."""
    # With valid asset ID
    trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="0xabc123",
        log_index=5,
        order_hash="0xorder123",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef,
        maker_amount=1000000,
        taker_amount=2000000,
        fee=10000,
    )
    condition_id = trade.extract_condition_id()
    assert condition_id.startswith("0x")
    assert len(condition_id) == 66  # 0x + 64 hex chars

    # With asset_id = 0 (USDC)
    trade_usdc = BlockchainTrade(
        block_number=40000000,
        transaction_hash="0xabc123",
        log_index=5,
        order_hash="0xorder123",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=12345,
        taker_asset_id=0,  # USDC
        maker_amount=1000000,
        taker_amount=2000000,
        fee=10000,
    )
    assert trade_usdc.extract_condition_id() == ""


def test_extract_outcome_name():
    """Test outcome name extraction (placeholder)."""
    trade = BlockchainTrade(
        block_number=40000000,
        transaction_hash="0xabc123",
        log_index=5,
        order_hash="0xorder123",
        maker="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        taker="0x28C6c06298d514Db089934071355E5743bf21d60",
        maker_asset_id=0,
        taker_asset_id=12345,
        maker_amount=1000000,
        taker_amount=2000000,
        fee=10000,
    )
    # Placeholder returns empty string
    assert trade.extract_outcome_name() == ""
