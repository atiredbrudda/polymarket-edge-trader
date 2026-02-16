"""Tests for profile resolution functionality."""

import unittest
from unittest.mock import patch, MagicMock

import httpx


class TestGetPublicProfile(unittest.TestCase):
    """Test cases for get_public_profile method."""

    def test_get_public_profile_success(self):
        """Test successful profile fetch returns dict."""
        from src.api.gamma_client import GammaMarketClient

        mock_profile = {
            "proxyWallet": "0xProxy123",
            "name": "TestTrader",
            "pseudonym": "test_trader",
            "bio": "Test bio",
            "profileImage": "https://example.com/avatar.png",
            "createdAt": "2024-01-01T00:00:00Z",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_profile

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            result = client.get_public_profile("0xTestAddress")

            self.assertEqual(result, mock_profile)
            call_args = mock_get.call_args
            self.assertEqual(
                call_args[0][0], "https://gamma-api.polymarket.com/public-profile"
            )
            params = call_args[1].get("params", {})
            self.assertEqual(params.get("address"), "0xtestaddress")

    def test_get_public_profile_not_found(self):
        """Test 404 returns None."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            result = client.get_public_profile("0xNoProfile")

            self.assertIsNone(result)
            mock_get.assert_called_once()

    def test_get_public_profile_with_rate_limiter(self):
        """Test rate limiter is used when configured."""
        from src.api.gamma_client import GammaMarketClient
        from src.api.rate_limiter import RateLimiter

        mock_profile = {"proxyWallet": "0xProxy", "name": "Trader"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_profile

        mock_limiter = MagicMock(spec=RateLimiter)

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient(rate_limiter=mock_limiter)
            client.get_public_profile("0xTest")

            mock_limiter.acquire.assert_called_once()
            mock_get.assert_called_once()

    def test_get_public_profile_normalizes_address(self):
        """Test address is lowercased in request."""
        from src.api.gamma_client import GammaMarketClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client = GammaMarketClient()
            client.get_public_profile("0xUPPERCASE")

            call_args = mock_get.call_args
            params = call_args[1].get("params", {})
            self.assertEqual(params.get("address"), "0xuppercase")


class TestResolveTraderProfiles(unittest.TestCase):
    """Test cases for resolve_trader_profiles pipeline method."""

    @patch("src.pipeline.ingest.GammaMarketClient")
    def test_resolve_trader_profiles_with_profiles(self, mock_gamma_class):
        """Test resolving traders with existing profiles."""
        from src.pipeline.ingest import IngestionPipeline
        from src.db.models import Trader
        from src.api.client import PolymarketClient
        from src.pipeline.filters import CategoryFilter

        mock_gamma_client = MagicMock()
        mock_gamma_client.get_public_profile.return_value = {
            "proxyWallet": "0xProxy123",
            "name": "TestTrader",
        }

        mock_client = MagicMock(spec=PolymarketClient)
        mock_session_factory = MagicMock()

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            CategoryFilter(["eSports"]),
            gamma_client=mock_gamma_client,
        )

        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session

        mock_trader = MagicMock(spec=Trader)
        mock_trader.address = "0xTestAddress"
        mock_trader.proxy_wallet = None
        mock_trader.display_name = None
        mock_trader.profile_resolved = False
        mock_trader.has_profile = False

        mock_session.query.return_value.filter_by.return_value.all.return_value = [
            mock_trader
        ]
        mock_session.query.return_value.filter_by.return_value.limit.return_value.all.return_value = [
            mock_trader
        ]

        with patch.object(pipeline, "session_factory", mock_session_factory):
            profiles_found = pipeline.resolve_trader_profiles(limit=1)

        mock_gamma_client.get_public_profile.assert_called_once_with("0xTestAddress")
        self.assertEqual(profiles_found, 1)

    @patch("src.pipeline.ingest.GammaMarketClient")
    def test_resolve_trader_profiles_no_gamma_client(self, mock_gamma_class):
        """Test returns 0 when gamma client not configured."""
        from src.pipeline.ingest import IngestionPipeline
        from src.api.client import PolymarketClient
        from src.pipeline.filters import CategoryFilter

        mock_client = MagicMock(spec=PolymarketClient)
        mock_session_factory = MagicMock()

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            CategoryFilter(["eSports"]),
            gamma_client=None,
        )

        profiles_found = pipeline.resolve_trader_profiles()

        self.assertEqual(profiles_found, 0)

    @patch("src.pipeline.ingest.GammaMarketClient")
    def test_resolve_trader_profiles_404_sets_has_profile_false(self, mock_gamma_class):
        """Test 404 response sets has_profile=False."""
        from src.pipeline.ingest import IngestionPipeline
        from src.db.models import Trader
        from src.api.client import PolymarketClient
        from src.pipeline.filters import CategoryFilter

        mock_gamma_client = MagicMock()
        mock_gamma_client.get_public_profile.return_value = None

        mock_client = MagicMock(spec=PolymarketClient)
        mock_session_factory = MagicMock()

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            CategoryFilter(["eSports"]),
            gamma_client=mock_gamma_client,
        )

        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session

        mock_trader = MagicMock(spec=Trader)
        mock_trader.address = "0xNoProfile"
        mock_trader.profile_resolved = False

        mock_session.query.return_value.filter_by.return_value.all.return_value = [
            mock_trader
        ]
        mock_session.query.return_value.filter_by.return_value.limit.return_value.all.return_value = [
            mock_trader
        ]

        with patch.object(pipeline, "session_factory", mock_session_factory):
            profiles_found = pipeline.resolve_trader_profiles(limit=1)

        self.assertEqual(profiles_found, 0)


if __name__ == "__main__":
    unittest.main()
