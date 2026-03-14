"""Tests for taxonomy-based entity normalization."""

from src.extraction.llm_extractor import EntityResult
from src.extraction.normalizer import normalize_entities


def test_known_alias_normalized() -> None:
    """Test that known team aliases are normalized to canonical names."""
    raw = EntityResult(
        team_a="NaVi", team_b="FaZe", tournament="IEM Katowice", game="CS2"
    )

    normalized = normalize_entities(raw)

    assert normalized.team_a == "Natus Vincere"
    assert normalized.team_b == "FaZe Clan"
    assert normalized.tournament == "IEM Katowice"
    assert normalized.game == "CS2"


def test_unknown_team_kept() -> None:
    """Test that unknown team names are kept as-is."""
    raw = EntityResult(
        team_a="SomeUnknownTeam",
        team_b="AnotherUnknown",
        tournament="Unknown Tournament",
    )

    normalized = normalize_entities(raw)

    assert normalized.team_a == "SomeUnknownTeam"
    assert normalized.team_b == "AnotherUnknown"
    assert normalized.tournament == "Unknown Tournament"


def test_none_fields_pass_through() -> None:
    """Test that None fields pass through unchanged."""
    raw = EntityResult()

    normalized = normalize_entities(raw)

    assert normalized.team_a is None
    assert normalized.team_b is None
    assert normalized.tournament is None
    assert normalized.game is None
    assert normalized.market_type is None


def test_game_normalized() -> None:
    """Test that game names are normalized (case-insensitive)."""
    raw = EntityResult(game="cs2")

    normalized = normalize_entities(raw)

    assert normalized.game == "CS2"


def test_tournament_normalized() -> None:
    """Test that tournament names are matched case-insensitively."""
    raw = EntityResult(tournament="iem katowice")

    normalized = normalize_entities(raw)

    assert normalized.tournament == "IEM Katowice"
