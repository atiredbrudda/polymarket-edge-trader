# Polymarket Smart Money Tracker

## What This Is

A category-agnostic intelligence pipeline that identifies expert niche traders on Polymarket, scores their specialization depth, and aggregates their positions to surface consensus signals. It starts from active events, discovers who's trading them, backtracks their history to evaluate expertise, and alerts when qualified traders converge on a position. eSports is the first case study used to develop and validate the approach, with the pipeline designed to generalize to any Polymarket category (politics, crypto, sports) via taxonomy configuration. Built for awareness and pattern recognition, not automated trading.

## Core Value

Surface where smart money is moving in niche prediction markets so the user can see what informed traders are doing and factor that into their own thinking. The system must be category-agnostic by design — eSports is the proving ground, not the ceiling.

## Requirements

### Validated

- Polymarket CLOB API integration for events, markets, trades, and trader histories — v1.0
- Custom eSports taxonomy with game-level granularity (CS2, Dota 2, LoL, Valorant) — v1.0
- Event-first trader discovery pipeline (active events → active traders → history backtrack) — v1.0
- Trader evaluation engine (PnL, win rate, volume, minimum 5 resolved markets, recency weighting) — v1.0
- Niche specialization detection (game-level specialist vs. eSports generalist) — v1.0
- Signal aggregation with configurable thresholds (75% consensus, 3+ experts) — v1.0
- Ranked trader leaderboard per niche — v1.0
- Drill-down into individual trader profiles, stats, and position history — v1.0
- Periodic automated polling (hourly sweeps of active markets) — v1.0
- Telegram alerting with event classification and deduplication — v1.0
- 4-tier cost-optimized data ingestion (JBecker/API/Graph/Blockchain) — v1.0
- Offline trader research via JBecker dataset CLI — v1.0
- Architecture extensible to new categories via taxonomy definitions — v1.0

### Active

(Requirements for next milestone defined via `/gsd:new-milestone`)

### Out of Scope

- Web dashboard — premature until signal quality is proven
- Auto-trading / bot execution — this is an awareness tool, not a trading bot
- Real-time streaming — hourly polling is sufficient for the use case
- Mobile app — CLI + webhooks covers the interface needs
- Discord webhook alerting — Telegram sufficient for v1, Discord deferred (ALRT-02)

## Context

- **Platform:** Polymarket — prediction market on Polygon blockchain. Uses a CLOB (Central Limit Order Book) API for trading data. Traders identified by wallet addresses.
- **Current state:** v1.0 shipped. 26,306 LOC Python, 509+ tests. Full pipeline operational: ingestion → classification → evaluation → scoring → signal detection → alerting → CLI.
- **Tech stack:** Python 3.12, SQLAlchemy 2.0, Click, Rich, DuckDB, web3.py, py-clob-client, loguru, tenacity.
- **Discovery approach:** Event-first: start from active events, find who's trading them, then evaluate those traders' histories. Naturally focuses on active participants.
- **Niche hypothesis:** Traders who specialize deeply in a narrow category likely have domain knowledge that generalists don't. Their convergence on a position is a stronger signal than broad-market consensus.
- **Signal philosophy:** The output is intelligence, not instruction. Alerts are awareness triggers, not trade recommendations.
- **Known limitation:** Market scanning currently fetches ALL markets then filters. Needs niche + time-to-close filtering for practical use.
- **Known limitation:** Scoring operates at game level only. Deeper niche detection (tournament/team level) needed for the "Chelsea trader" use case.

## Constraints

- **Data source**: Polymarket CLOB API + The Graph + JBecker Parquet dataset. Rate limits constrain polling frequency.
- **Tech stack**: Python — user's preferred language.
- **Storage**: Local-first (SQLite). Database at `data/polymarket.db`.
- **Taxonomy**: Extensible by design — adding a category means defining a YAML taxonomy file.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| eSports as first case study | Small category to validate pipeline before larger markets | Good — validated architecture |
| Event-first discovery | Avoids scanning entire trader database; focuses on active participants | Good — efficient and targeted |
| Custom taxonomy over Polymarket categories | Game-level granularity needed for niche detection | Good — enables specialist scoring |
| Hourly polling, not real-time | Awareness tool doesn't need sub-minute latency | Good — reduces API pressure |
| CLI + webhooks, no web UI | Prove signal quality first before UI investment | Good — CLI sufficient for v1 |
| SQLite local-first storage | No external database infrastructure needed | Good — simple, zero-config |
| 4-tier data ingestion hierarchy | JBecker (free) → API (free) → Graph (paid) → Blockchain (slow) | Good — minimizes costs |
| Bonus-only consistency multiplier | Never penalize, only reward consistent traders | Good — conservative scoring |
| Append-only score history | INSERT-only for ExpertiseScore and SignalSnapshot | Good — enables trend analysis |

---
*Last updated: 2026-02-13 after v1.0 milestone*
