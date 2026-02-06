# Phase 2: Classification & Discovery - Context

**Gathered:** 2026-02-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Classify Polymarket markets into a 4-level eSports taxonomy and discover active traders meeting minimum thresholds. Track current open positions with trade-level detail and entry timing. Adding new categories requires only YAML changes, not code modification.

</domain>

<decisions>
## Implementation Decisions

### Taxonomy structure
- 4-level hierarchy: eSports → Game → Tournament tier → Team
- Team-level awareness: system tracks which teams a trader bets on across events (e.g., a trader consistently betting on NaVi across IEM Katowice, ESL Pro League, BLAST = NaVi specialist)
- Teams that compete across multiple games: Claude's discretion on whether to duplicate per game or use a shared registry
- Unknown teams/tournaments: classify at highest matching level, flag unmatched entities for periodic YAML review

### Market matching
- Keyword patterns defined in YAML per taxonomy node (regex/keyword matching against market titles)
- Market type tag: each market classified as "match" (head-to-head, e.g., Team Secret vs MVK) or "prop" (tournament winner, player stats, etc.) — this is a tag attribute, not a taxonomy branch
- Multi-match resolution: best (most specific) match wins — deepest taxonomy node takes priority
- Ambiguous markets that match no taxonomy node get flagged for review alongside unknown teams

### Trader discovery scope
- Minimum thresholds to track: 5+ trades AND $500+ total volume in eSports markets
- Track eSports activity only — non-eSports trades ignored entirely
- Discovery mode: periodic sweep (e.g., daily) plus manual trigger capability
- History backfill strategy: Claude's discretion on immediate vs deferred backfill

### Position tracking
- Trade-level tracking: track each buy/sell individually, compute average entry price, total size, and direction from full history
- Recalculate positions from raw trade data each time (no incremental state — always accurate, no drift)
- Archive resolved positions with outcome (win/loss/void) and PnL — feeds Phase 3 historical evaluation
- Track entry timing: record when positions were opened relative to market creation and resolution (early mover vs late follower signal for Phase 5)

### Claude's Discretion
- Cross-game team handling (duplicate per game vs shared registry)
- History backfill timing (immediate on discovery vs deferred batch job)
- Exact regex patterns for initial taxonomy seeding
- Sweep scheduling defaults (daily cadence, time of day)

</decisions>

<specifics>
## Specific Ideas

- "Some people know some teams well and how they perform" — the team-level tracking is specifically about detecting traders who follow specific rosters/organizations across tournaments, not just games
- Match markets (Team A vs Team B) should be distinguished from prop markets (tournament winner, player stats) — different market types signal different trading behavior
- The system should recognize patterns like "this trader always bets on NaVi regardless of tournament" as a specialization signal

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-classification-discovery*
*Context gathered: 2026-02-06*
