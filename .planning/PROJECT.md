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
- ✓ Configurable niche scanning with `--niche` and `--closing-within` CLI filters (SCAN-01–04) — v1.1
- ✓ Decoupled `discover` / `backfill` / `status` commands with per-trader state tracking (PIPE-01–04) — v1.1
- ✓ Multi-depth expertise scoring at game, tournament, and team levels (DEEP-01–05) — v1.1
- ✓ Hidden specialist detection (high sub-niche concentration despite average game score) — v1.1
- ✓ JBecker token catalog (817k rows, token_id → taxonomy without Gamma API) — v1.1
- ✓ Pipeline decomposed into `score`, `detect`, `alert` + block_number timestamp resolution — v1.1

### Active

See v1.2 requirements (to be defined by `/gsd:new-milestone`).

**Known gaps carried into v1.2:**
- Market outcome resolution missing — `markets.outcome=NULL` prevents position PnL scoring
- Token catalog classification only reaches eSports root (node_path=NULL); deep classification via Events API needed
- Scoring produces no leaderboard results end-to-end until resolution is wired

## Current Milestone: v1.2 (Planning)

**Goal:** TBD — likely: market outcome resolution via Events API, deep classification beyond eSports root, working end-to-end scoring on JBecker data.

### Out of Scope

- Web dashboard — premature until signal quality is proven
- Auto-trading / bot execution — this is an awareness tool, not a trading bot
- Real-time streaming — hourly polling is sufficient for the use case
- Mobile app — CLI + webhooks covers the interface needs
- Discord webhook alerting — Telegram sufficient for v1, Discord deferred (ALRT-02)

## Context

- **Platform:** Polymarket — prediction market on Polygon blockchain. Uses a CLOB (Central Limit Order Book) API for trading data. Traders identified by wallet addresses.
- **Current state:** v1.1 shipped. ~32,065 LOC Python (15,400 src + 16,665 tests). Full pipeline operational with targeted scanning, decoupled backfill, and multi-depth scoring. JBecker token catalog bridges 817k trade tokens to taxonomy.
- **Tech stack:** Python 3.12, SQLAlchemy 2.0, Click, Rich, DuckDB, web3.py, py-clob-client, loguru, tenacity, httpx.
- **Discovery approach:** Event-first: start from active events, find who's trading them, then evaluate those traders' histories. Naturally focuses on active participants.
- **Niche hypothesis:** Traders who specialize deeply in a narrow category likely have domain knowledge that generalists don't. Their convergence on a position is a stronger signal than broad-market consensus.
- **Signal philosophy:** The output is intelligence, not instruction. Alerts are awareness triggers, not trade recommendations.
- **Known limitation:** Market outcome resolution missing — `markets.outcome=NULL` for all 117k markets. Positions cannot be resolved for PnL scoring until resolution data is loaded.
- **Known limitation:** Token catalog classification only reaches eSports root (node_path=NULL). Deep classification via Gamma Events API event tags needed.
- **Data source insight:** Gamma Events API (`gamma-api.polymarket.com/events`) returns ~8,500 closed esports events with nested markets, `outcomePrices`, `clobTokenIds`, and multi-level `tags` (game/tournament/team slugs). One-time ~30s download, ~10MB. This is the authoritative resolution + deep-classification source for v1.2.

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
| Token catalog via Gamma Events API | Originally planned as DuckDB scan of JBecker parquet; rewritten to Gamma API tag-filter (tag_id=64) | ⚠️ Revisit — produces niche_slug='esports' only, no game/tournament/team depth |
| Savepoint idempotent inserts | JBecker backfill uses SAVEPOINT per insert to handle duplicates cleanly | Good — no IntegrityError crashes |
| Sweep decomposed into score/detect/alert | Monolithic sweep split into three composable commands | Good — enables partial runs |
| Events API for market resolution | Gamma `/events` endpoint returns outcomePrices + clobTokenIds — authoritative resolution source | Pending (v1.2) |

---
*Last updated: 2026-02-21 after v1.1 milestone*
