"""LLM fallback for entity extraction when pattern matcher fails.

This module provides Anthropic Claude integration for extracting entities
from market questions when the regex pattern matcher returns None for
critical fields (game, team_a, team_b).

Cost Control: Only use when pattern matcher fails. Do not call for every market.
"""

import json
import os
import time
from typing import Any, Dict, Optional

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Prompt template for entity extraction
EXTRACTION_PROMPT = """
You are an entity extraction assistant for eSports prediction markets.

Extract the following entities from the market question:
- game: The video game title (CS2, LoL, Dota 2, Valorant, etc.)
- team_a: First team/player name
- team_b: Second team/player name
- tournament: Tournament/championship name
- market_type: Type of bet (winner, total_maps, handicap, etc.)

Market Question: "{question}"

Return ONLY a valid JSON object with this exact structure:
{{
  "game": "string or null",
  "team_a": "string or null",
  "team_b": "string or null",
  "tournament": "string or null",
  "market_type": "string or null"
}}

Do not include any other text. Return null for fields you cannot confidently extract.
"""


class LLMFallback:
    """LLM fallback for entity extraction using Anthropic API.

    This class should only be used when the pattern matcher fails to extract
    critical entities (game, team_a, team_b) from a market question.

    Attributes:
        client: Anthropic API client instance
        model: Model name to use for extraction

    Example:
        >>> llm = LLMFallback()
        >>> entities = llm.extract("Will T1 beat G2 in LoL Worlds 2025?")
        >>> print(entities)
        {"game": "LoL", "team_a": "T1", "team_b": "G2", "tournament": "Worlds 2025", ...}
    """

    def __init__(
        self, api_key: Optional[str] = None, client: Optional[Anthropic] = None
    ):
        """Initialize LLM fallback.

        Args:
            api_key: Anthropic API key. If not provided, reads from
                     ANTHROPIC_API_KEY environment variable.
            client: Optional Anthropic client instance for testing.
                    If not provided, creates a new client with api_key.

        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        if client is not None:
            self.client = client
        else:
            api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "No Anthropic API key provided. "
                    "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
                )
            self.client = Anthropic(api_key=api_key)

        self.model = "claude-sonnet-4-20250514"

    def extract(self, question: str) -> Dict[str, Any]:
        """Extract entities from market question using LLM.

        Args:
            question: Market question text to extract entities from.

        Returns:
            Dictionary with extracted entities:
            - game: Video game title or None
            - team_a: First team/player name or None
            - team_b: Second team/player name or None
            - tournament: Tournament name or None
            - market_type: Market type or None

        Raises:
            Exception: If API call fails or response cannot be parsed.

        Note:
            This method is expensive - only call when pattern matcher fails
            to extract critical fields (game, team_a, team_b).
        """
        prompt = EXTRACTION_PROMPT.format(question=question)

        last_exc: Exception = RuntimeError("no attempts made")
        for attempt in range(3):
            if attempt > 0:
                time.sleep(2 ** attempt)  # 2s, 4s
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = response.content[0].text.strip()
                entities = json.loads(response_text)
                return {
                    "game": entities.get("game"),
                    "team_a": entities.get("team_a"),
                    "team_b": entities.get("team_b"),
                    "tournament": entities.get("tournament"),
                    "market_type": entities.get("market_type"),
                }
            except Exception as e:
                last_exc = e

        raise last_exc
