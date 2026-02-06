"""Tests for trade aggregation logic.

aggregate_trades produces category summaries from trade lists.
group_and_aggregate groups by category then aggregates each group.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest


# Mock TradeResponse until API models are implemented in Plan 02
@dataclass
class MockTradeResponse:
    """Minimal trade response for testing aggregators."""

    market_id: str
    trader_address: str
    side: str
    size: Decimal
    price: Decimal
    timestamp: datetime


@dataclass
class TradeWithCategory:
    """Associates a trade with its market's category."""

    trade: MockTradeResponse
    category: str


def test_aggregate_single_trade():
    """Aggregate single trade produces correct summary."""
    from src.pipeline.aggregators import aggregate_trades

    trades = [
        MockTradeResponse(
            market_id="politics_1",
            trader_address="0xabc",
            side="BUY",
            size=Decimal("100.5"),
            price=Decimal("0.6"),
            timestamp=datetime(2024, 1, 15, 10, 30),
        )
    ]

    result = aggregate_trades(trades, "0xabc", "Politics")

    assert result["trader_address"] == "0xabc"
    assert result["category"] == "Politics"
    assert result["total_volume"] == Decimal("100.5")
    assert result["trade_count"] == 1
    assert result["first_trade"] == datetime(2024, 1, 15, 10, 30)
    assert result["last_trade"] == datetime(2024, 1, 15, 10, 30)


def test_aggregate_multiple_trades():
    """Aggregate multiple trades sums volume and finds date range."""
    from src.pipeline.aggregators import aggregate_trades

    trades = [
        MockTradeResponse(
            market_id="politics_1",
            trader_address="0xabc",
            side="BUY",
            size=Decimal("100.0"),
            price=Decimal("0.6"),
            timestamp=datetime(2024, 1, 10, 8, 0),
        ),
        MockTradeResponse(
            market_id="politics_2",
            trader_address="0xabc",
            side="SELL",
            size=Decimal("50.5"),
            price=Decimal("0.4"),
            timestamp=datetime(2024, 1, 15, 14, 30),
        ),
        MockTradeResponse(
            market_id="politics_3",
            trader_address="0xabc",
            side="BUY",
            size=Decimal("75.25"),
            price=Decimal("0.55"),
            timestamp=datetime(2024, 1, 20, 16, 45),
        ),
    ]

    result = aggregate_trades(trades, "0xabc", "Politics")

    assert result["trader_address"] == "0xabc"
    assert result["category"] == "Politics"
    assert result["total_volume"] == Decimal("225.75")  # 100.0 + 50.5 + 75.25
    assert result["trade_count"] == 3
    assert result["first_trade"] == datetime(2024, 1, 10, 8, 0)
    assert result["last_trade"] == datetime(2024, 1, 20, 16, 45)


def test_aggregate_decimal_precision():
    """Aggregate uses Decimal arithmetic to preserve precision."""
    from src.pipeline.aggregators import aggregate_trades

    # These values demonstrate float precision issues
    # 0.1 + 0.2 != 0.3 in float, but should be exact in Decimal
    trades = [
        MockTradeResponse(
            market_id="crypto_1",
            trader_address="0xabc",
            side="BUY",
            size=Decimal("0.1"),
            price=Decimal("0.5"),
            timestamp=datetime(2024, 1, 1),
        ),
        MockTradeResponse(
            market_id="crypto_2",
            trader_address="0xabc",
            side="SELL",
            size=Decimal("0.2"),
            price=Decimal("0.5"),
            timestamp=datetime(2024, 1, 2),
        ),
    ]

    result = aggregate_trades(trades, "0xabc", "Crypto")

    # Should be exact, not 0.30000000000000004
    assert result["total_volume"] == Decimal("0.3")
    assert isinstance(result["total_volume"], Decimal)


def test_aggregate_preserves_trader_address():
    """Aggregate output contains correct trader_address."""
    from src.pipeline.aggregators import aggregate_trades

    trades = [
        MockTradeResponse(
            market_id="sports_1",
            trader_address="0xdef",
            side="BUY",
            size=Decimal("200.0"),
            price=Decimal("0.7"),
            timestamp=datetime(2024, 1, 1),
        )
    ]

    result = aggregate_trades(trades, "0xdef", "Sports")

    assert result["trader_address"] == "0xdef"


def test_aggregate_empty_trade_list():
    """Aggregate handles empty trade list gracefully."""
    from src.pipeline.aggregators import aggregate_trades

    with pytest.raises(ValueError, match="Cannot aggregate empty trade list"):
        aggregate_trades([], "0xabc", "Politics")


def test_group_and_aggregate_single_category():
    """group_and_aggregate with trades in one category."""
    from src.pipeline.aggregators import group_and_aggregate

    trades = [
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("100.0"),
                price=Decimal("0.6"),
                timestamp=datetime(2024, 1, 1),
            ),
            category="Politics",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("50.0"),
                price=Decimal("0.4"),
                timestamp=datetime(2024, 1, 2),
            ),
            category="Politics",
        ),
    ]

    results = group_and_aggregate(trades, "0xabc")

    assert len(results) == 1
    assert results[0]["category"] == "Politics"
    assert results[0]["total_volume"] == Decimal("150.0")
    assert results[0]["trade_count"] == 2


def test_group_and_aggregate_multiple_categories():
    """group_and_aggregate with trades across multiple categories."""
    from src.pipeline.aggregators import group_and_aggregate

    trades = [
        # Politics trades
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("100.0"),
                price=Decimal("0.6"),
                timestamp=datetime(2024, 1, 1),
            ),
            category="Politics",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("50.0"),
                price=Decimal("0.4"),
                timestamp=datetime(2024, 1, 2),
            ),
            category="Politics",
        ),
        # Crypto trades
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="crypto_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("200.0"),
                price=Decimal("0.55"),
                timestamp=datetime(2024, 1, 3),
            ),
            category="Crypto",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="crypto_2",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("75.0"),
                price=Decimal("0.65"),
                timestamp=datetime(2024, 1, 4),
            ),
            category="Crypto",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="crypto_3",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("125.0"),
                price=Decimal("0.5"),
                timestamp=datetime(2024, 1, 5),
            ),
            category="Crypto",
        ),
    ]

    results = group_and_aggregate(trades, "0xabc")

    assert len(results) == 2

    # Find each category in results
    politics_summary = next(r for r in results if r["category"] == "Politics")
    crypto_summary = next(r for r in results if r["category"] == "Crypto")

    # Verify Politics summary
    assert politics_summary["total_volume"] == Decimal("150.0")
    assert politics_summary["trade_count"] == 2
    assert politics_summary["trader_address"] == "0xabc"

    # Verify Crypto summary
    assert crypto_summary["total_volume"] == Decimal("400.0")  # 200 + 75 + 125
    assert crypto_summary["trade_count"] == 3
    assert crypto_summary["trader_address"] == "0xabc"


def test_group_and_aggregate_empty_list():
    """group_and_aggregate handles empty trade list."""
    from src.pipeline.aggregators import group_and_aggregate

    results = group_and_aggregate([], "0xabc")

    assert results == []


def test_group_and_aggregate_preserves_date_ranges():
    """group_and_aggregate preserves first/last trade dates per category."""
    from src.pipeline.aggregators import group_and_aggregate

    trades = [
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("100.0"),
                price=Decimal("0.6"),
                timestamp=datetime(2024, 1, 5),
            ),
            category="Politics",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="crypto_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("200.0"),
                price=Decimal("0.55"),
                timestamp=datetime(2024, 1, 10),
            ),
            category="Crypto",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("50.0"),
                price=Decimal("0.4"),
                timestamp=datetime(2024, 1, 20),
            ),
            category="Politics",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="crypto_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("75.0"),
                price=Decimal("0.5"),
                timestamp=datetime(2024, 1, 25),
            ),
            category="Crypto",
        ),
    ]

    results = group_and_aggregate(trades, "0xabc")

    politics_summary = next(r for r in results if r["category"] == "Politics")
    crypto_summary = next(r for r in results if r["category"] == "Crypto")

    # Politics: first=Jan 5, last=Jan 20
    assert politics_summary["first_trade"] == datetime(2024, 1, 5)
    assert politics_summary["last_trade"] == datetime(2024, 1, 20)

    # Crypto: first=Jan 10, last=Jan 25
    assert crypto_summary["first_trade"] == datetime(2024, 1, 10)
    assert crypto_summary["last_trade"] == datetime(2024, 1, 25)
