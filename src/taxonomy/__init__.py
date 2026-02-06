"""
Taxonomy system for eSports market classification.

Provides YAML-based taxonomy definitions, pattern matching classification,
and market type detection.
"""

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

__all__ = [
    "TeamNode",
    "TournamentNode",
    "GameNode",
    "TaxonomyConfig",
    "load_taxonomy",
    "PatternMatcher",
    "ClassificationResult",
    "detect_market_type",
]
