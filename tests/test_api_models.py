"""Tests for Pydantic API response validation models."""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.api.models import EventResponse, MarketResponse, TradeResponse


class TestMarketResponse:
    """Test suite for MarketResponse validation."""

    def test_market_response_validates_complete_data(self):
        """Test that complete market data validates correctly."""
        data = {
            "condition_id": "0x123abc",
            "question": "Will Team Liquid win IEM Katowice 2026?",
            "end_date_iso": "2026-02-15T18:00:00Z",
            "category": "eSports",
            "outcome": None,
            "active": True,
            "tokens": [
                {"token_id": "123", "outcome": "Yes"},
                {"token_id": "456", "outcome": "No"}
            ]
        }

        market = MarketResponse(**data)

        assert market.condition_id == "0x123abc"
        assert market.question == "Will Team Liquid win IEM Katowice 2026?"
        assert market.category == "eSports"
        assert market.active is True
        assert market.outcome is None
        assert len(market.tokens) == 2

    def test_market_response_handles_missing_optional_fields(self):
        """Test that optional fields can be omitted."""
        data = {
            "condition_id": "0x123abc",
            "question": "Will Team Liquid win?",
            "category": "eSports",
            "active": True,
        }

        market = MarketResponse(**data)

        assert market.end_date_iso is None
        assert market.outcome is None
        assert market.tokens is None

    def test_market_response_requires_mandatory_fields(self):
        """Test that mandatory fields raise ValidationError when missing."""
        data = {
            "question": "Missing condition_id",
        }

        with pytest.raises(ValidationError) as exc_info:
            MarketResponse(**data)

        errors = exc_info.value.errors()
        missing_fields = {error["loc"][0] for error in errors}
        assert "condition_id" in missing_fields


class TestEventResponse:
    """Test suite for EventResponse validation."""

    def test_event_response_validates_complete_data(self):
        """Test that complete event data validates correctly."""
        data = {
            "id": "event-123",
            "title": "IEM Katowice 2026",
            "slug": "iem-katowice-2026",
            "category": "eSports",
            "end_date": "2026-02-20T23:59:59Z",
            "active": True,
            "markets": [
                {
                    "condition_id": "0x123",
                    "question": "Will Liquid win?",
                    "category": "eSports",
                    "active": True,
                }
            ]
        }

        event = EventResponse(**data)

        assert event.id == "event-123"
        assert event.title == "IEM Katowice 2026"
        assert event.category == "eSports"
        assert len(event.markets) == 1
        assert event.markets[0].question == "Will Liquid win?"

    def test_event_response_handles_unix_timestamp(self):
        """Test that end_date accepts Unix timestamp."""
        data = {
            "id": "event-123",
            "title": "IEM Katowice 2026",
            "slug": "iem-katowice-2026",
            "category": "eSports",
            "end_date": 1739404799,  # Unix timestamp
            "active": True,
            "markets": []
        }

        event = EventResponse(**data)

        assert isinstance(event.end_date, datetime)
        # Verify it's approximately the right date (Feb 2026)
        assert event.end_date.year == 2025

    def test_event_response_handles_null_end_date(self):
        """Test that end_date can be null."""
        data = {
            "id": "event-123",
            "title": "Open-ended event",
            "slug": "open-ended",
            "category": "Politics",
            "end_date": None,
            "active": True,
            "markets": []
        }

        event = EventResponse(**data)

        assert event.end_date is None


class TestTradeResponse:
    """Test suite for TradeResponse validation."""

    def test_trade_response_decimal_precision(self):
        """Test that Decimal values preserve precision (not float)."""
        data = {
            "id": "trade-123",
            "market": "0xabc",
            "trader": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "side": "BUY",
            "size": "125.500000",
            "price": "0.650000",
            "timestamp": "2026-02-06T12:00:00Z",
        }

        trade = TradeResponse(**data)

        # Verify Decimal type (not float)
        assert isinstance(trade.size, Decimal)
        assert isinstance(trade.price, Decimal)

        # Verify exact precision
        assert trade.size == Decimal("125.500000")
        assert trade.price == Decimal("0.650000")

        # Verify no float rounding errors
        total = trade.size * trade.price
        assert total == Decimal("81.575000")  # Exact, not 81.57499999...

    def test_timestamp_handles_iso_and_unix(self):
        """Test that timestamp accepts both ISO string and Unix timestamp."""
        # ISO string
        data_iso = {
            "id": "trade-1",
            "market": "0xabc",
            "trader": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "side": "BUY",
            "size": "100",
            "price": "0.5",
            "timestamp": "2026-02-06T12:00:00Z",
        }

        trade_iso = TradeResponse(**data_iso)
        assert isinstance(trade_iso.timestamp, datetime)

        # Unix timestamp
        data_unix = {
            "id": "trade-2",
            "market": "0xabc",
            "trader": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "side": "SELL",
            "size": "100",
            "price": "0.5",
            "timestamp": 1707220800,  # Feb 6, 2024 12:00:00 UTC
        }

        trade_unix = TradeResponse(**data_unix)
        assert isinstance(trade_unix.timestamp, datetime)
        assert trade_unix.timestamp.year == 2024

    def test_price_validation_range(self):
        """Test that price must be between 0 and 1."""
        # Valid price
        data_valid = {
            "id": "trade-1",
            "market": "0xabc",
            "trader": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "side": "BUY",
            "size": "100",
            "price": "0.75",
            "timestamp": "2026-02-06T12:00:00Z",
        }

        trade = TradeResponse(**data_valid)
        assert trade.price == Decimal("0.75")

        # Invalid: price > 1
        data_invalid_high = {
            **data_valid,
            "price": "1.5",
        }

        with pytest.raises(ValidationError) as exc_info:
            TradeResponse(**data_invalid_high)

        assert "price" in str(exc_info.value).lower()

        # Invalid: price <= 0
        data_invalid_zero = {
            **data_valid,
            "price": "0",
        }

        with pytest.raises(ValidationError) as exc_info:
            TradeResponse(**data_invalid_zero)

        assert "price" in str(exc_info.value).lower()

    def test_trade_response_handles_field_aliases(self):
        """Test that field aliases work for API response mapping."""
        # API might return 'maker' or 'taker' instead of 'trader'
        data_with_maker = {
            "id": "trade-123",
            "market": "0xabc",
            "maker": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",  # Alias for 'trader'
            "side": "BUY",
            "size": "100",
            "price": "0.5",
            "timestamp": "2026-02-06T12:00:00Z",
        }

        trade = TradeResponse(**data_with_maker)
        assert trade.trader == "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
