"""Tests for API client behavior."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from tenacity import RetryError

from src.api.client import PolymarketClient
from src.api.models import MarketResponse, TradeResponse
from src.config.settings import Settings


class TestPolymarketClient:
    """Test suite for PolymarketClient."""

    @patch("src.api.client.ClobClient")
    def test_initialization_with_settings(self, mock_clob_client):
        """Test that client initializes with settings."""
        settings = Settings()
        client = PolymarketClient(settings=settings)

        # Verify ClobClient was initialized with correct host
        mock_clob_client.assert_called_once_with(
            settings.polymarket_api_host,
            key=settings.polymarket_api_key
        )

        # Verify rate limiter was created with correct rate
        assert client.rate_limiter is not None

    @patch("src.api.client.ClobClient")
    def test_initialization_without_settings_uses_defaults(self, mock_clob_client):
        """Test that client uses default settings when none provided."""
        client = PolymarketClient()

        # Should still initialize ClobClient
        assert mock_clob_client.called

    @patch("src.api.client.ClobClient")
    def test_get_markets_returns_validated_models(self, mock_clob_client):
        """Test that get_markets returns list of MarketResponse models."""
        # Mock API response (as list, not dict with pagination)
        mock_api_response = [
            {
                "condition_id": "0xabc",
                "question": "Will Liquid win IEM?",
                "category": "eSports",
                "active": True,
            },
            {
                "condition_id": "0xdef",
                "question": "Will FaZe qualify?",
                "category": "eSports",
                "active": True,
            }
        ]

        mock_instance = mock_clob_client.return_value
        mock_instance.get_simplified_markets.return_value = mock_api_response

        client = PolymarketClient()
        markets = client.get_markets(active=True)

        # Verify returns list of MarketResponse
        assert len(markets) == 2
        assert all(isinstance(m, MarketResponse) for m in markets)
        assert markets[0].question == "Will Liquid win IEM?"
        assert markets[1].condition_id == "0xdef"

    @patch("src.api.client.ClobClient")
    def test_get_markets_paginates(self, mock_clob_client):
        """Test that get_markets handles pagination correctly."""
        # Mock paginated responses
        page1 = {
            "data": [
                {
                    "condition_id": "0x1",
                    "question": "Market 1",
                    "category": "eSports",
                    "active": True,
                }
            ],
            "next_cursor": "cursor_page2"
        }
        page2 = {
            "data": [
                {
                    "condition_id": "0x2",
                    "question": "Market 2",
                    "category": "eSports",
                    "active": True,
                }
            ],
            "next_cursor": "LTE"  # End of pagination
        }

        mock_instance = mock_clob_client.return_value
        mock_instance.get_simplified_markets.side_effect = [page1, page2]

        client = PolymarketClient()
        markets = client.get_markets(active=True)

        # Verify both pages were fetched
        assert len(markets) == 2
        assert markets[0].condition_id == "0x1"
        assert markets[1].condition_id == "0x2"

        # Verify pagination calls
        assert mock_instance.get_simplified_markets.call_count == 2

    @patch("src.api.client.ClobClient")
    def test_get_market_trades_returns_trades(self, mock_clob_client):
        """Test that get_market_trades returns list of TradeResponse models."""
        # Mock API response
        mock_api_response = [
            {
                "id": "trade-1",
                "market": "0xabc",
                "maker": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
                "side": "BUY",
                "size": "100.5",
                "price": "0.65",
                "timestamp": 1707220800,
            },
            {
                "id": "trade-2",
                "market": "0xabc",
                "maker": "0x1234567890abcdef1234567890abcdef12345678",
                "side": "SELL",
                "size": "50.25",
                "price": "0.70",
                "timestamp": 1707221000,
            }
        ]

        mock_instance = mock_clob_client.return_value
        mock_instance.get_trades.return_value = mock_api_response

        client = PolymarketClient()
        trades = client.get_market_trades(condition_id="0xabc", limit=500)

        # Verify returns list of TradeResponse
        assert len(trades) == 2
        assert all(isinstance(t, TradeResponse) for t in trades)
        assert trades[0].trader == "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        assert trades[1].size == Decimal("50.25")

    @patch("src.api.client.ClobClient")
    def test_retry_on_connection_error(self, mock_clob_client):
        """Test that connection errors are retried with exponential backoff."""
        # Mock: fail twice, then succeed
        mock_instance = mock_clob_client.return_value
        mock_instance.get_simplified_markets.side_effect = [
            ConnectionError("Network error"),
            ConnectionError("Network error again"),
            [  # Success on third attempt
                {
                    "condition_id": "0x123",
                    "question": "Success after retry",
                    "category": "eSports",
                    "active": True,
                }
            ]
        ]

        client = PolymarketClient()
        markets = client.get_markets(active=True)

        # Verify it eventually succeeded
        assert len(markets) == 1
        assert markets[0].question == "Success after retry"

        # Verify it retried 3 times total
        assert mock_instance.get_simplified_markets.call_count == 3

    @patch("src.api.client.ClobClient")
    def test_retry_exhaustion_raises_error(self, mock_clob_client):
        """Test that retry exhaustion raises RetryError."""
        # Mock: always fail
        mock_instance = mock_clob_client.return_value
        mock_instance.get_simplified_markets.side_effect = ConnectionError("Persistent failure")

        # Override settings to limit retries for faster test
        settings = Settings(retry_max_attempts=3)
        client = PolymarketClient(settings=settings)

        # Should raise RetryError after exhausting attempts
        with pytest.raises(RetryError):
            client.get_markets(active=True)

    @patch("src.api.client.ClobClient")
    def test_rate_limiter_called_before_request(self, mock_clob_client):
        """Test that rate limiter acquire() is called before API requests."""
        mock_instance = mock_clob_client.return_value
        mock_instance.get_simplified_markets.return_value = []

        client = PolymarketClient()

        # Spy on rate limiter
        with patch.object(client.rate_limiter, "acquire", wraps=client.rate_limiter.acquire) as mock_acquire:
            client.get_markets(active=True)

            # Verify rate limiter was called
            mock_acquire.assert_called()

    @patch("src.api.client.ClobClient")
    def test_get_market_trades_pagination(self, mock_clob_client):
        """Test that get_market_trades handles pagination correctly."""
        # Mock paginated responses
        page1 = {
            "data": [
                {
                    "id": "trade-1",
                    "market": "0xabc",
                    "maker": "0x111",
                    "side": "BUY",
                    "size": "100",
                    "price": "0.5",
                    "timestamp": 1707220800,
                }
            ],
            "next_cursor": "cursor_page2"
        }
        page2 = {
            "data": [
                {
                    "id": "trade-2",
                    "market": "0xabc",
                    "maker": "0x222",
                    "side": "SELL",
                    "size": "50",
                    "price": "0.6",
                    "timestamp": 1707221000,
                }
            ],
            "next_cursor": "LTE"  # End marker
        }

        mock_instance = mock_clob_client.return_value
        mock_instance.get_trades.side_effect = [page1, page2]

        client = PolymarketClient()
        trades = client.get_market_trades(condition_id="0xabc", limit=500)

        # Verify both pages were fetched
        assert len(trades) == 2
        assert trades[0].id == "trade-1"
        assert trades[1].id == "trade-2"
