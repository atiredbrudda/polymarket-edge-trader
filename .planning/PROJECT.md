# Polymarket eSports Smart Money Tracker

## What This Is

An intelligence tool that identifies expert niche traders on Polymarket's eSports markets, scores their specialization depth, and aggregates their positions to surface consensus signals. It starts from active events, discovers who's trading them, backtracks their history to evaluate expertise, and alerts when qualified traders converge on a position. Built for awareness and pattern recognition, not automated trading.

## Core Value

Surface where smart money is moving in eSports markets so the user can see what informed traders are doing and factor that into their own thinking.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Polymarket CLOB API integration for events, markets, trades, and trader histories
- [ ] Custom eSports taxonomy with game-level granularity (CS:GO, Dota 2, LoL, Valorant, etc.)
- [ ] Event-first trader discovery pipeline (active events → active traders → history backtrack)
- [ ] Trader evaluation engine (ROI weighted by volume, minimum 5 resolved markets, calibration scoring, recency weighting)
- [ ] Niche specialization detection (game-level specialist vs. eSports generalist)
- [ ] Signal aggregation with configurable thresholds (>70% consensus, 2+ convergence)
- [ ] Ranked trader leaderboard per niche
- [ ] Drill-down into individual trader profiles, stats, and position history
- [ ] Periodic automated polling (hourly sweeps of active markets)
- [ ] CLI alert output with webhook support (Discord/Telegram)
- [ ] Architecture extensible to new categories (politics, crypto, sports) via taxonomy definitions

### Out of Scope

- Web dashboard — premature until signal quality is proven
- Auto-trading / bot execution — this is an awareness tool, not a trading bot
- Real-time streaming — hourly polling is sufficient for the use case
- Non-eSports categories in v1 — architecture supports it, but only eSports is built out
- Mobile app — CLI + webhooks covers the interface needs

## Context

- **Platform:** Polymarket — prediction market on Polygon blockchain. Uses a CLOB (Central Limit Order Book) API for trading data. Traders identified by wallet addresses.
- **Discovery approach:** Scanning all historical traders is infeasible and unnecessary. Instead, start from currently active events, find who's trading them, then evaluate those traders' histories. This naturally focuses on active participants.
- **Niche hypothesis:** Traders who specialize deeply in a narrow category (e.g., one specific esport game) likely have domain knowledge that generalists don't. Their convergence on a position is a stronger signal than broad-market consensus.
- **Signal philosophy:** The output is intelligence, not instruction. The user wants to see patterns and make their own decisions. Alerts are awareness triggers, not trade recommendations.

## Constraints

- **Data source**: Polymarket CLOB API — all data must come from public API endpoints. Rate limits will constrain polling frequency and backfill depth.
- **Tech stack**: Python — user's preferred language. Specific libraries TBD after research.
- **Storage**: Local-first (SQLite preferred) — no external database infrastructure for v1.
- **Taxonomy**: Must be extensible by design — adding a new category should mean defining a taxonomy file and running the same pipeline, not rewriting code.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Start with eSports only | Small category, easier to validate approach before scaling to larger markets | — Pending |
| Event-first discovery (not trader-first) | Avoids scanning entire trader database; focuses on active participants naturally | — Pending |
| Custom taxonomy over Polymarket categories | Polymarket's categories are too broad; game-level granularity needed for niche detection | — Pending |
| Hourly polling, not real-time | Awareness tool doesn't need sub-minute latency; reduces API pressure and complexity | — Pending |
| CLI + webhooks, no web UI | Prove signal quality first; UI investment only after value is validated | — Pending |
| Both summary signal and trader drill-down | User wants to evaluate the signal themselves, not just trust the algorithm blindly | — Pending |

---
*Last updated: 2026-02-05 after initialization*
