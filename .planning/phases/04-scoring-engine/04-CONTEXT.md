# Phase 4: Scoring Engine - Context

**Gathered:** 2026-02-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Calculate specialization depth scores (0-100) per trader per eSports category. Scores incorporate concentration, win rate, sample size, and recency. Enforce minimum sample sizes, apply recency weighting, and produce ranked leaderboards per niche. Distinguish game-level specialists from generalists. This phase is data/computation only — CLI display is Phase 7.

</domain>

<decisions>
## Implementation Decisions

### Score Formula Weights
- Win rate dominant weighting (~40%), remaining split across concentration, recency, sample size
- Moderate recency decay (half-life ~3 months) — balances rewarding history with penalizing inactivity
- Consistency score from Phase 3 factors INTO the expertise score as a multiplier/bonus — consistent traders get boosted, streaky ones penalized
- Initial weight values: Claude's discretion (hardcoded defaults or auto-tuned via validation framework, whichever makes more sense for v1)

### Specialist vs Generalist
- Specialization threshold: Claude's discretion based on what the data supports
- Generalists receive a different label only — scores are fair per game, not penalized
- Per-game independent scoring — a trader CAN be specialist in multiple games simultaneously (e.g., CS:GO and Valorant)
- Two-tier specialization tracking: both eSports-level (how focused within eSports overall) AND game-level (how focused within a specific game)

### Leaderboard Design
- Both views: default top-N per game AND filterable by minimum score threshold
- Recency decay naturally handles inactive traders — no separate removal mechanism needed
- Each entry includes: score + rank, win rate + PnL, activity level (trade count, unique markets, last active), specialization label
- Data/computation only at this phase — CLI rendering is Phase 7's responsibility

### Score Interpretation
- Raw numbers only (0-100) — no named tiers (Expert/Proficient/etc.)
- Scores are relative/percentile-based — normalized against the population, not absolute formula output
- New traders with exactly 5 resolved markets (minimum) scored normally — sample size component naturally gives appropriate weight
- Score history tracked over time — store snapshots to enable trend analysis and "rising star" detection downstream

</decisions>

<specifics>
## Specific Ideas

- The niche hypothesis is core: traders deeply focused in one game likely have domain knowledge generalists don't. The scoring should reward and surface this.
- Scores shift as population changes (percentile-based), which means leaderboards stay meaningful even as new traders join.
- Score history enables Phase 5 to detect momentum/trajectory, not just current state.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-scoring-engine*
*Context gathered: 2026-02-06*
