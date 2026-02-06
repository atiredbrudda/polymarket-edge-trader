"""Tests for category-based trade filtering.

CategoryFilter routes trades to full detail storage or summary storage
based on configured detail_categories list.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest


# Mock TradeResponse until API models are implemented in Plan 02
@dataclass
class MockTradeResponse:
    """Minimal trade response for testing filters."""

    market_id: str
    trader_address: str
    side: str
    size: Decimal
    price: Decimal
    timestamp: datetime


@dataclass
class TradeWithCategory:
    """Associates a trade with its market's category.

    This wrapper avoids adding category directly to TradeResponse
    (which mirrors API structure).
    """

    trade: MockTradeResponse
    category: str


def test_requires_detail_matching_category():
    """Filter identifies matching detail category."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])
    assert filter.requires_detail("eSports") is True


def test_requires_detail_case_insensitive():
    """Filter matches categories case-insensitively."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])
    assert filter.requires_detail("esports") is True
    assert filter.requires_detail("ESPORTS") is True
    assert filter.requires_detail("EsPoRtS") is True


def test_requires_detail_non_matching():
    """Filter rejects non-detail categories."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])
    assert filter.requires_detail("Politics") is False
    assert filter.requires_detail("Crypto") is False
    assert filter.requires_detail("Sports") is False


def test_multiple_detail_categories():
    """Filter supports multiple detail categories."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports", "Crypto"])
    assert filter.requires_detail("eSports") is True
    assert filter.requires_detail("Crypto") is True
    assert filter.requires_detail("crypto") is True  # case-insensitive
    assert filter.requires_detail("Politics") is False


def test_route_trades_splits_correctly():
    """route_trades splits trades into detail and summary lists."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])

    # Create test trades
    trades = [
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="esport_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("100.0"),
                price=Decimal("0.6"),
                timestamp=datetime(2024, 1, 1),
            ),
            category="eSports",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="esport_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("50.0"),
                price=Decimal("0.4"),
                timestamp=datetime(2024, 1, 2),
            ),
            category="eSports",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("200.0"),
                price=Decimal("0.55"),
                timestamp=datetime(2024, 1, 3),
            ),
            category="Politics",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="esport_3",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("75.0"),
                price=Decimal("0.7"),
                timestamp=datetime(2024, 1, 4),
            ),
            category="esports",  # lowercase - should still match
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="politics_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("150.0"),
                price=Decimal("0.45"),
                timestamp=datetime(2024, 1, 5),
            ),
            category="Politics",
        ),
    ]

    detail_trades, summary_trades = filter.route_trades(trades)

    # Should have 3 eSports (detail) and 2 Politics (summary)
    assert len(detail_trades) == 3
    assert len(summary_trades) == 2

    # Verify detail trades are all eSports
    assert all(t.category.lower() == "esports" for t in detail_trades)

    # Verify summary trades are all Politics
    assert all(t.category == "Politics" for t in summary_trades)


def test_route_trades_empty_list():
    """route_trades handles empty trade list."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])
    detail_trades, summary_trades = filter.route_trades([])

    assert detail_trades == []
    assert summary_trades == []


def test_route_trades_all_detail():
    """route_trades with all trades in detail category."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])

    trades = [
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="esport_1",
                trader_address="0xabc",
                side="BUY",
                size=Decimal("100.0"),
                price=Decimal("0.6"),
                timestamp=datetime(2024, 1, 1),
            ),
            category="eSports",
        ),
        TradeWithCategory(
            trade=MockTradeResponse(
                market_id="esport_2",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("50.0"),
                price=Decimal("0.4"),
                timestamp=datetime(2024, 1, 2),
            ),
            category="eSports",
        ),
    ]

    detail_trades, summary_trades = filter.route_trades(trades)

    assert len(detail_trades) == 2
    assert len(summary_trades) == 0


def test_route_trades_all_summary():
    """route_trades with all trades in non-detail categories."""
    from src.pipeline.filters import CategoryFilter

    filter = CategoryFilter(["eSports"])

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
                market_id="crypto_1",
                trader_address="0xabc",
                side="SELL",
                size=Decimal("50.0"),
                price=Decimal("0.4"),
                timestamp=datetime(2024, 1, 2),
            ),
            category="Crypto",
        ),
    ]

    detail_trades, summary_trades = filter.route_trades(trades)

    assert len(detail_trades) == 0
    assert len(summary_trades) == 2
