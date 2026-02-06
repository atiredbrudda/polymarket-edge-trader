"""
Pydantic models for 4-level eSports taxonomy hierarchy.

Hierarchy: eSports > Game > Tournament > Team
Each level has regex patterns for classification.
"""

from typing import List, Optional
from pydantic import BaseModel, field_validator


class TeamNode(BaseModel):
    """Team in a tournament (depth 3)."""

    name: str
    patterns: List[str]  # Regex patterns for matching
    aliases: Optional[List[str]] = None

    @field_validator("patterns")
    @classmethod
    def patterns_not_empty(cls, v: List[str]) -> List[str]:
        """Ensure at least one pattern exists."""
        if not v:
            raise ValueError("patterns list cannot be empty")
        return v


class TournamentNode(BaseModel):
    """Tournament within a game (depth 2)."""

    name: str
    patterns: List[str]  # Regex patterns for matching
    tier: Optional[str] = None  # e.g., "major", "minor", "qualifier"
    teams: List[TeamNode] = []

    @field_validator("patterns")
    @classmethod
    def patterns_not_empty(cls, v: List[str]) -> List[str]:
        """Ensure at least one pattern exists."""
        if not v:
            raise ValueError("patterns list cannot be empty")
        return v


class GameNode(BaseModel):
    """Game (depth 1)."""

    name: str
    patterns: List[str]  # Regex patterns for matching
    tournaments: List[TournamentNode] = []

    @field_validator("patterns")
    @classmethod
    def patterns_not_empty(cls, v: List[str]) -> List[str]:
        """Ensure at least one pattern exists."""
        if not v:
            raise ValueError("patterns list cannot be empty")
        return v


class TaxonomyConfig(BaseModel):
    """Root taxonomy configuration (depth 0)."""

    name: str = "eSports"
    games: List[GameNode]

    @field_validator("games")
    @classmethod
    def games_not_empty(cls, v: List[GameNode]) -> List[GameNode]:
        """Ensure at least one game exists."""
        if not v:
            raise ValueError("games list cannot be empty")
        return v
