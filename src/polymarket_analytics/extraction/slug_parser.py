"""Parse event_slug into game/team entities.

Shared by discover and backfill commands to extract game information
from structured event slugs like 'cs2-fnc-faze-2026-03-31'.
"""

import re
from typing import Dict, Optional

# Map event_slug game prefix → canonical game name (must match market_entities.game values)
SLUG_GAME_MAP: Dict[str, str] = {
    "cs2": "CS2",
    "cs": "CS2",
    "csgo": "CS2",
    "dota2": "Dota 2",
    "dota": "Dota 2",
    "lol": "LoL",
    "league": "LoL",
    "val": "Valorant",
    "valorant": "Valorant",
    "hok": "Honor of Kings",
    "r6siege": "Rainbow Six Siege",
    "r6": "Rainbow Six Siege",
    "codmw": "Call of Duty",
    "cod": "Call of Duty",
    "mlbb": "Mobile Legends",
    "rl": "Rocket League",
    "ow": "Overwatch",
    "sc2": "StarCraft 2",
}

# Map tournament slug prefixes → game (for organizer-branded slugs with no game prefix).
TOURNAMENT_PREFIX_MAP: list = [
    ("blast-bounty", "CS2"),
    ("blast-open", "CS2"),
    ("blast-rivals", "CS2"),
    ("blast-slam", "CS2"),
    ("blastopen", "CS2"),
    ("counter-strike-2", "CS2"),
    ("dreamhack-major", "CS2"),
    ("esl-counter-strike", "CS2"),
    ("esl-pro-league", "CS2"),
    ("esl-one-birmingham", "Dota 2"),
    ("fissure", "CS2"),
    ("iem", "CS2"),
    ("pgl-astana", "CS2"),
    ("pgl-bucharest", "CS2"),
    ("pgl-wallachia", "Dota 2"),
    ("thunderpick-wc", "CS2"),
    ("vct", "Valorant"),
    ("optic-texas-major", "Call of Duty"),
    ("betboom-rush-b", "CS2"),
    ("first-stand", "LoL"),
    ("msi-playoffs", "LoL"),
    ("geng-global-academy", "LoL"),
]

_SLUG_DATE_RE = re.compile(r"^(.+)-(\d{4})-(\d{2})-(\d{2})$")


def parse_event_slug(slug: str) -> Dict[str, Optional[str]]:
    """Parse event_slug into entities.

    Handles two formats:
    - Match slug: 'game-team_a-team_b-YYYY-MM-DD' → game + teams
    - Prefix-only: 'game-anything' (no date) → game only, when prefix is a known game
    """
    if not slug:
        return {}
    # Try match slug format first (with date)
    m = _SLUG_DATE_RE.match(slug)
    if m:
        body = m.group(1)  # everything before the date
        parts = body.split("-")
        if len(parts) >= 3:
            game_prefix = parts[0]
            game = SLUG_GAME_MAP.get(game_prefix)
            if game:
                team_a = parts[1]
                team_b = "-".join(parts[2:]) if len(parts) > 2 else None
                return {"game": game, "team_a": team_a, "team_b": team_b}
    # Try prefix-only format (e.g. 'cs2-fissure-playground-1-winner')
    prefix = slug.split("-")[0]
    game = SLUG_GAME_MAP.get(prefix)
    if game:
        return {"game": game}
    # Try tournament prefix map (e.g. 'blast-bounty-fnatic-vs-legacy' → CS2)
    for tournament_prefix, tournament_game in TOURNAMENT_PREFIX_MAP:
        if slug.startswith(tournament_prefix):
            return {"game": tournament_game}
    return {}
