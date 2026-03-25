"""Tests for market resolution from closed Gamma events."""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
from decimal import Decimal

from src.gamma.events_resolver import (
    resolve_markets_from_closed_events,
    _determine_winner_index,
    _update_market_outcome,
)


class TestDetermineWinnerIndex:
    """Tests for _determine_winner_index helper function."""

    def test_clear_winner_high_price(self):
        """Returns index of token with price > 0.5 closest to 1.0."""
        outcome_prices = ["0.85", "0.15"]
        assert _determine_winner_index(outcome_prices) == 0

    def test_clear_winner_second_token(self):
        """Returns correct index when second token wins."""
        outcome_prices = ["0.25", "0.75"]
        assert _determine_winner_index(outcome_prices) == 1

    def test_no_clear_winner_all_below_threshold(self):
        """Returns None when all prices are <= 0.5."""
        outcome_prices = ["0.50", "0.40", "0.10"]
        assert _determine_winner_index(outcome_prices) is None

    def test_empty_prices(self):
        """Returns None for empty price list."""
        assert _determine_winner_index([]) is None

    def test_invalid_price_string(self):
        """Handles invalid price strings gracefully."""
        outcome_prices = ["invalid", "0.85", "0.15"]
        assert _determine_winner_index(outcome_prices) == 1

    def test_three_way_market(self):
        """Correctly handles three-outcome markets."""
        outcome_prices = ["0.60", "0.25", "0.15"]
        assert _determine_winner_index(outcome_prices) == 0


class TestUpdateMarketOutcome:
    """Tests for _update_market_outcome function."""

    def test_market_not_found(self):
        """Returns False when market doesn't exist in DB."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = (
            None
        )

        result = _update_market_outcome(
            mock_session,
            condition_id="0xnonexistent",
            winning_token_id="token123",
            outcome_prices=["0.85", "0.15"],
        )

        assert result is False

    def test_market_already_resolved(self):
        """Returns False when market already has outcome."""
        mock_session = MagicMock()
        mock_market = MagicMock()
        mock_market.outcome = "YES"
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_market
        )

        result = _update_market_outcome(
            mock_session,
            condition_id="0xtest123",
            winning_token_id="token123",
            outcome_prices=["0.85", "0.15"],
        )

        assert result is False

    def test_market_resolved_successfully(self):
        """Returns True and updates market when resolution succeeds."""
        mock_session = MagicMock()
        mock_market = MagicMock()
        mock_market.outcome = None
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_market
        )

        result = _update_market_outcome(
            mock_session,
            condition_id="0xtest456",
            winning_token_id="token123",
            outcome_prices=["0.85", "0.15"],
        )

        assert result is True
        assert mock_market.outcome == "YES"
        assert mock_market.active is False


class TestResolveMarketsFromClosedEvents:
    """Tests for resolve_markets_from_closed_events function."""

    @patch("src.gamma.events_resolver.GammaMarketClient")
    @patch("src.gamma.events_resolver.RateLimiter")
    def test_fetches_all_closed_events(self, mock_rate_limiter, mock_gamma_client):
        """Fetches events across multiple pages until exhausted."""
        mock_session = MagicMock()
        mock_client = Mock()
        mock_gamma_client.return_value = mock_client

        mock_events_page1 = [
            {
                "id": "event1",
                "markets": [
                    {
                        "conditionId": "0xmarket1",
                        "outcomePrices": ["0.85", "0.15"],
                        "clobTokenIds": ["token1", "token2"],
                    }
                ],
            }
        ]
        mock_events_page2 = [
            {
                "id": "event2",
                "markets": [
                    {
                        "conditionId": "0xmarket2",
                        "outcomePrices": ["0.25", "0.75"],
                        "clobTokenIds": ["token3", "token4"],
                    }
                ],
            }
        ]

        mock_client.get_events.side_effect = [
            mock_events_page1,
            mock_events_page2,
            [],
        ]

        mock_market1 = MagicMock()
        mock_market1.condition_id = "0xmarket1"
        mock_market1.outcome = None
        mock_market1.active = True

        mock_market2 = MagicMock()
        mock_market2.condition_id = "0xmarket2"
        mock_market2.outcome = None
        mock_market2.active = True

        mock_session.query.return_value.filter.return_value.one_or_none.side_effect = [
            mock_market1,
            mock_market2,
        ]

        result = resolve_markets_from_closed_events(mock_session, batch_size=200)

        assert result["events_fetched"] == 2
        assert result["markets_resolved"] == 2
        assert result["markets_updated"] == 2

        assert mock_market1.outcome == "YES"
        assert mock_market1.active is False
        assert mock_market2.outcome == "YES"
        assert mock_market2.active is False

    @patch("src.gamma.events_resolver.GammaMarketClient")
    @patch("src.gamma.events_resolver.RateLimiter")
    def test_skips_markets_not_in_db(self, mock_rate_limiter, mock_gamma_client):
        """Counts markets resolved but not updated if not in DB."""
        mock_session = MagicMock()
        mock_client = Mock()
        mock_gamma_client.return_value = mock_client

        mock_events = [
            {
                "id": "event1",
                "markets": [
                    {
                        "conditionId": "0xnotindb",
                        "outcomePrices": ["0.90", "0.10"],
                        "clobTokenIds": ["token1", "token2"],
                    }
                ],
            }
        ]

        # Return events once, then empty list to stop the loop
        mock_client.get_events.side_effect = [mock_events, []]
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = (
            None
        )

        result = resolve_markets_from_closed_events(mock_session, batch_size=200)

        assert result["events_fetched"] == 1
        assert result["markets_resolved"] == 1
        assert result["markets_updated"] == 0

    @patch("src.gamma.events_resolver.GammaMarketClient")
    @patch("src.gamma.events_resolver.RateLimiter")
    def test_skips_already_resolved_markets(self, mock_rate_limiter, mock_gamma_client):
        """Skips markets that already have outcome set."""
        mock_session = MagicMock()
        mock_client = Mock()
        mock_gamma_client.return_value = mock_client

        mock_events = [
            {
                "id": "event1",
                "markets": [
                    {
                        "conditionId": "0xalreadyresolved",
                        "outcomePrices": ["0.85", "0.15"],
                        "clobTokenIds": ["token1", "token2"],
                    }
                ],
            }
        ]

        # Return events once, then empty list to stop the loop
        mock_client.get_events.side_effect = [mock_events, []]

        mock_market = MagicMock()
        mock_market.outcome = "YES"
        mock_market.active = False
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_market
        )

        result = resolve_markets_from_closed_events(mock_session, batch_size=200)

        assert result["events_fetched"] == 1
        assert result["markets_resolved"] == 1
        assert result["markets_updated"] == 0

    @patch("src.gamma.events_resolver.GammaMarketClient")
    @patch("src.gamma.events_resolver.RateLimiter")
    def test_skips_already_resolved_markets(self, mock_rate_limiter, mock_gamma_client):
        """Skips markets that already have outcome set."""
        mock_session = MagicMock()
        mock_client = Mock()
        mock_gamma_client.return_value = mock_client

        mock_events = [
            {
                "id": "event1",
                "markets": [
                    {
                        "conditionId": "0xalreadyresolved",
                        "outcomePrices": ["0.85", "0.15"],
                        "clobTokenIds": ["token1", "token2"],
                    }
                ],
            }
        ]

        # Return events once, then empty list to stop the loop
        mock_client.get_events.side_effect = [mock_events, []]

        mock_market = MagicMock()
        mock_market.outcome = "YES"
        mock_market.active = False
        mock_session.query.return_value.filter.return_value.one_or_none.return_value = (
            mock_market
        )

        result = resolve_markets_from_closed_events(mock_session, batch_size=200)

        assert result["events_fetched"] == 1
        assert result["markets_resolved"] == 1
        assert result["markets_updated"] == 0
