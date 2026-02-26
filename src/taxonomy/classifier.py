"""
Pattern-based market classifier with market type detection.

Uses precompiled regex patterns for efficient classification.
Implements deepest-match-wins strategy for hierarchical taxonomy.
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

from src.taxonomy.models import TaxonomyConfig, GameNode, TournamentNode, TeamNode


@dataclass
class ClassificationResult:
    """Result of market classification."""

    node_path: str  # e.g., "eSports.CS2.IEM Katowice.NaVi"
    depth: int  # 0=root, 1=game, 2=tournament, 3=team
    game: Optional[str] = None
    tournament: Optional[str] = None
    team: Optional[str] = None
    market_type: Optional[str] = None  # "match" or "prop"
    matched_pattern: str = ""
    flagged_for_review: bool = False


class PatternMatcher:
    """
    Precompiled regex pattern matcher for taxonomy classification.

    Compiles all patterns at initialization for O(patterns) classification time.
    Implements deepest-match-wins strategy.
    """

    def __init__(self, taxonomy: TaxonomyConfig):
        """
        Initialize with taxonomy and precompile all patterns.

        Args:
            taxonomy: TaxonomyConfig with game/tournament/team hierarchy
        """
        self.taxonomy = taxonomy
        self.patterns: List[Tuple[re.Pattern, int, str, dict]] = []
        self._compile_patterns()

    def _compile_patterns(self):
        """Precompile all regex patterns with metadata."""
        # Depth 1: Games
        for game in self.taxonomy.games:
            for pattern_str in game.patterns:
                pattern = re.compile(pattern_str, re.IGNORECASE)
                metadata = {
                    "game": game.name,
                    "tournament": None,
                    "team": None,
                }
                node_path = f"{self.taxonomy.name}.{game.name}"
                self.patterns.append((pattern, 1, node_path, metadata))

            # Depth 2: Tournaments
            for tournament in game.tournaments:
                for pattern_str in tournament.patterns:
                    pattern = re.compile(pattern_str, re.IGNORECASE)
                    metadata = {
                        "game": game.name,
                        "tournament": tournament.name,
                        "team": None,
                    }
                    node_path = f"{self.taxonomy.name}.{game.name}.{tournament.name}"
                    self.patterns.append((pattern, 2, node_path, metadata))

                # Depth 3: Teams
                for team in tournament.teams:
                    for pattern_str in team.patterns:
                        pattern = re.compile(pattern_str, re.IGNORECASE)
                        metadata = {
                            "game": game.name,
                            "tournament": tournament.name,
                            "team": team.name,
                        }
                        node_path = (
                            f"{self.taxonomy.name}.{game.name}.{tournament.name}.{team.name}"
                        )
                        self.patterns.append((pattern, 3, node_path, metadata))

    def classify(self, market_title: str) -> Optional[ClassificationResult]:
        """
        Classify market title to deepest matching taxonomy node.

        Args:
            market_title: Market title to classify

        Returns:
            ClassificationResult with deepest match, or None if no match
        """
        best_match = None
        best_depth = -1

        for pattern, depth, node_path, metadata in self.patterns:
            if pattern.search(market_title):
                if depth > best_depth:
                    best_depth = depth
                    best_match = (pattern, depth, node_path, metadata)

        if best_match is None:
            return None

        pattern, depth, node_path, metadata = best_match
        market_type = detect_market_type(market_title)

        return ClassificationResult(
            node_path=node_path,
            depth=depth,
            game=metadata["game"],
            tournament=metadata["tournament"],
            team=metadata["team"],
            market_type=market_type,
            matched_pattern=pattern.pattern,
            flagged_for_review=False,
        )

    def classify_with_review(self, market_title: str) -> ClassificationResult:
        """
        Classify with review flagging for unmatched or partial matches.

        Args:
            market_title: Market title to classify

        Returns:
            ClassificationResult, always returns a result (flagged if problematic)
        """
        result = self.classify(market_title)

        if result is None:
            # No match at all — return empty node_path so taxonomy_node_id stays NULL.
            # Using root name as node_path previously caused every non-eSports market
            # (politics, crypto, etc.) to be classified under the eSports root node.
            return ClassificationResult(
                node_path="",
                depth=0,
                flagged_for_review=True,
            )

        # Check for partial match: "vs" in title but no team match
        has_vs = bool(
            re.search(r"\bvs\.?\b|\bv\b|\b-\b|\b@\b", market_title, re.IGNORECASE)
        )
        if has_vs and result.team is None:
            result.flagged_for_review = True

        return result


# =============================================================================
# MARKET TYPE DETECTION
# =============================================================================

# Precompiled patterns for market type detection
_MATCH_PATTERNS = [
    re.compile(r"\bvs\.?\b", re.IGNORECASE),
    re.compile(r"\bv\b", re.IGNORECASE),
    re.compile(r"\w+\s+-\s+\w+", re.IGNORECASE),  # Team A - Team B (with context)
    re.compile(r"\b@\b", re.IGNORECASE),  # Team A @ Team B
]

_PROP_PATTERNS = [
    re.compile(r"\bwinner\b", re.IGNORECASE),
    re.compile(r"\btop\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bover\s+\d+\.?\d*\b", re.IGNORECASE),
    re.compile(r"\bchampion\b", re.IGNORECASE),
    re.compile(r"\bMVP\b", re.IGNORECASE),
]


def detect_market_type(market_title: str) -> Optional[str]:
    """
    Detect if market is a match (head-to-head) or prop (winner/stats) market.

    Args:
        market_title: Market title to analyze

    Returns:
        "match" for head-to-head markets, "prop" for props, None if ambiguous
    """
    match_score = sum(1 for p in _MATCH_PATTERNS if p.search(market_title))
    prop_score = sum(1 for p in _PROP_PATTERNS if p.search(market_title))

    if match_score > prop_score:
        return "match"
    elif prop_score > match_score:
        return "prop"
    else:
        return None
