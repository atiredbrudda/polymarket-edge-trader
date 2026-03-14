"""LLM-based entity extraction from Polymarket question text."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

_EXTRACTION_MODEL = "claude-haiku-3-5-20241022"

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
    question: str, client: Optional[anthropic.Anthropic] = None
) -> EntityResult:
    """Call Claude to extract structured entities from a market question string."""
    if client is None:
        client = anthropic.Anthropic()
    try:
        message = client.messages.create(
            model=_EXTRACTION_MODEL,
            max_tokens=256,
            messages=[
                {"role": "user", "content": _PROMPT_TEMPLATE.format(question=question)}
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
    except Exception as e:
        logger.warning("Entity extraction failed for question %r: %s", question, e)
        return EntityResult()
