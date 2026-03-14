"""Taxonomy-based normalization for LLM-extracted entities."""

from __future__ import annotations

from typing import Optional

import yaml
from pathlib import Path

from src.extraction.llm_extractor import EntityResult


def _load_alias_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Load esports taxonomy and build alias -> canonical maps.

    Returns:
        Tuple of (team_aliases, tournament_map, game_map) where:
        - team_aliases: maps alias.lower() -> canonical team name
        - tournament_map: maps tournament.name.lower() -> tournament.name
        - game_map: maps game.name.lower() -> game.name
    """
    yaml_path = (
        Path(__file__).parent.parent.parent / "data" / "taxonomy" / "esports.yaml"
    )

    team_aliases: dict[str, str] = {}
    tournament_map: dict[str, str] = {}
    game_map: dict[str, str] = {}

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    games = data.get("games", [])
    for game in games:
        game_name = game.get("name")
        if game_name:
            game_map[game_name.lower()] = game_name

        tournaments = game.get("tournaments", [])
        for tournament in tournaments:
            t_name = tournament.get("name")
            if t_name:
                tournament_map[t_name.lower()] = t_name

            teams = tournament.get("teams", [])
            for team in teams:
                team_name = team.get("name")
                if team_name:
                    team_aliases[team_name.lower()] = team_name

                aliases = team.get("aliases", [])
                for alias in aliases:
                    team_aliases[alias.lower()] = team_name

    return team_aliases, tournament_map, game_map


_TEAM_ALIASES, _TOURNAMENT_MAP, _GAME_MAP = _load_alias_maps()


def normalize_entities(result: EntityResult) -> EntityResult:
    """Normalize LLM-extracted entities using taxonomy aliases.

    Maps known aliases to canonical names:
    - team_a, team_b: "NaVi" -> "Natus Vincere", "FaZe" -> "FaZe Clan"
    - tournament: case-insensitive exact match
    - game: case-insensitive exact match
    - market_type: pass through unchanged
    - None values: pass through as None
    - Unknown names: keep as-is from LLM

    Args:
        result: EntityResult from extract_entities()

    Returns:
        New EntityResult with normalized fields (input unchanged)
    """

    def _normalize_team(name: Optional[str]) -> Optional[str]:
        if name is None:
            return None
        return _TEAM_ALIASES.get(name.lower(), name)

    def _normalize_tournament(name: Optional[str]) -> Optional[str]:
        if name is None:
            return None
        return _TOURNAMENT_MAP.get(name.lower(), name)

    def _normalize_game(name: Optional[str]) -> Optional[str]:
        if name is None:
            return None
        return _GAME_MAP.get(name.lower(), name)

    return EntityResult(
        team_a=_normalize_team(result.team_a),
        team_b=_normalize_team(result.team_b),
        tournament=_normalize_tournament(result.tournament),
        game=_normalize_game(result.game),
        market_type=result.market_type,
    )
