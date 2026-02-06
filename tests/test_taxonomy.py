"""
Tests for taxonomy system (models, loader, classifier).

TDD RED phase: All tests written before implementation.
Tests drive the design of the taxonomy system.
"""

import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from src.taxonomy.models import (
    TeamNode,
    TournamentNode,
    GameNode,
    TaxonomyConfig,
)
from src.taxonomy.loader import load_taxonomy
from src.taxonomy.classifier import (
    PatternMatcher,
    ClassificationResult,
    detect_market_type,
)


# =============================================================================
# MODEL TESTS
# =============================================================================


def test_team_node_valid():
    """TeamNode with name and patterns validates."""
    team = TeamNode(
        name="Natus Vincere",
        patterns=[r"\bNaVi\b", r"\bNatus\s+Vincere\b"],
        aliases=["NaVi", "Born to Win"],
    )
    assert team.name == "Natus Vincere"
    assert len(team.patterns) == 2
    assert team.aliases == ["NaVi", "Born to Win"]


def test_game_node_with_tournaments():
    """Nested hierarchy validates."""
    game = GameNode(
        name="CS2",
        patterns=[r"\bCS2\b", r"\bCounter-Strike\s+2\b"],
        tournaments=[
            TournamentNode(
                name="IEM Katowice",
                patterns=[r"\bIEM\s+Katowice\b"],
                tier="major",
                teams=[
                    TeamNode(name="NaVi", patterns=[r"\bNaVi\b"]),
                    TeamNode(name="FaZe", patterns=[r"\bFaZe\b"]),
                ],
            )
        ],
    )
    assert game.name == "CS2"
    assert len(game.tournaments) == 1
    assert game.tournaments[0].name == "IEM Katowice"
    assert len(game.tournaments[0].teams) == 2


def test_taxonomy_config_full():
    """Complete 4-level config validates."""
    config = TaxonomyConfig(
        name="eSports",
        games=[
            GameNode(
                name="CS2",
                patterns=[r"\bCS2\b"],
                tournaments=[
                    TournamentNode(
                        name="IEM Katowice",
                        patterns=[r"\bIEM\s+Katowice\b"],
                        teams=[TeamNode(name="NaVi", patterns=[r"\bNaVi\b"])],
                    )
                ],
            )
        ],
    )
    assert config.name == "eSports"
    assert len(config.games) == 1


def test_taxonomy_config_rejects_empty_games():
    """Validation fails with empty games list."""
    with pytest.raises(ValidationError):
        TaxonomyConfig(name="eSports", games=[])


# =============================================================================
# LOADER TESTS
# =============================================================================


def test_load_taxonomy_valid_file(tmp_path):
    """Loads seed YAML, returns TaxonomyConfig with correct game count."""
    yaml_content = """
name: eSports
games:
  - name: CS2
    patterns:
      - "\\\\bCS2\\\\b"
      - "\\\\bCounter-Strike\\\\s+2\\\\b"
    tournaments:
      - name: IEM Katowice
        patterns:
          - "\\\\bIEM\\\\s+Katowice\\\\b"
        tier: major
        teams:
          - name: NaVi
            patterns:
              - "\\\\bNaVi\\\\b"
              - "\\\\bNatus\\\\s+Vincere\\\\b"
          - name: FaZe
            patterns:
              - "\\\\bFaZe\\\\b"
"""
    yaml_file = tmp_path / "test_taxonomy.yaml"
    yaml_file.write_text(yaml_content)

    taxonomy = load_taxonomy(yaml_file)
    assert isinstance(taxonomy, TaxonomyConfig)
    assert len(taxonomy.games) == 1
    assert taxonomy.games[0].name == "CS2"


def test_load_taxonomy_missing_file():
    """Raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_taxonomy(Path("/nonexistent/file.yaml"))


def test_load_taxonomy_invalid_yaml(tmp_path):
    """Raises yaml.YAMLError on broken syntax."""
    yaml_file = tmp_path / "broken.yaml"
    yaml_file.write_text("name: eSports\ngames: [invalid yaml structure {")

    with pytest.raises(yaml.YAMLError):
        load_taxonomy(yaml_file)


def test_load_taxonomy_invalid_schema(tmp_path):
    """Raises ValidationError on valid YAML with wrong structure."""
    yaml_content = """
name: eSports
games:
  - wrong_field: "This should be 'name'"
"""
    yaml_file = tmp_path / "invalid_schema.yaml"
    yaml_file.write_text(yaml_content)

    with pytest.raises(ValidationError):
        load_taxonomy(yaml_file)


# =============================================================================
# CLASSIFIER TESTS
# =============================================================================


@pytest.fixture
def sample_taxonomy():
    """Sample taxonomy for classifier tests."""
    return TaxonomyConfig(
        name="eSports",
        games=[
            GameNode(
                name="CS2",
                patterns=[r"\bCS2\b", r"\bCounter-Strike\s+2\b"],
                tournaments=[
                    TournamentNode(
                        name="IEM Katowice",
                        patterns=[r"\bIEM\s+Katowice\b"],
                        tier="major",
                        teams=[
                            TeamNode(
                                name="Natus Vincere",
                                patterns=[r"\bNaVi\b", r"\bNatus\s+Vincere\b"],
                            ),
                            TeamNode(
                                name="FaZe Clan",
                                patterns=[r"\bFaZe\s+Clan\b", r"\bFaZe\b"],
                            ),
                        ],
                    )
                ],
            ),
            GameNode(
                name="Dota 2",
                patterns=[r"\bDota\s+2\b", r"\bDota2\b"],
                tournaments=[],
            ),
        ],
    )


def test_classify_game_level(sample_taxonomy):
    """CS2 Major Finals -> depth=1, game=CS2."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify("CS2 Major Finals upcoming")

    assert result is not None
    assert result.depth == 1
    assert result.game == "CS2"
    assert result.tournament is None
    assert result.team is None


def test_classify_tournament_level(sample_taxonomy):
    """IEM Katowice 2025 Grand Final -> depth=2, tournament=IEM Katowice."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify("IEM Katowice 2025 Grand Final")

    assert result is not None
    assert result.depth == 2
    assert result.game == "CS2"
    assert result.tournament == "IEM Katowice"
    assert result.team is None


def test_classify_team_level(sample_taxonomy):
    """NaVi vs FaZe Clan - IEM Katowice -> depth=3, team detected."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify("NaVi vs FaZe Clan - IEM Katowice")

    assert result is not None
    assert result.depth == 3
    assert result.game == "CS2"
    assert result.tournament == "IEM Katowice"
    assert result.team in ["Natus Vincere", "FaZe Clan"]


def test_classify_deepest_wins(sample_taxonomy):
    """Title matching game AND team returns team-level (depth 3)."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify("CS2 NaVi performance analysis")

    assert result is not None
    # Should match team level since NaVi pattern exists
    assert result.depth == 3
    assert result.team == "Natus Vincere"


def test_classify_no_match(sample_taxonomy):
    """US Presidential Election -> None."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify("US Presidential Election 2024")

    assert result is None


def test_classify_with_review_flags_unknown(sample_taxonomy):
    """Non-matching title gets flagged_for_review=True."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify_with_review("Bitcoin price prediction")

    assert result is not None
    assert result.flagged_for_review is True
    assert result.depth == 0


def test_classify_partial_match_flags(sample_taxonomy):
    """Game matches but 'vs' in title with no team match -> flagged."""
    matcher = PatternMatcher(sample_taxonomy)
    result = matcher.classify_with_review("CS2 TeamA vs TeamB unknown teams")

    assert result is not None
    assert result.flagged_for_review is True
    # Should have matched game but flagged due to 'vs' without team match


# =============================================================================
# MARKET TYPE DETECTION TESTS
# =============================================================================


def test_detect_match_type():
    """Team A vs Team B -> match."""
    assert detect_market_type("Team A vs Team B") == "match"
    assert detect_market_type("NaVi v FaZe") == "match"
    assert detect_market_type("Team Liquid - Cloud9") == "match"


def test_detect_prop_type():
    """Tournament Winner -> prop."""
    assert detect_market_type("IEM Katowice Winner") == "prop"
    assert detect_market_type("Top 3 finish") == "prop"
    assert detect_market_type("Over 2.5 maps") == "prop"
    assert detect_market_type("Tournament MVP") == "prop"


def test_detect_ambiguous_type():
    """Some random title -> None."""
    assert detect_market_type("Random market title") is None
    assert detect_market_type("CS2 Major") is None
