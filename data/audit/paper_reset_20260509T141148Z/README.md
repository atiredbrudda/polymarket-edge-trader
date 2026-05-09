# Paper Reset Snapshot — 2026-05-09 14:11:48 UTC

**Reason:** Strategy ship — CONSIDER tighten (q5≥2→q5≥3) + divisor ÷N→÷√N. Clean cohort cutover after framework sign-off.
**Motivating review:** [[Live Bridge Review 2026-05-09]] + [[Strategy Dimensions Walk 2026-05-09]] (strategy dimensions framework sign-off).
**Reset by:** user (ship session 2026-05-09).
**Window archived:** 2026-05-03 08:34 UTC → 2026-05-09 10:09 UTC (6.06 days, 241 BUYs).
**Starting bankroll reset to:** $10,000 (was $6,652.18 cash + $2,106.62 open positions + $1,241.21 realized loss).

## Contents

| File | Source | Rows | Note |
|---|---|---|---|
| paper.db | full copy of data/paper_trader/paper.db | account (1) + 241 positions + 334 trades + 5741 snapshots | $6,652.18 cash at snapshot; $10,000 starting (2026-05-03 reset) |
| bridge_decisions.csv | analytics.db.bridge_decisions (≥2026-05-03T08:34) | 9,441 | post-reset window only; live table continues to grow |
| take_profit_log.csv | analytics.db.take_profit_log | 92 | full table (all entries are post-reset) |

## Active rules at reset (2026-05-09 — after ship)

| Rule | Value | Source |
|---|---|---|
| Bankroll | $10,000 | Reset 2026-05-09 |
| ACT threshold | net_q5 ≥ 3 AND clv_dom_count < q5_count | 2026-05-03 (CLV gate); 2026-04-25 (net_q5≥3) |
| **CONSIDER threshold** | **net_q5 ≥ 3 (all-CLV-dom — demoted from ACT)** | **2026-05-09** ← CHANGED from net_q5≥2 |
| WATCH (formerly CONSIDER) | net_q5 = 2 | 2026-05-09 (tightened; no longer traded) |
| Spread hard limit | +0.03 (3c) | Initial |
| Spread soft limit | +0.01 (1c, half size) | Initial |
| Negative-spread floor | −0.30 (SKIP_FALLING_KNIFE) | 2026-05-03 |
| Price floor | $0.05 | 2026-04-16 |
| Take-profit | 1.5× entry (50%) | 2026-04-16 |
| Stop-loss | None | 2026-04-16 (proven harmful) |
| ACT size | 2.0% bankroll | Initial |
| CONSIDER size | 1.0% bankroll | Initial |
| **Correlated adjustment** | **÷ √event_group_size** | **2026-05-09** ← CHANGED from ÷N |
| CLV-Dom demote | ACT→CONSIDER when all CLV-dominant (net_q5≥3) | 2026-05-03 (KEEP verdict 2026-05-09) |
| Opposite side | Refuse (SKIP_OPPOSITE_HELD) | 2026-04-17 |
| Re-entry after TP | Refuse (SKIP_TP_EXIT) | 2026-04-17 |
| Dead orderbook | Auto-resolve, skip (SKIP_NO_BOOK) | 2026-04-17 |
| Q5 composite floor | −0.10 (panel=205) | 2026-04-19 (INVESTIGATE verdict 2026-05-09; held) |

Key change from prior cohort (2026-05-03 reset): native CONSIDER (net_q5=2) eliminated. Only CONSIDER signals now are all-CLV-dom signals with net_q5≥3 (the demoted-ACT cohort that outperformed +$8.7/buy).

## Knob inventory snapshot at reset

| Knob | Status | Last measured | Next trigger |
|---|---|---|---|
| CONSIDER threshold | SHIPPED 2026-05-09 (≥3) | 5/9 review n=149 | Re-measure ≥200 closed on new rule |
| Divisor mode | SHIPPED 2026-05-09 (÷√N) | 5/9 review n=94 multi | Re-measure ≥200 closed |
| Rescue predictor P1+P2 | READY-TO-SHIP (HELD) | SLICING-PASSED 5/9 | Ship at next full bridge review (≥200 closed or 14d) |
| CLV-Dom demote | ACTIVE-KEEP | 5/9 review (demote cohort +$8.7/buy) | Watch CLV-dom reversal claim (2 reviews running, TRIPWIRE tier) |
| SKIP_FALLING_KNIFE | ACTIVE-KEEP | 5/9 KEEP verdict | Next review |
| SKIP_OPPOSITE_HELD cost | ACTIVE-MEASURED-COSTLY | 5/9 42% costly / ~$1,500 est | Phase 3 recurring query added to Bridge Review Protocol §4 |
| Q5 composite floor | ACTIVE-INVESTIGATE | 5/9 panel=205 (−39% from deploy) | Composition diff (Tier 3) + Tier 2 tripwire script SHIPPED 5/9 |
| B-band sign flip | WATCH (TRIPWIRE tier) | 5/9 review n=87 | Re-measure at next review |
| TP poll cadence / rescue predictor | TRIGGER FIRED ×2 | 5/9 33 missed-TP losses | Rescue predictor P1+P2 is the action path |
| ACT/CONSIDER dynamic scaling | GATED | gated on Q5 panel ≥1000 | — |
| Within-Q5 timing 4th feature | PROPOSED | — | — |
| Bankroll scale-up (gate 6) | PARTIAL | deliberate TBD (live capital deferred) | — |
| Drawdown trip-wire (gate 7) | YES | thresholds documented 2026-05-09 | — |
| Event group divisor A/B | PARKED 2026-05-04 | ρ=+0.31 confirmed; ÷√N shipped | — |

## Framework state at reset (Strategy Dimensions STABLE v2, 2026-05-09)

**Framework version:** STABLE v2 (2026-05-09) — v2 amendments added cross-dimension interactions §3×§11, §6×§7×§1; decision-timescale column; Data Quality / Regime Validity added as dimensions.

**Gate status (pre-reset read, 2026-05-09T14:12:16Z):**

| Gate | Status | Value | Tier |
|---|---|---|---|
| 1: Position-size distribution anchored | YES | p10=$27.48, p50=$70.30, p90=$94.36 (n=241) | — |
| 2: Capital efficiency measured | NOT YET | — | — |
| 3: Esports-only formally defended | YES | [[Esports-Only Decision]] page present | — |
| 4: Portfolio Construction measured | NOT YET | — | — |
| 5: Friction-adjusted edge positive | NOT YET | — | — |
| 6: Bankroll scale-up criterion | PARTIAL | thresholds TBD (live capital deferred) | — |
| 7: Drawdown trip-wire | YES | thresholds documented | — |
| 8: §12 Data Quality sweep formalized | NOT YET | — | — |
| 9: Stable-rule-set sample sufficient | YES | 241 buys since 2026-05-03 (proxy) | MAGNITUDE |
| 10: Cross-validation refresh AT deployment | NOT YET | not triggered | — |

Summary: 4 YES / 1 PARTIAL / 5 NOT YET. Paper-side rule changes not gated. Live-capital deployment gates (2, 4, 5, 8, 10) remain open.

**Hot-list items completed during window (2026-05-03 → 2026-05-09):**
- SKIP_OPPOSITE_HELD cost measured (42% costly, Phase 1+2 instrumentation shipped)
- Q5 panel snapshot landed (205 / −39% from deploy; INVESTIGATE verdict)
- TP counterfactual sign flip observed (+$259 cumulative — steady-state effect)
- B-band sign flip surfaced (mechanism unclear; TRIPWIRE)

**Held-constant assumptions for the window:**
- Sizing measured under TP-inclusive live exit policy ✅ (lesson from [[Plan Event Group Divisor 2026-05-04]])
- Entry Logic cohorts (§3) measured while assuming Signal Generation (§1) panel stable → assumption VIOLATED mid-window (panel contraction was ongoing; downstream cohorts pre/post-panel-change not cleanly separable)
- Rescue predictor unshipped during window (by design — pre-committed sequencing)

**§12 Data Quality flags during window:**
- Q5 panel −39% contraction is upstream signal change; downstream WR claims adjusted to DIRECTION tier (not PRODUCTION)
- CLV-dom reversal effective-N too small for DIRECTION tier (clean-ACT n=12-18, cluster≈3 → effective 4-6; TRIPWIRE only)

## What was computed from this data

- [[Live Bridge Review 2026-05-09]] — full cohort analysis (241 BUYs, 88 TP, 121 HTR)
- [[Strategy Dimensions Walk 2026-05-09]] — framework leak walk
- [[Plan SKIP_OPPOSITE_HELD Cost 2026-05-09]] — cost measurement plan (Phase 1+2 shipped)
- `Backtest/missed_tp_polymarket_all_losses_2026-05-09.json` — 33 missed-TP losses on 106 HTR

## How to query

```python
import sqlite3

# Pre-reset paper.db (the archived copy)
paper = sqlite3.connect("data/audit/paper_reset_20260509T141148Z/paper.db")

# Bridge decisions for this window from the archive CSV
import csv
with open("data/audit/paper_reset_20260509T141148Z/bridge_decisions.csv") as f:
    rows = list(csv.DictReader(f))

# Or filter the live analytics.db by window
analytics = sqlite3.connect("data/analytics.db")
decisions = analytics.execute(
    "SELECT * FROM bridge_decisions WHERE checked_at BETWEEN '2026-05-03T08:34:00' AND '2026-05-09T10:09:30'"
).fetchall()
```
