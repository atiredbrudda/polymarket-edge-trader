# Phase 25: Lift-Based Scoring v2 - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning
**Source:** PRD Express Path (Backtest/ANALYZE_BRIEFING.md)

<domain>
## Phase Boundary

Replace the entire scoring engine (currently WR/concentration/recency/sample_size weighted composite) with a backtest-validated lift-based formula: **z(CLV) + z(ROI) + z(Sharpe)** with equal weights. Rewrite the `analyze` command to be the primary scoring + Q5 identification + signal surface. Functions are category-agnostic — built for eSports data today, work on EPL/politics when data arrives.

</domain>

<decisions>
## Implementation Decisions

### Scoring Formula
- Composite score = z(CLV) + z(ROI) + z(Sharpe), equal weights, no tuning
- CLV (Closing Line Value): LONG = market_avg_entry - trader_avg_entry; SHORT = trader_avg_entry - market_avg_entry. Positive = better price than crowd.
- ROI: total_pnl / total_capital_deployed
- Sharpe: avg_pnl_per_position / stddev_pnl_per_position
- Z-score normalize each metric across the trader population, then sum
- Top 20% = Q5 traders. Quintile assignment (Q1-Q5).

### What Is Explicitly Excluded From Formula
- Win rate: predicts nothing. 70% WR traders lose money. 50% WR traders can be most profitable. WR does NOT belong in the formula.
- Weight tuning: 348 experiments across 5 markets, "optimal" weights beat equal weights by <0.002. Don't tune.
- Extra features (volume, consistency, n_markets, wr_lift): all degrade performance. Tested all 84 possible 3-feature combos — CLV+ROI+Sharpe ranked #1.
- Specialist/niche detection: good traders are generalists within a category, skill transfers across sub-markets.

### Rolling Window
- 30-day training window. Recency > quantity. Score traders on last ~30 days of activity.

### Per-Market Configuration
- esports: min_positions=30, actionable=true
- epl: min_positions=10, actionable=true
- politics: min_positions=30, actionable=true
- la-liga: min_positions=20, actionable=false (weak signal)
- ligue-1: min_positions=10, actionable=false (weak signal)
- nba: not scorable (signal=0.12, useless)

### Old Scoring System
- The old scoring.py formula (40% WR, 25% concentration, 20% recency, 15% sample_size) is REPLACED, not kept alongside.
- ExpertiseScore table replaced by LiftScore table. No dual system.
- `score` command and `leaderboard` command rewired to new engine.

### Category-Agnostic Design
- All functions take a category parameter
- Only eSports has position data today — that's fine
- When EPL/politics data gets ingested later, same functions just work, no code changes needed

### Real-Time Signal Surface (analyze --signals)
- When Q5 trader enters a position, evaluate: market category, entry price vs current market price, how many other Q5 on same side
- 0-2 Q5 same side → small position signal (1% bankroll)
- 3+ Q5 same side → standard position signal (2-3% bankroll)
- If market price already moved past Q5 entry → edge gone, skip
- This is a SIZING signal, not a directional confidence signal

### Slippage Tracking
- Log every entry with: your_entry_price, q5_entry_price, market_avg_price, slippage = (your_entry - q5_entry)
- Edge remains positive up to 5c slippage across all markets
- If average slippage consistently >5c, strategy is degrading

### Core Insight
- Q5 traders' edge is PRICE, not DIRECTION
- They win ~50% of the time, same as everyone
- They make money by consistently entering at better prices than the crowd
- Consensus identifies MISPRICED markets, not winning sides

### Claude's Discretion
- Module file organization (lift_metrics.py, lift_scoring.py, lift_queries.py naming)
- DB migration strategy (new table vs alter existing)
- Index design for LiftScore table
- CLI output formatting for analyze command
- How to compute market_avg_entry efficiently (single SQL aggregate per scoring run)
- Whether to keep ExpertiseScore table data or drop it

</decisions>

<specifics>
## Specific Ideas

### Market Average Entry Computation
- Compute once per scoring run: `SELECT market_id, AVG(avg_entry_price) FROM positions WHERE direction IN ('LONG','SHORT') GROUP BY market_id`
- This is the "crowd price" that CLV measures against

### Capital Deployed Calculation
- LONG: size × avg_entry_price (you pay the price to buy shares)
- SHORT: size × (1 - avg_entry_price) (you pay the complement)

### Decision Tree for Real-Time Signals
```
New position detected from address X
├── Is X scored? (active in last 30 days, >= min_positions)
│   ├── No -> ignore
│   └── Yes -> is X in Q5?
│       ├── No -> ignore
│       └── Yes -> what market category?
│           ├── NBA/crypto -> ignore
│           ├── La Liga/Ligue 1 -> only if perfect setup
│           └── Esports/EPL/Politics ->
│               └── Can I enter at or below X's entry price?
│                   ├── No -> set price alert, wait
│                   └── Yes -> how many other Q5 on same side?
│                       ├── 0-2 -> 1% bankroll
│                       └── 3+  -> 2-3% bankroll
│                           └── ENTER. Log entry price, track slippage.
```

### Edge Cases
- Season transitions (EPL Aug-Sep): re-score more aggressively around season boundaries
- CLV decay: time between Q5 entry and your entry is critical variable
- Survivorship bias works in our favor: dropouts had higher ROI than survivors

</specifics>

<deferred>
## Deferred Ideas

- Ingesting EPL/politics/other market data (separate phase, pipeline already supports it)
- Live CLOB price fetching for real-time edge calculation (needs API integration)
- Automated trade execution based on Q5 signals
- Fade detection for reliably bad traders as contrarian signals (mentioned in roadmap goal, defer to v2 if scope is too large)

</deferred>

---

*Phase: 25-lift-based-scoring-v2*
*Context gathered: 2026-03-22 via PRD Express Path*
