"""Tests for Gamma API client."""

import unittest
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock

import httpx


class TestGammaMarketClient(unittest.TestCase):
    """Test cases for GammaMarketClient."""

    def test_get_markets_basic(self):
        """Test basic market fetching with closed=false param."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "1", "question": "Will it rain?"},
            {"id": "2", "question": "Will it snow?"},
        ]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            result = client.get_markets(closed=False)

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            self.assertEqual(
                call_args[0][0], "https://gamma-api.polymarket.com/markets"
            )
            params = call_args[1].get("params", {})
            self.assertEqual(params.get("closed"), "false")
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["question"], "Will it rain?")

    def test_get_markets_with_end_date_max(self):
        """Test filtering by end_date_max param."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "1", "question": "Test market"}]

        test_date = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            result = client.get_markets(end_date_max=test_date)

            call_args = mock_get.call_args
            params = call_args[1].get("params", {})
            self.assertIn("end_date_max", params)

    def test_get_markets_with_tag(self):
        """Test filtering by tag param."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "1", "question": "Esports market"}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            result = client.get_markets(tag="esports")

            call_args = mock_get.call_args
            params = call_args[1].get("params", {})
            self.assertEqual(params.get("tag"), "esports")
            self.assertEqual(len(result), 1)

    def test_get_markets_pagination(self):
        """Test pagination through multiple pages of results."""
        from src.api.gamma_client import GammaMarketClient

        page1 = [{"id": str(i)} for i in range(100)]
        page2 = [{"id": str(i)} for i in range(100, 150)]

        mock_response1 = MagicMock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = page1

        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = page2

        with patch(
            "httpx.get", side_effect=[mock_response1, mock_response2]
        ) as mock_get:
            client = GammaMarketClient()
            result = client.get_markets(limit=100)

            self.assertEqual(mock_get.call_count, 2)
            self.assertEqual(len(result), 150)

    def test_get_markets_empty_response(self):
        """Test returns empty list when API returns empty array."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("httpx.get", return_value=mock_response):
            client = GammaMarketClient()
            result = client.get_markets()

            self.assertEqual(result, [])

    def test_get_markets_http_error(self):
        """Test raises HTTPStatusError on 4xx/5xx response."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        with patch("httpx.get", return_value=mock_response):
            client = GammaMarketClient()
            with self.assertRaises(httpx.HTTPStatusError):
                client.get_markets()

    def test_get_markets_with_multiple_filters(self):
        """Test combining end_date_max + tag + closed filters."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "1"}]

        test_date = datetime(2025, 12, 31, tzinfo=UTC)

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            client.get_markets(end_date_max=test_date, tag="crypto", closed=True)

            call_args = mock_get.call_args
            params = call_args[1].get("params", {})
            self.assertIn("end_date_max", params)
            self.assertEqual(params.get("tag"), "crypto")
            self.assertEqual(params.get("closed"), "true")


if __name__ == "__main__":
    unittest.main()
