# Phase 5: Signal Detection - Context

**Gathered:** 2026-02-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Detect when multiple expert traders (score >70) independently converge on the same market position. Calculate consensus confidence scores. Surface markets ranked by expert activity across time windows (1h/6h/24h). Identify first movers vs followers. Herding detection is explicitly deferred — all expert positions count equally regardless of timing.

</domain>

<decisions>
## Implementation Decisions

### Consensus definition
- Minimum 3 experts required to trigger a consensus signal
- Expert threshold: score >70 (from roadmap)
- All qualifying experts weighted equally (no score-weighting within consensus)
- Supermajority rule: 75%+ of experts on same direction triggers signal (not unanimous)
- Confidence score (0-100) incorporates: number of experts agreeing, agreement percentage, and position sizes

### Herding vs independence
- No herding detection in this phase — explicitly deferred
- User rationale: if copy-traders follow a smart trader who's right, the signal is still valid
- All expert positions count toward consensus regardless of timing proximity

### Signal freshness & windows
- Signals persist until market resolution (no expiration)
- 1h/6h/24h windows are filter views only — not used for ranking
- Ranking is by confidence score only
- Auto-update: consensus recalculates whenever any expert's position changes (flip, exit, enter)
- Track strength changes: record confidence score deltas when experts join/leave/flip for Phase 6 alerting

### First-mover identification
- First mover defined as: first expert to take a position in a specific direction (YES or NO)
- First-mover status is metadata only — no effect on consensus confidence score
- Track first-mover frequency per trader over time (aggregate stat for Phase 7 trader profiles)

### Claude's Discretion
- Fast-follower time window definition (how long after first mover counts as "following")
- Confidence score formula specifics (how to weight count vs agreement % vs position size)
- Signal state machine implementation (how auto-updates and strength tracking work internally)

</decisions>

<specifics>
## Specific Ideas

- User wants signals to auto-update rather than create new signals — living signals that evolve
- Position sizes matter for confidence — experts putting more money in should boost signal confidence
- First-mover tracking across signals could become a "conviction" metric for trader profiles

</specifics>

<deferred>
## Deferred Ideas

- Herding/copy-trading detection — user may revisit if data shows a problem with signal quality
- Timing cluster analysis — originally in roadmap but user prefers to skip unless needed
- First-mover confidence boost — could revisit if first-mover data shows predictive value

</deferred>

---

*Phase: 05-signal-detection*
*Context gathered: 2026-02-07*
