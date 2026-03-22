"""Pattern-based entity extraction from market question text.

Uses known games, teams, and tournaments from existing market_entities
to extract entities without LLM calls. Falls back to None fields when
patterns don't match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.extraction.llm_extractor import EntityResult


# Game keywords → canonical game name
# Order matters: longer patterns first to avoid partial matches
_GAME_PATTERNS: list[tuple[str, str]] = [
    (r"\bCounter-Strike\b", "Counter-Strike"),
    (r"\bCS2\b", "CS2"),
    (r"\bCS:GO\b", "CS:GO"),
    (r"\bCS:", "CS"),
    (r"\bLeague of Legends\b", "League of Legends"),
    (r"\bLoL\b", "LoL"),
    (r"\bDota\s*2\b", "Dota 2"),
    (r"\bValorant\b", "Valorant"),
    (r"\bCall of Duty\b", "Call of Duty"),
    (r"\bRocket League\b", "Rocket League"),
    (r"\bFortnite\b", "Fortnite"),
    (r"\bRainbow Six Siege\b", "Rainbow Six Siege"),
    (r"\bMobile Legends\b", "Mobile Legends Bang Bang"),
    (r"\bStarCraft II\b", "StarCraft II"),
    (r"\bHonor of Kings\b", "Honor of Kings"),
    (r"\bOverwatch\b", "Overwatch"),
]

# Known tournament prefixes that imply a game
_TOURNAMENT_GAME_MAP: dict[str, str] = {
    "IEM": "CS2",
    "BLAST": "CS2",
    "ESL": "CS2",
    "ESEA": "Counter-Strike",
    "CCT": "Counter-Strike",
    "PGL": "CS2",
    "MSI": "League of Legends",
    "LEC": "League of Legends",
    "LCS": "League of Legends",
    "LCK": "League of Legends",
    "LPL": "League of Legends",
    "VCT": "Valorant",
    "VCL": "Valorant",
    "DreamLeague": "Dota 2",
    "EPL": "Dota 2",
}

# Regex for "Team A vs Team B" with optional suffixes
_VS_PATTERN = re.compile(
    r"^(?:(.+?):\s+)?(.+?)\s+vs\.?\s+(.+?)(?:\s*[-–]\s*.+?(?:Winner|Map|Game))?(?:\s*\(BO\d\))?\s*$",
    re.IGNORECASE,
)

# Prop bet patterns (no team extraction needed)
_PROP_PATTERNS = [
    re.compile(r"Total Rounds Over/Under", re.IGNORECASE),
    re.compile(r"Games Total:\s*O/U", re.IGNORECASE),
    re.compile(r"(?:Map|Game|Series)\s+Handicap", re.IGNORECASE),
    re.compile(r"Kill Handicap", re.IGNORECASE),
    re.compile(r"Tower Handicap", re.IGNORECASE),
    re.compile(r"Rounds Handicap", re.IGNORECASE),
    re.compile(r"Drake Handicap", re.IGNORECASE),
    re.compile(r"to win \d+ (?:maps?|games?)\??", re.IGNORECASE),
    re.compile(r"to win a map\??", re.IGNORECASE),
    re.compile(r"Will .+ qualify ", re.IGNORECASE),
    re.compile(r"Will .+ advance ", re.IGNORECASE),
    re.compile(r"Will .+ win ", re.IGNORECASE),
    re.compile(r"Will the price of", re.IGNORECASE),
    re.compile(r"Series:\s*Most \w+\??", re.IGNORECASE),
    re.compile(r"Inhibitor Handicap", re.IGNORECASE),
]


@dataclass
class PatternMatcherStats:
    """Tracks pattern matcher hit/miss rates."""

    matched: int = 0
    unmatched: int = 0
    prop_bets: int = 0


class PatternMatcher:
    """Extracts entities from market questions using known patterns.

    Built from existing market_entities data. For questions that follow
    known formats (Game: Team A vs Team B), extracts without LLM.
    """

    def __init__(self):
        self._team_set: set[str] = set()
        self._tournament_game: dict[str, str] = dict(_TOURNAMENT_GAME_MAP)
        self._compiled_games = [(re.compile(p, re.IGNORECASE), name) for p, name in _GAME_PATTERNS]
        self.stats = PatternMatcherStats()

    def load_from_db(self, session) -> int:
        """Load known teams and tournament→game mappings from market_entities.

        Returns:
            Number of reference rows loaded.
        """
        from sqlalchemy import select
        from src.db.models import MarketEntity

        rows = session.execute(
            select(
                MarketEntity.team_a,
                MarketEntity.team_b,
                MarketEntity.tournament,
                MarketEntity.game,
            ).where(MarketEntity.game.isnot(None))
        ).all()

        for team_a, team_b, tournament, game in rows:
            if team_a:
                self._team_set.add(team_a)
            if team_b:
                self._team_set.add(team_b)
            if tournament and game:
                self._tournament_game[tournament] = game

        return len(rows)

    def match(self, question: str) -> Optional[EntityResult]:
        """Try to extract entities from question using patterns.

        Returns:
            EntityResult if matched, None if LLM fallback needed.
        """
        # Check prop bets first
        for pat in _PROP_PATTERNS:
            if pat.search(question):
                result = self._extract_prop(question)
                if result:
                    self.stats.prop_bets += 1
                    self.stats.matched += 1
                    return result

        # Try "Game/Tournament: Team A vs Team B" format
        vs_match = _VS_PATTERN.match(question)
        if vs_match:
            prefix = vs_match.group(1)  # game or tournament name
            team_a = vs_match.group(2).strip()
            team_b = vs_match.group(3).strip()

            game = self._resolve_game(prefix, question)
            tournament = None

            if prefix and game and prefix.strip() != game:
                tournament = prefix.strip()

            if game:
                self.stats.matched += 1
                return EntityResult(
                    team_a=team_a,
                    team_b=team_b,
                    tournament=tournament,
                    game=game,
                    market_type="match",
                )

        # No match
        self.stats.unmatched += 1
        return None

    def _resolve_game(self, prefix: Optional[str], question: str) -> Optional[str]:
        """Resolve game name from prefix and/or question text."""
        # Check direct game patterns in question
        for compiled, name in self._compiled_games:
            if compiled.search(question):
                return name

        # Check if prefix matches a known tournament
        if prefix:
            prefix_stripped = prefix.strip()
            # Exact match
            if prefix_stripped in self._tournament_game:
                return self._tournament_game[prefix_stripped]
            # Prefix match (e.g., "IEM Cologne" starts with "IEM")
            for tourn_prefix, game in self._tournament_game.items():
                if prefix_stripped.startswith(tourn_prefix):
                    return game

        return None

    def _extract_prop(self, question: str) -> Optional[EntityResult]:
        """Extract what we can from prop bet questions."""
        game = None
        for compiled, name in self._compiled_games:
            if compiled.search(question):
                game = name
                break

        # Try to find game from team/tournament context
        if not game:
            for tourn_prefix, g in self._tournament_game.items():
                if tourn_prefix in question:
                    game = g
                    break

        # Prop bets: we know the type but may not have teams
        return EntityResult(
            team_a=None,
            team_b=None,
            tournament=None,
            game=game,
            market_type="prop",
        )
