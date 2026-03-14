# Polymarket Smart Money Tracker

## What This Is

A category-agnostic intelligence pipeline that identifies expert niche traders on Polymarket, scores their specialization depth, and aggregates their positions to surface consensus signals. It starts from active events, discovers who's trading them, backtracks their history to evaluate expertise, and alerts when qualified traders converge on a position.

eSports is the first case study. The pipeline is designed to generalize to any Polymarket category via taxonomy configuration.

**Current direction (v1.2+):** Beyond taxonomy-level specialization ("CS2 expert"), the pipeline now extracts the actual teams and tournaments from each market question via LLM, computes per-trader win rates at the team level ("wins 73% of bets involving Natus Vincere"), and exposes this via a contextual analyze command. This shifts scoring from pre-computed taxonomy scores toward query-time entity-level signals.

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
- ✓ Configurable niche scanning with `--niche` and `--closing-within` CLI filters — v1.1
- ✓ Decoupled `discover` / `backfill` / `status` commands with per-trader state tracking — v1.1
- ✓ Multi-depth expertise scoring at game, tournament, and team levels — v1.1
- ✓ Hidden specialist detection (high sub-niche concentration despite average game score) — v1.1
- ✓ JBecker token catalog (817k rows, token_id → taxonomy without Gamma API) — v1.1
- ✓ Pipeline decomposed into `score`, `detect`, `alert` + block_number timestamp resolution — v1.1
- ✓ Gamma Events API ingestion (~8,500 closed eSports events, one-time ~30s download) — v1.2
- ✓ Market outcome resolution (`markets.outcome` populated from Gamma `outcomePrices`) — v1.2
- ✓ Deep token classification (`node_path`/`depth` at game/tournament/team level via Gamma tags) — v1.2
- ✓ End-to-end scoring pipeline produces real leaderboard results on JBecker data — v1.2
- ✓ Self-healing token catalog (auto-patch unclassifiable trades after every backfill run) — v1.2
- ✓ eSports token gap recovery (156 null-token markets, 3,633 trades recovered) — v1.2
- ✓ LLM entity extraction per market (team_a, team_b, tournament, game, market_type via Claude Haiku 3.5) — v1.2
- ✓ Taxonomy normalizer (alias → canonical team names, e.g. NaVi → Natus Vincere) — v1.2
- ✓ TraderTeamStats pre-computed per-team win rates (LONG=team_a, SHORT=team_b convention) — v1.2

### Active

- [ ] Contextual analyze command — query-time win rate per team/dimension per trader, consuming TraderTeamStats (Phase 23)

## Current Milestone: v1.2 Market Resolution & Deep Classification

**Original goal:** Integrate Gamma Events API data to fix the two critical v1.1 gaps — outcome resolution and deep classification — enabling the scoring pipeline to produce real leaderboard results end-to-end.

**Actual scope (expanded):** Phases 15–23. After the original 4-phase goal was met (phases 15–18), the milestone continued to close data gaps (phases 19–20) and then shifted toward entity-level intelligence (phases 21–23). The entity layer adds a new signal dimension that was not in the original v1.2 plan — team-specific trader expertise — and introduces a different scoring model: query-time contextual win rates rather than pre-computed taxonomy scores.

**Status:** 22/23 phases complete. Phase 23 (Contextual Analyze Command) is the final piece.

### Out of Scope

- Web dashboard — premature until signal quality is proven
- Auto-trading / bot execution — this is an awareness tool, not a trading bot
- Real-time streaming — hourly polling is sufficient for the use case
- Mobile app — CLI + webhooks covers the interface needs
- Discord webhook alerting — Telegram sufficient for v1, Discord deferred

## Context

- **Platform:** Polymarket — prediction market on Polygon blockchain. Uses a CLOB (Central Limit Order Book) API for trading data. Traders identified by wallet addresses.
- **Current state:** v1.2 nearing completion. ~32k+ LOC Python. Full pipeline operational: discovery, backfill, resolution, classification, scoring, team-level stats. Leaderboard produces real results on JBecker data.
- **Tech stack:** Python 3.12, SQLAlchemy 2.0, Click, Rich, DuckDB, anthropic SDK, py-clob-client, loguru, tenacity, httpx.
- **Discovery approach:** Event-first: start from active events, find who's trading them, then evaluate those traders' histories. During discover, LLM now also extracts entity data (teams, tournament, game) from each market question.
- **Niche hypothesis:** Traders who specialize deeply in a narrow category likely have domain knowledge that generalists don't. Their convergence on a position is a stronger signal than broad-market consensus.
- **Entity hypothesis (new):** Traders with consistently high win rates when betting on a specific team (e.g. NaVi) have team-specific knowledge that taxonomy-level scoring doesn't capture. "NaVi specialist" is more useful than "CS2 specialist."
- **Signal philosophy:** The output is intelligence, not instruction. Alerts are awareness triggers, not trade recommendations.
- **Known limitations:**
  - 158 null-token catalog gaps remain unfixable (markets with `tokens=NULL` in DB — no token_id available). Tier 3 inserts category-only entry with `node_path=NULL`.
  - Slow test suite (~32 min) — `_ensure_catalog_built` in `ingest.py` calls real Gamma API on every in-memory DB test. Pre-existing since Phase 13.
  - Entity coverage depends on `discover` having been run — only markets scanned via discover have `market_entities` rows. Historical markets without entities won't appear in team stats.

## Constraints

- **Data source**: Polymarket CLOB API + The Graph + JBecker Parquet dataset. Rate limits constrain polling frequency.
- **Tech stack**: Python — user's preferred language.
- **Storage**: Local-first (SQLite). Database at `data/polymarket.db`.
- **Taxonomy**: Extensible by design — adding a category means defining a YAML taxonomy file.
- **LLM usage**: Claude Haiku 3.5 via Anthropic API. Used only for entity extraction during discover (not for scoring or alerting). Model is configurable.

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
| Token catalog via Gamma Events API | Originally planned via DuckDB JBecker scan; rewritten to Gamma API tag-filter | Good — simpler, more accurate |
| Savepoint idempotent inserts | JBecker backfill uses SAVEPOINT per insert to handle duplicates cleanly | Good — no IntegrityError crashes |
| Sweep decomposed into score/detect/alert | Monolithic sweep split into three composable commands | Good — enables partial runs |
| LLM entity extraction via Claude Haiku 3.5 | Structured JSON extraction of team/tournament/game from market question text | Good — avoids brittle regex; Haiku cost negligible at per-market scale |
| No FK from market_entities to markets | Plain string join on condition_id — avoids migration complexity | Good — consistent with project pattern |
| TraderTeamStats as pre-computed table | Enables cross-trader team queries at O(1) vs full join scan | Good — Phase 23 can sort "who bets on NaVi" efficiently |
| LONG=team_a / SHORT=team_b convention | Binary market YES side = team_a; NO side = team_b. Established in Phase 22, consumed by Phase 23 | Good — unambiguous direction mapping |
| Entity-level scoring replaces (not augments) pre-computed scoring | Phase 23 Contextual Analyze Command computes win rates on demand from TraderTeamStats rather than running the pre-computed score pipeline | Pending validation (Phase 23) |

---
*Last updated: 2026-03-14 after Phase 22 complete*
