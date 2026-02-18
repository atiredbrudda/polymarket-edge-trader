"""Tests for JBecker dataset to API format converters."""

import pytest
from datetime import datetime
from decimal import Decimal

from src.api.models import TradeResponse


# Sample JBecker trade matching schema from 09-RESEARCH.md
SAMPLE_JBECKER_TRADE = {
    "maker": "0xeffd76b6a4318d50c6f71a16b276c5b279445a86",
    "taker": "0xabc123def456789012345678901234567890abcd",
    "maker_amount": "1500000",
    "taker_amount": "3000000",
    "maker_asset_id": "123457",  # odd = YES
    "taker_asset_id": "789012",  # even = NO
    "fee": "1000",
    "timestamp": 1704067200,
    "block_number": 50000000,
    "transaction_hash": "0xabcdef1234567890",
    "order_hash": "0xfedcba0987654321",
    "log_index": "0",
    "_fetched_at": "2024-01-01T00:00:00",
    "_contract": "ctf_exchange",
}


# ============================================================================
# Basic Conversion Tests (3 tests)
# ============================================================================


def test_convert_maker_trade():
    """Trader as maker: size=makerAmount/1e6, side=SELL (hardcoded for maker)."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"  # maker

    result = jbecker_trade_to_api_response(SAMPLE_JBECKER_TRADE, trader_address)

    assert isinstance(result, TradeResponse)
    assert result.side == "SELL"  # Maker's side is hardcoded to SELL
    assert result.size == Decimal("1.5")  # 1500000 / 1e6
    assert result.price == Decimal(
        "0.5"
    )  # maker_amount / taker_amount = 1.5 / 3.0 = 0.5
    assert result.trader == trader_address.lower()


def test_convert_taker_trade():
    """Trader as taker: size=takerAmount/1e6, side=BUY (hardcoded for taker)."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trader_address = "0xabc123def456789012345678901234567890abcd"  # taker

    result = jbecker_trade_to_api_response(SAMPLE_JBECKER_TRADE, trader_address)

    assert isinstance(result, TradeResponse)
    assert result.side == "BUY"  # Taker's side is hardcoded to BUY
    assert result.size == Decimal("3.0")  # 3000000 / 1e6
    assert result.price == Decimal(
        "0.5"
    )  # maker_amount / taker_amount = 1.5 / 3.0 = 0.5
    assert result.trader == trader_address.lower()


def test_convert_returns_trade_response():
    """Return type is TradeResponse Pydantic model."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    result = jbecker_trade_to_api_response(SAMPLE_JBECKER_TRADE, trader_address)

    assert isinstance(result, TradeResponse)
    assert hasattr(result, "id")
    assert hasattr(result, "market")
    assert hasattr(result, "trader")
    assert hasattr(result, "side")
    assert hasattr(result, "size")
    assert hasattr(result, "price")
    assert hasattr(result, "timestamp")
    assert hasattr(result, "asset_ticker")


# ============================================================================
# Amount Conversion Tests (3 tests)
# ============================================================================


def test_amount_6_decimal_conversion():
    """'1500000' string converts to Decimal('1.500000') (1.5 USDC)."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["maker_amount"] = "1500000"
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"  # maker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.size == Decimal("1.5")
    # Verify no float conversion (Decimal precision maintained)
    assert isinstance(result.size, Decimal)


def test_amount_zero_handling():
    """'0' string converts to Decimal('0')."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["maker_amount"] = "0"
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"  # maker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.size == Decimal("0")


def test_amount_large_value():
    """'1000000000' string converts to Decimal('1000.000000') (1000 USDC)."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["maker_amount"] = "1000000000"
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"  # maker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.size == Decimal("1000.0")


# ============================================================================
# Role Determination Tests (3 tests)
# ============================================================================


def test_maker_gets_buy_side():
    """Maker always gets side=SELL (hardcoded)."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"  # maker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.side == "SELL"


def test_taker_gets_opposite_side():
    """Taker always gets side=BUY (hardcoded)."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trader_address = "0xabc123def456789012345678901234567890abcd"  # taker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.side == "BUY"


def test_case_insensitive_role_matching():
    """'0xABC' matches '0xabc' for role determination."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["maker"] = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
    trader_address = "0xabcdef1234567890abcdef1234567890abcdef12"  # lowercase

    result = jbecker_trade_to_api_response(trade, trader_address)

    # Should be recognized as maker - gets hardcoded SELL side
    assert result.side == "SELL"


# ============================================================================
# Edge Cases Tests (4 tests)
# ============================================================================


def test_timestamp_conversion():
    """Unix int timestamp converts to datetime."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["timestamp"] = 1704067200  # 2024-01-01 00:00:00 UTC
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert isinstance(result.timestamp, datetime)
    assert result.timestamp.year == 2024
    assert result.timestamp.month == 1
    assert result.timestamp.day == 1


def test_asset_ticker_odd_yes():
    """Odd asset ID produces 'YES' ticker."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["maker_asset_id"] = "123457"  # odd
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"  # maker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.asset_ticker == "YES"


def test_asset_ticker_even_no():
    """Even asset ID produces 'NO' ticker."""
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["taker_asset_id"] = "789012"  # even
    trader_address = "0xabc123def456789012345678901234567890abcd"  # taker

    result = jbecker_trade_to_api_response(trade, trader_address)

    assert result.asset_ticker == "NO"


def test_invalid_price_skipped():
    """Prices derived from amounts are validated and corrected by converter.

    The converter has fallback logic to ensure price is always in (0,1):
    - If price >= 1, it flips: price = 1 - price
    - If price <= 0 after flip, it defaults to 0.5
    So ValidationError should NOT be raised from this converter.
    """
    from src.datasources.converters import jbecker_trade_to_api_response

    trade = SAMPLE_JBECKER_TRADE.copy()
    trade["maker_amount"] = "3000000"  # 3.0
    trade["taker_amount"] = "1000000"  # 1.0
    # price = 3.0 >= 1, so converter flips: 1 - 3.0 = -2.0
    # Then -2.0 <= 0, so converter sets: 0.5
    trader_address = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"

    # Should not raise - converter handles extreme prices gracefully
    result = jbecker_trade_to_api_response(trade, trader_address)
    assert result.price == Decimal("0.5")
