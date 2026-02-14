"""
Pure functions for concentration metrics and specialization classification.

This module provides two-tier concentration analysis:
1. eSports-level concentration: % of total volume in eSports
2. Game-level concentration: % of eSports volume in specific game

Design principles:
- Pure functions, no classes or state
- Duck-typed inputs (pre-computed Decimal volumes)
- All calculations use Decimal arithmetic
- No SQLAlchemy imports (keeps module pure and decoupled)

Concentration is a core component (~25% weight) of expertise scoring.
It enables the "niche hypothesis" — traders deeply focused in one game
likely have domain knowledge generalists don't.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SpecializationProfile:
    """
    Immutable two-tier specialization classification result.

    Attributes:
        esports_level: "specialist" if >= esports_threshold, else "generalist"
        game_level: "specialist" if >= game_threshold, else "generalist"
        esports_concentration: Decimal (0-1, fraction of total volume in eSports)
        game_concentration: Decimal (0-1, fraction of eSports volume in this game)
        primary_game: str | None (game slug if game specialist, None if generalist)
    """

    esports_level: str
    game_level: str
    esports_concentration: Decimal
    game_concentration: Decimal
    primary_game: str | None


def calculate_esports_concentration(
    esports_volume: Decimal, total_volume: Decimal
) -> Decimal:
    """
    Calculate eSports-level concentration (fraction of total volume in eSports).

    Args:
        esports_volume: Total volume in eSports markets (pre-computed Decimal)
        total_volume: Total volume across all markets (pre-computed Decimal)

    Returns:
        Fraction of total volume in eSports (0-1). Returns Decimal("0") if total_volume is 0.

    Examples:
        >>> calculate_esports_concentration(Decimal("70"), Decimal("100"))
        Decimal('0.7')

        >>> calculate_esports_concentration(Decimal("0"), Decimal("0"))
        Decimal('0')
    """
    if total_volume == Decimal("0"):
        return Decimal("0")

    return esports_volume / total_volume


def calculate_game_concentration(
    game_volume: Decimal, esports_volume: Decimal
) -> Decimal:
    """
    Calculate game-level concentration (fraction of eSports volume in specific game).

    Args:
        game_volume: Volume in specific game (pre-computed Decimal)
        esports_volume: Total volume in eSports (pre-computed Decimal)

    Returns:
        Fraction of eSports volume in this game (0-1). Returns Decimal("0") if esports_volume is 0.

    Examples:
        >>> calculate_game_concentration(Decimal("50"), Decimal("100"))
        Decimal('0.5')

        >>> calculate_game_concentration(Decimal("0"), Decimal("0"))
        Decimal('0')
    """
    if esports_volume == Decimal("0"):
        return Decimal("0")

    return game_volume / esports_volume


def calculate_tournament_concentration(
    tournament_volume: Decimal, game_volume: Decimal
) -> Decimal:
    """
    Calculate tournament-level concentration (fraction of game volume in specific tournament).

    Args:
        tournament_volume: Volume in specific tournament (pre-computed Decimal)
        game_volume: Total volume in the game (pre-computed Decimal)

    Returns:
        Fraction of game volume in this tournament (0-1). Returns Decimal("0") if game_volume is 0.

    Examples:
        >>> calculate_tournament_concentration(Decimal("30"), Decimal("100"))
        Decimal('0.3')

        >>> calculate_tournament_concentration(Decimal("0"), Decimal("0"))
        Decimal('0')
    """
    if game_volume == Decimal("0"):
        return Decimal("0")

    return tournament_volume / game_volume


def calculate_team_concentration(
    team_volume: Decimal, tournament_volume: Decimal
) -> Decimal:
    """
    Calculate team-level concentration (fraction of tournament volume for specific team).

    Args:
        team_volume: Volume for specific team (pre-computed Decimal)
        tournament_volume: Total volume in the tournament (pre-computed Decimal)

    Returns:
        Fraction of tournament volume for this team (0-1). Returns Decimal("0") if tournament_volume is 0.

    Examples:
        >>> calculate_team_concentration(Decimal("20"), Decimal("50"))
        Decimal('0.4')

        >>> calculate_team_concentration(Decimal("0"), Decimal("0"))
        Decimal('0')
    """
    if tournament_volume == Decimal("0"):
        return Decimal("0")

    return team_volume / tournament_volume


def classify_specialization(
    esports_concentration: Decimal,
    game_concentration: Decimal,
    game_slug: str,
    esports_threshold: Decimal = Decimal("0.7"),
    game_threshold: Decimal = Decimal("0.5"),
) -> SpecializationProfile:
    """
    Classify trader specialization at both eSports and game levels.

    Uses configurable thresholds to determine specialist vs generalist status.
    A trader can be specialist in multiple games simultaneously (independent per call).

    Thresholds:
        - esports_threshold: Default 0.7 (70% of total volume in eSports)
        - game_threshold: Default 0.5 (50% of eSports volume in one game)

    Note: Game threshold is lower than eSports threshold because a trader
    active in 2 games can be specialist in both at 50%+ each.

    Args:
        esports_concentration: Fraction of total volume in eSports (0-1)
        game_concentration: Fraction of eSports volume in specific game (0-1)
        game_slug: Game identifier (e.g., "esports.cs2")
        esports_threshold: Minimum concentration for eSports specialist (default 0.7)
        game_threshold: Minimum concentration for game specialist (default 0.5)

    Returns:
        SpecializationProfile with classifications and concentrations

    Examples:
        >>> classify_specialization(Decimal("0.9"), Decimal("0.8"), "esports.cs2")
        SpecializationProfile(esports_level='specialist', game_level='specialist', ...)

        >>> classify_specialization(Decimal("0.3"), Decimal("0.8"), "esports.dota2")
        SpecializationProfile(esports_level='generalist', game_level='specialist', ...)
    """
    # Classify eSports level
    esports_level = (
        "specialist" if esports_concentration >= esports_threshold else "generalist"
    )

    # Classify game level
    game_level = (
        "specialist" if game_concentration >= game_threshold else "generalist"
    )

    # Set primary_game only if game-level specialist
    primary_game = game_slug if game_level == "specialist" else None

    return SpecializationProfile(
        esports_level=esports_level,
        game_level=game_level,
        esports_concentration=esports_concentration,
        game_concentration=game_concentration,
        primary_game=primary_game,
    )
