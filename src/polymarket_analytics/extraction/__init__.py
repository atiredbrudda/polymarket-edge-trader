"""Entity extraction module with pattern matcher and LLM fallback."""

from src.polymarket_analytics.extraction.llm import LLMFallback, EXTRACTION_PROMPT
from src.polymarket_analytics.extraction.patterns import (
    EntityPatternMatcher,
    GAME_PATTERNS,
    TEAM_PATTERNS,
    TOURNAMENT_PATTERNS,
)

__all__ = [
    "EntityPatternMatcher",
    "GAME_PATTERNS",
    "TEAM_PATTERNS",
    "TOURNAMENT_PATTERNS",
    "LLMFallback",
    "EXTRACTION_PROMPT",
]
