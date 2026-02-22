"""Tests for market outcome resolution from Gamma event data."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.gamma.resolution import (
    classify_token_outcome,
    determine_winner,
    resolve_market_outcomes,
)


class TestDetermineWinner:
    """Tests for determine_winner function."""

    def test_tok_a_wins(self):
        result = determine_winner(["tok_a", "tok_b"], ["0.99", "0.01"])
        assert result == "tok_a"

    def test_tok_b_wins(self):
        result = determine_winner(["tok_a", "tok_b"], ["0.01", "0.99"])
        assert result == "tok_b"

    def test_multi_outcome_event(self):
        result = determine_winner(
            ["tok_a", "tok_b", "tok_c"], ["0.8", "0.15", "0.05"]
        )
        assert result == "tok_a"

    def test_no_clear_winner_both_at_05(self):
        result = determine_winner(["tok_a", "tok_b"], ["0.5", "0.5"])
        assert result is None

    def test_empty_inputs(self):
        result = determine_winner([], [])
        assert result is None

    def test_single_token_event(self):
        result = determine_winner(["tok_a"], ["0.99"])
        assert result == "tok_a"

    def test_length_mismatch(self):
        result = determine_winner(["tok_a", "tok_b"], ["0.99"])
        assert result is None

    def test_empty_token_ids(self):
        result = determine_winner([], ["0.99"])
        assert result is None

    def test_empty_prices(self):
        result = determine_winner(["tok_a"], [])
        assert result is None

    def test_malformed_price_string(self):
        result = determine_winner(["tok_a", "tok_b"], ["invalid", "0.99"])
        assert result == "tok_b"

    def test_all_prices_below_threshold(self):
        result = determine_winner(["tok_a", "tok_b"], ["0.3", "0.4"])
        assert result is None


class TestClassifyTokenOutcome:
    """Tests for classify_token_outcome function."""

    def test_winning_token_returns_yes(self):
        result = classify_token_outcome("tok_a", "tok_a")
        assert result == "YES"

    def test_losing_token_returns_no(self):
        result = classify_token_outcome("tok_b", "tok_a")
        assert result == "NO"

    def test_different_tokens_return_no(self):
        result = classify_token_outcome("tok_x", "tok_y")
        assert result == "NO"


class TestResolveMarketOutcomes:
    """Tests for resolve_market_outcomes function."""

    def test_resolves_single_market(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = json.dumps([
            {"token_id": "tok_a", "outcome": ""},
            {"token_id": "tok_b", "outcome": ""},
        ])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_b"])
        mock_event.outcome_prices = json.dumps(["0.99", "0.01"])

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = [mock_event]

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 2
        assert result["skipped_events"] == 0
        assert result["skipped_tokens"] == 0

    def test_skips_tokens_not_in_markets(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = json.dumps([
            {"token_id": "tok_a", "outcome": ""},
        ])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_unknown"])
        mock_event.outcome_prices = json.dumps(["0.99", "0.01"])

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = [mock_event]

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 1
        assert result["skipped_tokens"] == 1

    def test_skips_events_with_no_clear_winner(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = json.dumps([
            {"token_id": "tok_a", "outcome": ""},
        ])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_b"])
        mock_event.outcome_prices = json.dumps(["0.5", "0.5"])

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = [mock_event]

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 0
        assert result["skipped_events"] == 1

    def test_handles_malformed_json(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = json.dumps([
            {"token_id": "tok_a", "outcome": ""},
        ])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = "not valid json"
        mock_event.outcome_prices = json.dumps(["0.99", "0.01"])

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = [mock_event]

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 0
        assert result["skipped_events"] == 1

    def test_handles_null_tokens_field(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = None

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = []

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 0

    def test_idempotent_re_run(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = json.dumps([
            {"token_id": "tok_a", "outcome": ""},
        ])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = json.dumps(["tok_a"])
        mock_event.outcome_prices = json.dumps(["0.99"])

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = [mock_event]

        result1 = resolve_market_outcomes(mock_session)
        result2 = resolve_market_outcomes(mock_session)

        assert result1["resolved"] == 1
        assert result2["resolved"] == 1

    def test_multi_outcome_event_resolution(self):
        mock_session = MagicMock()

        mock_market_a = MagicMock()
        mock_market_a.tokens = json.dumps([{"token_id": "tok_a", "outcome": ""}])

        mock_market_b = MagicMock()
        mock_market_b.tokens = json.dumps([{"token_id": "tok_b", "outcome": ""}])

        mock_market_c = MagicMock()
        mock_market_c.tokens = json.dumps([{"token_id": "tok_c", "outcome": ""}])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_b", "tok_c"])
        mock_event.outcome_prices = json.dumps(["0.8", "0.15", "0.05"])

        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_market_a, mock_market_b, mock_market_c
        ]
        mock_session.query.return_value.all.return_value = [mock_event]

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 3
        assert mock_market_a.outcome == "YES"
        assert mock_market_b.outcome == "NO"
        assert mock_market_c.outcome == "NO"

    def test_null_clob_token_ids(self):
        mock_session = MagicMock()

        mock_market = MagicMock()
        mock_market.tokens = json.dumps([
            {"token_id": "tok_a", "outcome": ""},
        ])

        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.clob_token_ids = None
        mock_event.outcome_prices = json.dumps(["0.99"])

        mock_session.query.return_value.filter.return_value.all.return_value = [mock_market]
        mock_session.query.return_value.all.return_value = [mock_event]

        result = resolve_market_outcomes(mock_session)

        assert result["resolved"] == 0
        assert result["skipped_events"] == 1
