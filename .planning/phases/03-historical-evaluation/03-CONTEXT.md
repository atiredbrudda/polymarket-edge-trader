# Phase 3: Historical Evaluation - Context

**Gathered:** 2026-02-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Calculate trader performance metrics (PnL, win rate, volume) across multiple timeframes and build a validation framework for tuning expertise scoring weights. Traders are profiled as "selective" or "active" archetypes with different evaluation criteria. Scoring engine and signal detection are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Timeframe windows
- Rolling from current time (not calendar periods or poll-relative)
- Windows: 7d, 30d, 90d, all-time
- Sparse windows (few resolved markets): calculate metrics but flag as low-confidence — downstream scoring weights accordingly

### Trader profiles
- Tag traders as "selective" vs "active" based on unique markets entered (not trade count)
- A trader placing many trades on 2 markets = selective; one trade each on 10 markets = active
- Both profiles can score high through different lenses: accuracy (selective) vs volume-weighted edge (active)

### Consistency detection
- Primary signal: cross-timeframe stability (compare win rate across 30d/90d/all-time — stable = consistent, divergent = streaky)
- Secondary signal: streak length analysis (alternating W/L at 70% > 8 wins then 8 losses)
- Different consistency bars per profile: selective traders need stability across fewer windows than active traders
- No special "declining" flag — Phase 4 recency weighting handles performance drops naturally

### Market difficulty
- Track entry prices and implied probabilities alongside performance metrics
- Do NOT adjust raw win rate or PnL for difficulty — PnL already captures edge naturally
- Data is available for future analysis but metrics stay clean and simple

### Resolution handling
- Voided/cancelled markets: exclude completely from all calculations (never happened)
- Resolved markets: include in PnL/win rate (resolution settles positions automatically, no explicit close needed)
- Unresolved markets: mark-to-market using current token price, tracked with "unrealized" flag, separate from realized metrics
- Resolution grace period: Claude's discretion based on Polymarket dispute mechanics

### Validation framework
- Goal: tune scoring weights (concentration, win rate, recency, sample size) using historical data
- Data split strategy: Claude's discretion
- Framework must be re-runnable — periodic re-tuning (monthly/quarterly) as market evolves and meta shifts
- Validation output format: Claude's discretion

### Claude's Discretion
- Data split methodology for validation (temporal holdout vs k-fold vs hybrid)
- Validation output format and metrics
- Resolution grace period handling
- Exact thresholds for selective vs active profile boundary
- Exact consistency bar differences between profiles
- Sparse window confidence flag threshold

</decisions>

<specifics>
## Specific Ideas

- User raised the "sniper trader" archetype explicitly: someone who picks events carefully and doesn't bet often but has a great hit rate. System must not penalize low frequency if accuracy is high.
- "Unique markets entered" as the profile split metric — breadth of engagement, not raw trade count
- Resolution auto-settles on Polymarket (tokens go to $0 or $1), so "not closing a losing position" isn't an issue — it's handled by the protocol

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-historical-evaluation*
*Context gathered: 2026-02-06*
