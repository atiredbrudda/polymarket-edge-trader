"""Tests for LLM-based entity extraction."""

from unittest.mock import MagicMock

import anthropic
import pytest

from src.extraction.llm_extractor import EntityResult, extract_entities


def test_extract_match_market() -> None:
    """Test extraction of a match market with both teams."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"team_a": "NaVi", "team_b": "FaZe", "tournament": "IEM Katowice", "game": "CS2", "market_type": "match"}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    result = extract_entities(
        "NaVi vs FaZe — who wins map 1 at IEM Katowice?", client=mock_client
    )

    assert result.team_a == "NaVi"
    assert result.team_b == "FaZe"
    assert result.tournament == "IEM Katowice"
    assert result.game == "CS2"
    assert result.market_type == "match"


def test_extract_prop_market() -> None:
    """Test extraction of a prop market with tournament only."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='{"team_a": null, "team_b": null, "tournament": "The International", "game": "Dota 2", "market_type": "prop"}'
        )
    ]
    mock_client.messages.create.return_value = mock_response

    result = extract_entities(
        "Will Team Spirit win The International?", client=mock_client
    )

    assert result.team_a is None
    assert result.team_b is None
    assert result.tournament == "The International"
    assert result.game == "Dota 2"
    assert result.market_type == "prop"


def test_extract_api_failure() -> None:
    """Test that API errors return EntityResult with all None."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIError(
        message="API error",
        request=MagicMock(),
        body={"error": {"message": "test error"}},
    )

    result = extract_entities("Some question", client=mock_client)

    assert result.team_a is None
    assert result.team_b is None
    assert result.tournament is None
    assert result.game is None
    assert result.market_type is None


def test_extract_malformed_json() -> None:
    """Test that malformed JSON returns EntityResult with all None."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This is not JSON")]
    mock_client.messages.create.return_value = mock_response

    result = extract_entities("Some question", client=mock_client)

    assert result.team_a is None
    assert result.team_b is None
    assert result.tournament is None
    assert result.game is None
    assert result.market_type is None
