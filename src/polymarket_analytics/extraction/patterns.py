"""Entity pattern matcher for regex-based extraction from market questions.

This module provides pre-compiled regex patterns for extracting eSports entities
(game, teams, tournament) from Polymarket market questions.

Expected coverage: ~65% of eSports markets without LLM fallback.
"""

import re
from typing import Dict, List, Optional


# Pre-defined pattern dictionaries for entity extraction
GAME_PATTERNS: Dict[str, List[str]] = {
    "CS2": [
        r"\bCS2\b",
        r"\bCounter-Strike 2\b",
        r"\bCS:GO\b",
        r"\bCounter-Strike: Global Offensive\b",
    ],
    "LoL": [r"\bLoL\b", r"\bLeague of Legends\b"],
    "Dota 2": [r"\bDota 2\b"],
    "Valorant": [r"\bValorant\b"],
    "Rocket League": [r"\bRocket League\b"],
    "NBA 2K": [r"\bNBA 2K\b"],
    "Madden NFL": [r"\bMadden NFL\b"],
    "Tennis": [
        r"\bTennis\b",
        r"\bWimbledon\b",
        r"\bUS Open\b",
        r"\bFrench Open\b",
        r"\bAustralian Open\b",
    ],
    "Boxing": [r"\bBoxing\b"],
    "MMA": [r"\bMMA\b", r"\bUFC\b"],
    "Politics": [r"\bPolitics\b", r"\bElection\b", r"\bSenate\b", r"\bGovernor\b"],
    "Crypto": [r"\bCrypto\b", r"\bBitcoin\b", r"\bEthereum\b", r"\bBTC\b", r"\bETH\b"],
}

TEAM_PATTERNS: Dict[str, List[str]] = {
    # CS2 Teams
    "FaZe": [r"\bFaZe\b", r"\bFaZe Clan\b"],
    "NAVI": [r"\bNAVI\b", r"\bNatus Vincere\b", r"\bNa'Vi\b"],
    "G2": [r"\bG2\b", r"\bG2 Esports\b"],
    "Vitality": [r"\bVitality\b", r"\bTeam Vitality\b"],
    "Astralis": [r"\bAstralis\b"],
    "Liquid": [r"\bLiquid\b", r"\bTeam Liquid\b"],
    "Cloud9": [r"\bCloud9\b", r"\bC9\b"],
    "Fnatic": [r"\bFnatic\b", r"\bFNC\b"],
    "MOUZ": [r"\bMOUZ\b", r"\bmousesports\b"],
    "Spirit": [r"\bSpirit\b", r"\bTeam Spirit\b"],
    # LoL Teams
    "T1": [r"\bT1\b", r"\bSKT T1\b", r"\bSK Telecom T1\b"],
    "Gen.G": [r"\bGen\.G\b", r"\bGenG\b"],
    "JDG": [r"\bJDG\b", r"\bJD Gaming\b"],
    "BLG": [r"\bBLG\b", r"\bBilibili Gaming\b"],
    "WBG": [r"\bWBG\b", r"\bWeibo Gaming\b"],
    "G2 LoL": [r"\bG2\b", r"\bG2 Esports\b"],
    "FNC LoL": [r"\bFnatic\b", r"\bFNC\b"],
    "C9 LoL": [r"\bCloud9\b", r"\bC9\b"],
    "TL LoL": [r"\bTeam Liquid\b", r"\bTL\b"],
    # Dota 2 Teams
    "Team Spirit Dota": [r"\bTeam Spirit\b", r"\bSpirit\b"],
    "Gaimin Gladiators": [r"\bGaimin Gladiators\b", r"\bGG\b"],
    "Shopify Rebellion": [r"\bShopify Rebellion\b", r"\bSR\b"],
    "BetBoom": [r"\bBetBoom\b", r"\bBB\b"],
    # Valorant Teams
    "Sentinels": [r"\bSentinels\b", r"\bSEN\b"],
    "NRG": [r"\bNRG\b"],
    "Cloud9 Val": [r"\bCloud9\b", r"\bC9\b"],
    "LOUD": [r"\bLOUD\b"],
    "Paper Rex": [r"\bPaper Rex\b", r"\bPRX\b"],
    "DRX": [r"\bDRX\b"],
}

TOURNAMENT_PATTERNS: Dict[str, List[str]] = {
    # CS2 Tournaments
    "IEM": [r"\bIEM\b", r"\bIntel Extreme Masters\b"],
    "Major": [r"\bMajor\b", r"\bCS2 Major\b", r"\bCS:GO Major\b"],
    "BLAST": [r"\bBLAST\b", r"\bBLAST Premier\b"],
    "ESL Pro League": [r"\bESL Pro League\b", r"\bEPL\b"],
    "PGL": [r"\bPGL\b"],
    "IEM Katowice": [r"\bIEM Katowice\b"],
    "IEM Cologne": [r"\bIEM Cologne\b"],
    # LoL Tournaments
    "Worlds": [
        r"\bWorlds\b",
        r"\bWorld Championship\b",
        r"\bLeague of Legends World Championship\b",
    ],
    "MSI": [r"\bMSI\b", r"\bMid-Season Invitational\b"],
    "LCS": [r"\bLCS\b", r"\bLeague Championship Series\b"],
    "LEC": [r"\bLEC\b", r"\bLeague of Legends European Championship\b"],
    "LCK": [r"\bLCK\b", r"\bLeague of Legends Champions Korea\b"],
    "LPL": [r"\bLPL\b", r"\bLeague of Legends Pro League\b"],
    # Dota 2 Tournaments
    "The International": [r"\bThe International\b", r"\bTI\b", r"\bTI\d*\b"],
    "DPC": [r"\bDPC\b", r"\bDota Pro Circuit\b"],
    "DreamLeague": [r"\bDreamLeague\b"],
    "ESL One Dota": [r"\bESL One\b"],
    # Valorant Tournaments
    "VCT": [r"\bVCT\b", r"\bValorant Champions Tour\b"],
    "Valorant Champions": [r"\bChampions\b", r"\bValorant Champions\b"],
    "Masters": [r"\bMasters\b", r"\bVCT Masters\b"],
    "Game Changers": [r"\bGame Changers\b"],
    # General eSports
    "Grand Final": [r"\bGrand Final\b", r"\bGrand Finals\b"],
    "Playoffs": [r"\bPlayoffs\b", r"\bPlay-off\b"],
    "Semifinal": [r"\bSemifinal\b", r"\bSemi-final\b"],
    "Quarterfinal": [r"\bQuarterfinal\b", r"\bQuarter-final\b"],
}

# Market type keywords
MARKET_TYPE_PATTERNS = {
    "winner": [r"\bwinner\b", r"\bwin\b", r"\bwins\b"],
    "total_maps": [r"\btotal maps\b", r"\bmap total\b", r"\bover/\s*under\b"],
    "handicap": [r"\bhandicap\b", r"\bspread\b"],
    "first_blood": [r"\bfirst blood\b"],
    "first_map": [r"\bfirst map\b"],
    "correct_score": [r"\bcorrect score\b", r"\bexact score\b"],
    "outright": [r"\boutright\b", r"\btournament winner\b", r"\bchampion\b"],
}


class EntityPatternMatcher:
    """Regex-based entity extractor for market questions.

    Extracts game, teams, tournament, and market type from Polymarket
    market questions using pre-compiled regex patterns.

    Expected coverage: ~65% of eSports markets without LLM fallback.

    Attributes:
        game_regex: Dict mapping game names to compiled regex patterns
        team_regex: Dict mapping team names to compiled regex patterns
        tournament_regex: Dict mapping tournament names to compiled regex patterns
        market_type_regex: Dict mapping market types to compiled regex patterns
    """

    def __init__(self):
        """Initialize EntityPatternMatcher and compile all regex patterns."""
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile all regex patterns for performance."""
        # Compile game patterns
        self.game_regex = {
            game: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for game, patterns in GAME_PATTERNS.items()
        }

        # Compile team patterns
        self.team_regex = {
            team: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for team, patterns in TEAM_PATTERNS.items()
        }

        # Compile tournament patterns
        self.tournament_regex = {
            tournament: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for tournament, patterns in TOURNAMENT_PATTERNS.items()
        }

        # Compile market type patterns
        self.market_type_regex = {
            market_type: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for market_type, patterns in MARKET_TYPE_PATTERNS.items()
        }

        # Compile team extraction patterns (A vs B or A beat/defeat B format)
        # Pattern 1: "A vs B" format
        self.vs_pattern = re.compile(
            r"([A-Z][A-Za-z0-9\s]{0,25}?)\s+(?:vs\.?|-)\s+([A-Z][A-Za-z0-9\s]{0,25}?)(?:\s+(?:in|at|for|-)|$|\?)",
            re.IGNORECASE,
        )
        # Pattern 2: "Will A beat/defeat B" format (also handles "A against B")
        self.beat_pattern = re.compile(
            r"(?:Will|Who will)?\s*([A-Z][A-Za-z0-9\s]{0,25}?)\s+(?:beat|defeats?|plays?\s+(?:against|vs\.?)|against)\s+([A-Z][A-Za-z0-9\s]{0,25}?)(?:\s+(?:in|at|for)|$|\?)",
            re.IGNORECASE,
        )

    def extract(self, question: str) -> Dict[str, Optional[str]]:
        """Extract entities from a market question.

        Args:
            question: Market question text (e.g., "Will T1 beat G2 in LoL Worlds 2025?")

        Returns:
            Dict with keys: game, team_a, team_b, tournament, market_type
            All values are nullable (None if not extracted)
        """
        result: Dict[str, Optional[str]] = {
            "game": None,
            "team_a": None,
            "team_b": None,
            "tournament": None,
            "market_type": None,
        }

        # Extract game
        for game, patterns in self.game_regex.items():
            if any(pattern.search(question) for pattern in patterns):
                result["game"] = game
                break

        # Extract teams from "A vs B" or "A beat B" pattern
        vs_match = self.vs_pattern.search(question)
        if vs_match:
            result["team_a"] = self._normalize_team(vs_match.group(1).strip())
            result["team_b"] = self._normalize_team(vs_match.group(2).strip())
        else:
            # Try beat/defeat pattern
            beat_match = self.beat_pattern.search(question)
            if beat_match:
                result["team_a"] = self._normalize_team(beat_match.group(1).strip())
                result["team_b"] = self._normalize_team(beat_match.group(2).strip())

        # Extract tournament
        for tournament, patterns in self.tournament_regex.items():
            if any(pattern.search(question) for pattern in patterns):
                result["tournament"] = tournament
                break

        # Extract market type
        for market_type, patterns in self.market_type_regex.items():
            if any(pattern.search(question) for pattern in patterns):
                result["market_type"] = market_type
                break

        return result

    def _normalize_team(self, name: str) -> str:
        """Normalize team name by removing common prefixes/suffixes.

        Args:
            name: Raw team name extracted from question

        Returns:
            Normalized team name
        """
        # Remove common prefixes
        prefixes_to_remove = [
            "Team ",
            "The ",
        ]

        # Remove common suffixes
        suffixes_to_remove = [
            " Esports",
            " Gaming",
            " Club",
        ]

        normalized = name

        for prefix in prefixes_to_remove:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]

        for suffix in suffixes_to_remove:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]

        return normalized.strip()
