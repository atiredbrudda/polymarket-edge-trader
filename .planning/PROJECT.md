# Polymarket Smart Money Tracker

## What This Is

A system that identifies "smart money" traders on Polymarket – wallets whose entries consistently beat the market's implied probability – and surfaces consensus signals when multiple smart traders converge on the same position. eSports is the first niche. The architecture is niche-agnostic via config files.

## Core Value

Reliably detect when multiple proven traders (top quintile by CLV, ROI, and Sharpe ratio) are positioned in the same new market, enabling users to follow high-signal trades.

## Requirements

### Validated

(None yet – ship to validate)

### Active

- [ ] Token catalog maps token_id → condition_id before any trade ingestion
- [ ] Trades resolve to real condition_ids, not synthetic graph_* identifiers
- [ ] Entity extraction identifies game, teams, tournament from market questions
- [ ] Position calculation aggregates trades per (trader, market) pair
- [ ] Position resolution computes PnL using market outcomes (YES/NO)
- [ ] Scoring ranks traders by quintile using CLV, ROI, Sharpe (z-score normalized)
- [ ] Detection surfaces signals when ≥2 Q5 traders converge on same market
- [ ] Alert system delivers signals to Telegram
- [ ] Every command shows Rich progress bars (no silent >1s operations)
- [ ] Commands fail loudly with clear errors when dependencies missing

### Out of Scope

- JBecker dataset – all trades predate 30-day scoring window, zero contribution
- Polygon blockchain scanning – 49M blocks, 6-7 hours per trader, not viable
- Real-time chat – high complexity, not core to smart money tracking
- Mobile app – web-first, CLI + Telegram alerts sufficient
- OAuth login – API keys sufficient for v1
- Global entity extraction – only extract entities for active niche (cost control)

## Context

**Technical environment:**
- Python 3.10+ with SQLite (WAL mode for concurrency)
- SQLAlchemy ORM (mapped-column style), Click CLI, Rich terminal UI
- Polymarket CLOB API (authenticated trades), Gamma API (markets/events)
- The Graph for historical backfill (subgraph: 7fu2DWYK93ePfzB24c2wrP94S3x4LGHUrQxphhoEypyY)
- Anthropic SDK for LLM entity extraction fallback only

**Key architectural decisions:**
- 2-tier backfill: CLOB API first (free, fast, ~6 months), Graph fallback (complete history)
- Asset ID strategy: always pick non-zero asset_id (avoids 48% bug where USDC is selected)
- Price conversion: Graph prices are decimal odds (>1 possible), convert to implied probability
- Niche config system: YAML files (tag_id, slug, min_positions, scoring_window_days, entity_fields)
- All known tag IDs documented for future niche expansion (esports=64, nba=745, politics=2, etc.)

**Prior work:**
- v1 failed due to: token catalog built too late, market_entities invisible dependency, no integration test, 30 phases before E2E test
- This rebuild targets ≤10 phases, each leaving pipeline runnable end-to-end
- Integration test on fixture data must pass before any real API work

**Known issues to address:**
- `build-positions` silently returned 0 results when no market_entities rows existed
- Entity extraction not niche-scoped burned LLM credits on 50K+ markets
- Score returns 0 results until resolved positions exist in 30-day window (bootstrap problem)

## Constraints

- **Schema**: SQLite only – no DuckDB, no parquet, no PostgreSQL
- **API rate limits**: 60 req/s hard cap on CLOB – use 50 req/s (80%) with token bucket
- **Scoring window**: 30-day rolling window, min 30 resolved positions to qualify (esports)
- **Entity extraction**: Pattern matcher first (free, ~65% coverage), LLM fallback only for unmatched
- **Phase budget**: Maximum 10 phases – each must leave pipeline runnable end-to-end
- **Test requirement**: Integration test on fixture data must pass before any real API calls
- **Code simplicity**: Simple, working code only. No over-engineering, no extra features unless explicitly requested. Readable > clever.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Token catalog before any trade ingestion | v1 poisoned pipeline with synthetic market_ids | – Pending |
| Integration test in phase 1 | v1 had 30 phases before E2E test, debt accumulated | – Pending |
| 2-tier backfill (API → Graph), no JBecker | JBecker trades all predate scoring window | – Pending |
| Pattern matcher first, LLM fallback | Running LLM on 50K markets burned credits | – Pending |
| Niche-scoped entity extraction (WHERE niche_slug=?) | Global extraction was hours of useless work | – Pending |
| Always pick non-zero asset_id in Graph parsing | v1 orphaned 48% of trades via role-based selection | – Pending |
| Loud failures on missing dependencies | Silent 0-results left users guessing | – Pending |
| Rich progress on every command | Users should never stare at blank terminal | – Pending |

---

*Last updated: 2026-03-29 after initialization from GUIDE.md*
