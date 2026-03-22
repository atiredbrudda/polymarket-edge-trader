"""LLM-based entity extraction from Polymarket question text."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import anthropic
from anthropic import APIStatusError

logger = logging.getLogger(__name__)

_EXTRACTION_MODEL = "claude-3-haiku-20240307"

_PROMPT_TEMPLATE = """Extract entities from this prediction market question. Return ONLY a JSON object with these exact keys:
- team_a: first team name (string or null)
- team_b: second team name (string or null)
- tournament: tournament or event name (string or null)
- game: esports game name, e.g. "CS2", "Dota 2", "Valorant" (string or null)
- market_type: "match" for head-to-head, "prop" for winner/stats markets, null if unclear

Question: {question}

JSON only, no explanation:"""


@dataclass
class EntityResult:
    team_a: Optional[str] = None
    team_b: Optional[str] = None
    tournament: Optional[str] = None
    game: Optional[str] = None
    market_type: Optional[str] = None


def extract_entities(
    question: str, client: Optional[anthropic.Anthropic] = None, max_retries: int = 3
) -> EntityResult:
    """Call Claude to extract structured entities from a market question string.

    Retries on transient API errors (rate limits, timeouts) with exponential backoff.
    Does not retry on permanent errors (invalid JSON, model not found).

    Args:
        question: Market question text to extract entities from
        client: Optional pre-configured Anthropic client
        max_retries: Maximum retry attempts for transient errors (default: 3)

    Returns:
        EntityResult with extracted entities, or all-None on failure
    """
    if client is None:
        # Try to get API key from settings first, then environment
        from src.config.settings import get_settings

        settings = get_settings()
        api_key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            logger.warning(
                "Anthropic API key not configured, skipping entity extraction"
            )
            return EntityResult()

        client = anthropic.Anthropic(api_key=api_key)

    last_error = None
    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model=_EXTRACTION_MODEL,
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": _PROMPT_TEMPLATE.format(question=question),
                    }
                ],
            )
            raw = message.content[0].text.strip()
            data = json.loads(raw)
            return EntityResult(
                team_a=data.get("team_a"),
                team_b=data.get("team_b"),
                tournament=data.get("tournament"),
                game=data.get("game"),
                market_type=data.get("market_type"),
            )
        except APIStatusError as e:
            last_error = e
            # Don't retry on 404 (model not found) or 401 (invalid key)
            if e.status_code in (401, 404):
                logger.warning(
                    "Entity extraction failed for question %r: %s", question, e
                )
                return EntityResult()
            # Retry on 429 (rate limit), 5xx (server errors)
            if attempt < max_retries - 1:
                wait_time = (2**attempt) * 1.0  # 1s, 2s, 4s...
                logger.warning(
                    f"Extraction attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                logger.warning(
                    "Entity extraction failed for question %r after %d retries: %s",
                    question,
                    max_retries,
                    e,
                )
        except json.JSONDecodeError as e:
            # Don't retry malformed JSON - it's a permanent error
            logger.warning(
                "Entity extraction failed for question %r: malformed JSON response: %s",
                question,
                e,
            )
            return EntityResult()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (2**attempt) * 1.0
                logger.warning(
                    f"Extraction attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                logger.warning(
                    "Entity extraction failed for question %r after %d retries: %s",
                    question,
                    max_retries,
                    e,
                )

    return EntityResult()
