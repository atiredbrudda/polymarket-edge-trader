"""Entity extraction module with pattern matcher, slug parser, and LLM fallback."""

from polymarket_analytics.extraction.llm import LLMFallback, EXTRACTION_PROMPT
from polymarket_analytics.extraction.patterns import (
    EntityPatternMatcher,
    GAME_PATTERNS,
    TEAM_PATTERNS,
    TOURNAMENT_PATTERNS,
)
from polymarket_analytics.extraction.slug_parser import parse_event_slug

__all__ = [
    "EntityPatternMatcher",
    "GAME_PATTERNS",
    "TEAM_PATTERNS",
    "TOURNAMENT_PATTERNS",
    "LLMFallback",
    "EXTRACTION_PROMPT",
    "parse_event_slug",
]
