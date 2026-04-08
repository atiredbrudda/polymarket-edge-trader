---
phase: 02-data-ingestion
plan: 02
subsystem: data-ingestion
tags: [regex, entity-extraction, esports, pattern-matching]

# Dependency graph
requires:
  - phase: 02-data-ingestion
    provides: Gamma API client, markets table, CLI infrastructure
provides:
  - classify-tokens CLI command for building token_catalog from Gamma API
  - EntityPatternMatcher class for regex-based entity extraction
  - Pre-compiled regex patterns for games, teams, tournaments
affects:
  - 02-data-ingestion (future plans: LLM fallback integration)
  - 03-feature-engineering (entity-based features)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Pre-compiled regex patterns for performance
    - Dual-pattern team extraction (A vs B, A beats B)
    - Modular entity extraction with fallback architecture

key-files:
  created:
    - src/polymarket_analytics/commands/classify_tokens.py
    - src/polymarket_analytics/extraction/patterns.py
    - src/polymarket_analytics/extraction/__init__.py (updated)
  modified:
    - src/polymarket_analytics/commands/__init__.py

key-decisions:
  - "Used pre-compiled regex patterns (re.compile) for performance over string patterns"
  - "Implemented dual-pattern team extraction: vs_pattern for 'A vs B' and beat_pattern for 'A beats B'"
  - "Pattern matcher returns None for unmatched fields (LLM fallback handles remaining ~35%)"

patterns-established:
  - "EntityPatternMatcher.extract(question) returns dict with game, team_a, team_b, tournament, market_type keys (all nullable)"
  - "Patterns are extensible dictionaries (GAME_PATTERNS, TEAM_PATTERNS, TOURNAMENT_PATTERNS)"

# Metrics
duration: 7 min
completed: 2026-03-29
---

# Phase 02: Data Ingestion Plan 02: Token Classification and Pattern Extraction

**classify-tokens CLI command and EntityPatternMatcher with ~65% eSports entity coverage using pre-compiled regex patterns**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-29T12:59:46Z
- **Completed:** 2026-03-29T13:07:13Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- classify-tokens CLI command fetches markets from Gamma API, populates token_catalog with condition_id mappings
- EntityPatternMatcher class with pre-compiled regex patterns for games, teams, tournaments
- Pattern matcher extracts entities from market questions with ~65% expected coverage
- Dual-pattern team extraction handles both "A vs B" and "A beats B" question formats

## Task Commits

Each task was committed atomically:

1. **Task 1: Create classify-tokens CLI command** - `ae9ba71` (feat)
2. **Task 2: Create EntityPatternMatcher for entity extraction** - `daaf469` (feat)

## Files Created/Modified

- `src/polymarket_analytics/commands/classify_tokens.py` - classify-tokens CLI command (101 lines)
  - Fetches markets from Gamma API using GammaAPIClient
  - Populates token_catalog with condition_id, question, niche_slug, node_path, market_type
  - Asserts markets table exists before running (fails with clear error if missing)
  - Asserts data fetched (fails if no markets found)

- `src/polymarket_analytics/extraction/patterns.py` - EntityPatternMatcher class (264 lines)
  - GAME_PATTERNS: CS2, LoL, Dota 2, Valorant, Rocket League, Tennis, Boxing, MMA, Politics, Crypto
  - TEAM_PATTERNS: 40+ teams including FaZe, NAVI, G2, T1, Gen.G, Sentinels, LOUD
  - TOURNAMENT_PATTERNS: IEM, Major, BLAST, Worlds, MSI, LCS, LEC, LCK, The International, VCT
  - MARKET_TYPE_PATTERNS: winner, total_maps, handicap, first_blood, correct_score, outright
  - extract() method returns dict with game, team_a, team_b, tournament, market_type keys

- `src/polymarket_analytics/extraction/__init__.py` - Module exports (18 lines)
  - Exports EntityPatternMatcher, GAME_PATTERNS, TEAM_PATTERNS, TOURNAMENT_PATTERNS

- `src/polymarket_analytics/commands/__init__.py` - Command registration (updated)
  - Added classify_tokens import and export

## Decisions Made

- **Pre-compiled regex patterns**: Used `re.compile()` with `re.IGNORECASE` flag for performance - patterns compiled once at initialization, not on each extract() call
- **Dual-pattern team extraction**: Separate patterns for "A vs B" format and "A beats/defeats B" format - covers common market question structures
- **Nullable return values**: All entity fields (game, team_a, team_b, tournament, market_type) return None if not extracted - enables LLM fallback for remaining ~35%

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed team extraction pattern not matching common formats**
- **Found during:** Task 2 (EntityPatternMatcher testing)
- **Issue:** Original pattern only matched "A vs B" format, but market questions use "Will T1 beat G2?" and "Will FaZe defeat NAVI?" formats
- **Fix:** Added beat_pattern regex to handle "beat/defeat/play against" formats in addition to vs_pattern
- **Files modified:** src/polymarket_analytics/extraction/patterns.py
- **Verification:** Test extraction now correctly extracts T1/G2 from "Will T1 beat G2 in LoL Worlds 2025?"
- **Committed in:** daaf469 (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Bug fix necessary for correct entity extraction. No scope creep.

## Issues Encountered

None - plan executed successfully with minor bug fix during implementation.

## Pattern Matcher Test Results

Sample extractions demonstrating coverage:

```
Input: Will T1 beat G2 in LoL Worlds 2025?
game=LoL, team_a=T1, team_b=G2, tournament=Worlds

Input: Will FaZe Clan defeat NAVI at IEM Katowice?
game=None, team_a=FaZe Clan, team_b=NAVI, tournament=IEM

Input: T1 vs G2 - LoL Worlds 2025
game=LoL, team_a=T1, team_b=G2, tournament=Worlds

Input: Will Vitality play against Astralis in BLAST Premier?
game=None, team_a=Vitality, team_b=Astralis, tournament=BLAST

Input: Will Bitcoin hit 100k by end of year?
game=Crypto, team_a=None, team_b=None, tournament=None
```

## Pattern Gaps Identified (LLM Fallback Candidates)

Markets that will require LLM fallback (~35%):

1. **Non-eSports games**: Markets for games not in GAME_PATTERNS (e.g., "StarCraft 2", "Hearthstone")
2. **Unknown teams**: New/emerging teams not in TEAM_PATTERNS
3. **Novel tournaments**: New tournament formats not matching existing patterns
4. **Ambiguous phrasing**: Questions without clear "vs" or "beat" structure
5. **Player-vs-player**: Individual player names not in team patterns

## Next Phase Readiness

- Pattern matcher ready for integration with discover command (next plan)
- LLM fallback can be layered on top: pattern matcher first, LLM for None results
- token_catalog structure supports condition_id → entity mapping
- Architecture supports extensible pattern addition (add to GAME_PATTERNS/TEAM_PATTERNS dicts)

---
*Phase: 02-data-ingestion*
*Completed: 2026-03-29*

## Self-Check: PASSED
