"""Pydantic-based niche configuration validation system."""

from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field


class NicheConfig(BaseModel):
    """Configuration model for a Polymarket niche.

    Attributes:
        tag_id: Polymarket tag ID for this niche (required, integer)
        slug: Niche slug for file naming, e.g., "esports" (required)
        min_positions: Minimum positions for trader qualification (default: 10, min: 1)
        scoring_window_days: Rolling window for score calculation (default: 30, min: 1)
        entity_fields: Entity types to extract from market questions (default: [])
    """

    tag_id: int = Field(..., description="Polymarket tag ID for this niche (integer)")
    slug: str = Field(..., description="Niche slug for file naming (e.g., 'esports')")
    min_positions: int = Field(
        default=10, ge=1, description="Minimum positions for trader qualification"
    )
    scoring_window_days: int = Field(
        default=30, ge=1, description="Rolling window for score calculation in days"
    )
    entity_fields: List[str] = Field(
        default_factory=list,
        description="Entity types to extract (game, team, player, etc.)",
    )


def load_niche_config(config_path: Path) -> NicheConfig:
    """Load and validate a niche configuration file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Validated NicheConfig instance

    Raises:
        FileNotFoundError: If config file does not exist
        yaml.YAMLError: If YAML parsing fails
        ValidationError: If required fields are missing or type constraints violated
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    return NicheConfig(**data)
