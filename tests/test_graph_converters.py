"""Tests for Graph converters."""

from decimal import Decimal

from src.graph.converters import graph_trade_to_api_response


def test_graph_trade_price_under_one():
    """Test that prices under 1 are kept as-is."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "123",
        "takerAssetId": "456",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc",
        "side": "BUY",
        "price": "0.5",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    assert result.price == Decimal("0.5")


def test_graph_trade_price_over_one():
    """Test that prices over 1 are converted to implied probability."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "123",
        "takerAssetId": "456",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc",
        "side": "BUY",
        "price": "2.0",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    assert result.price == Decimal("0.5")


def test_graph_trade_price_decimal_odds():
    """Test conversion of various decimal odds to probability."""
    test_cases = [
        ("1.6666666666666667", Decimal("0.6")),
        ("32.25806339035813249017596024317552", Decimal("0.031")),
        ("7.142857142857142857142857142857143", Decimal("0.14")),
        ("50", Decimal("0.02")),
        ("1.01010101010101010101010101010101", Decimal("0.99")),
    ]

    for decimal_odds, expected_probability in test_cases:
        graph_trade = {
            "id": f"0xabc_{decimal_odds}",
            "maker": "0xTrader123",
            "taker": "0xOther456",
            "makerAmountFilled": "500000",
            "takerAmountFilled": "1000000",
            "makerAssetId": "123",
            "takerAssetId": "456",
            "fee": "1000",
            "timestamp": "1234567890",
            "blockNumber": "82466624",
            "transactionHash": "0xabc",
            "side": "BUY",
            "price": decimal_odds,
        }

        result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
        # Check that price is converted to valid probability (0-1 range)
        assert result.price > 0
        assert result.price < 1
        # Allow some tolerance for decimal precision
        assert abs(result.price - expected_probability) < Decimal("0.01")


def test_market_id_resolves_from_catalog():
    """Test that asset_id is looked up in token_to_condition cache."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "123",
        "takerAssetId": "456",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.5",
    }

    cache = {"123": "0xabc123_condition"}
    result = graph_trade_to_api_response(graph_trade, "0xTrader123", cache)
    assert result.market == "0xabc123_condition"


def test_market_id_fallback_when_not_in_catalog():
    """Test fallback to synthetic ID when token not in cache."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "999",
        "takerAssetId": "456",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.5",
    }

    cache = {"123": "0xabc123_condition"}
    result = graph_trade_to_api_response(graph_trade, "0xTrader123", cache)
    assert result.market.startswith("graph_")
    assert "0xabc123" in result.market
    assert "999" in result.market


def test_market_id_no_cache_passed():
    """Test fallback when cache is None."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "123",
        "takerAssetId": "456",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.5",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    assert result.market.startswith("graph_")


def test_maker_on_usdc_side_picks_taker_asset():
    """When maker provides USDC (asset=0), use taker's conditional token."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",   # 0.5 USDC
        "takerAmountFilled": "1000000",  # 1.0 tokens
        "makerAssetId": "0",             # USDC side
        "takerAssetId": "99887766",      # Conditional token
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.5",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    # Should use taker's token (99887766), not maker's USDC (0)
    assert "99887766" in result.market
    assert result.market == "graph_0xabc123_99887766"


def test_taker_on_usdc_side_picks_maker_asset():
    """When taker provides USDC (asset=0), use maker's conditional token."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xOther456",
        "taker": "0xTrader123",
        "makerAmountFilled": "1000000",  # 1.0 tokens
        "takerAmountFilled": "500000",   # 0.5 USDC
        "makerAssetId": "99887766",      # Conditional token
        "takerAssetId": "0",             # USDC side
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "SELL",
        "price": "0.5",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    # Should use maker's token (99887766), not taker's USDC (0)
    assert "99887766" in result.market
    assert result.market == "graph_0xabc123_99887766"


def test_usdc_side_resolves_from_catalog():
    """Maker on USDC side should still resolve market_id via token catalog."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "0",
        "takerAssetId": "99887766",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.5",
    }

    cache = {"99887766": "real_condition_id_abc"}
    result = graph_trade_to_api_response(graph_trade, "0xTrader123", cache)
    assert result.market == "real_condition_id_abc"


def test_usdc_side_size_is_token_amount():
    """Size should be the token amount, not the USDC amount."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",   # 0.5 USDC
        "takerAmountFilled": "2000000",  # 2.0 tokens
        "makerAssetId": "0",
        "takerAssetId": "99887766",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.25",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    # Size should be 2.0 (token amount), not 0.5 (USDC amount)
    assert result.size == Decimal("2")


def test_both_assets_nonzero_uses_trader_role():
    """When both assets are non-zero, fall back to trader's role."""
    graph_trade = {
        "id": "0xabc_0xdef",
        "maker": "0xTrader123",
        "taker": "0xOther456",
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "111",
        "takerAssetId": "222",
        "fee": "1000",
        "timestamp": "1234567890",
        "blockNumber": "82466624",
        "transactionHash": "0xabc123",
        "side": "BUY",
        "price": "0.5",
    }

    result = graph_trade_to_api_response(graph_trade, "0xTrader123", None)
    assert "111" in result.market  # maker's asset
