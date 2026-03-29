"""Entity extraction module with pattern matcher and LLM fallback."""

from src.polymarket_analytics.extraction.llm import LLMFallback, EXTRACTION_PROMPT

__all__ = ["LLMFallback", "EXTRACTION_PROMPT"]
