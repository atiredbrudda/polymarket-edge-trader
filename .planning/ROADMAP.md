# Polymarket Smart Money Tracker – Roadmap

**Core Value:** Reliably detect when multiple proven traders (top quintile by CLV, ROI, and Sharpe ratio) are positioned in the same new market, enabling users to follow high-signal trades.

**Overview:** This roadmap delivers a trader analytics pipeline that identifies "smart money" on Polymarket and surfaces consensus signals via Telegram alerts. Each phase leaves the pipeline runnable end-to-end, with integration testing before real API work.

---

## Phases

### Phase 1: Foundation + Integration Test

**Goal:** Pipeline foundation is wired and testable on fixture data before any real API complexity.

**Dependencies:** None (starting point)

**Plans:** 11 plans

**Status:** ✅ Complete

**Plans:**
- [x] 01-01-PLAN.md - Database schema with 9 tables, WAL mode, FK enforcement
- [x] 01-02-PLAN.md - Pydantic config validation + esports.yaml
- [x] 01-03-PLAN.md - Click CLI with --niche flag + build-token-catalog command
- [x] 01-04-PLAN.md - Integration test (TCAT-03) with fixture data
- [x] 01-05-PLAN.md - Core schema migrations (trader_address, end_date, team_a/team_b, NUMERIC precision)
- [x] 01-06-PLAN.md - gamma_events rebuild (normalized columns, no JSON blob)
- [x] 01-07-PLAN.md - Integration test update (schema verification test)
- [x] 01-08-PLAN.md - Gap closure verification checkpoint
- [x] 01-09-PLAN.md - Schema gap closure (NUMERIC affinity, UNIQUE constraint, trader_address index, market_type column)
- [x] 01-10-PLAN.md - NicheConfig.tag_id type fix (str → int)
- [x] 01-11-PLAN.md - signals.avg_score NUMERIC fix (raw SQL with NUMERIC(10,6))

**Requirements:**
- SCHM-01: All 9 core tables created with correct types
- SCHM-02: SQLite WAL mode enabled for read concurrency
- TCAT-01: Token catalog built from Gamma API before any trade ingestion
- TCAT-02: Every token_id maps to condition_id, question, niche_slug, node_path
- TCAT-03: Integration test asserts zero synthetic market_ids in trades table
- CLI-01: All commands use Click for CLI interface
- CLI-02: All commands accept --niche flag for YAML config lookup
- NICH-01: YAML config files in niches/ directory
- NICH-02: Config includes tag_id, slug, min_positions, scoring_window_days, entity_fields
- NICH-03: All known tag IDs documented

**Success Criteria:**
1. Database schema exists with all 9 tables (traders, markets, market_entities, gamma_events, token_catalog, trades, positions, lift_scores, signals)
2. Token catalog can be built and queried (token_id → condition_id mapping works)
3. Integration test passes on fixture data with zero synthetic market_ids
4. CLI commands exist and accept --niche flag (even if stubbed)
5. YAML niche config (esports.yaml) is loadable and validated

---

### Phase 2: Data Ingestion Layer

**Goal:** Core reference data (events, markets, entities) populated for the niche.

**Dependencies:** Phase 1 complete (schema + token catalog)

**Status:** ✅ Complete (2026-03-29)

**Plans:** 6 plans

**Plans:**
- [x] 02-01-PLAN.md - ingest-events command (Gamma API by tag_id)
- [x] 02-02-PLAN.md - resolve-outcomes command (YES/NO from gamma_events)
- [x] 02-03-PLAN.md - classify-tokens command (populate token_catalog)
- [x] 02-04-PLAN.md - discover command (Polymarket API for traders/markets)
- [x] 02-05-PLAN.md - Entity extraction pattern matcher (~65% coverage)
- [x] 02-06-PLAN.md - LLM fallback for unmatched market questions

**Requirements:**
- INGE-01: ingest-events fetches events from Gamma API by tag_id (niche)
- INGE-02: ingest-events populates gamma_events and markets tables
- INGE-03: resolve-outcomes sets markets.outcome (YES/NO) from gamma_events
- CLSF-01: classify-tokens populates token_catalog from Gamma API market data
- DSVR-01: discover fetches active markets and traders for niche from Polymarket API
- DSVR-02: discover populates traders, markets, market_entities tables
- ENTY-01: Entity extraction uses pattern matcher first (free, ~65% coverage)
- ENTY-02: LLM fallback only for unmatched market questions
- ENTY-03: Entity extraction scoped to WHERE markets.niche_slug = :niche
- RESL-01: Every command asserts dependencies exist at startup
- RESL-02: Commands fail loudly with clear error messages (no silent 0-results)

**Success Criteria:**
1. `ingest-events --niche esports` populates gamma_events and markets tables
2. `resolve-outcomes --niche esports` sets YES/NO outcomes on resolved markets
3. `classify-tokens --niche esports` builds token_catalog with condition_id mappings
4. `discover --niche esports` populates traders and market_entities tables
5. Commands fail with clear errors if dependencies missing (e.g., "No niche config found")
6. Entity extraction uses pattern matcher first, LLM only for unmatched

---

### Phase 3: Trade Backfill (2-Tier)

**Goal:** Historical trades ingested with correct token mappings and no data loss.

**Dependencies:** Phase 2 complete (token_catalog + market_entities exist)

**Status:** ✅ Complete (2026-03-29)

**Plans:** 3 plans

**Plans:**
- [x] 03-01-PLAN.md - API clients: GraphAPIClient + DataAPIClient.fetch_user_trades extension
- [x] 03-02-PLAN.md - Backfill command with 2-tier orchestration (API first, Graph fallback)
- [x] 03-03-PLAN.md - Sanity-check command with 5 SQL validation queries (SANI-01)

**Requirements:**
- BKFL-01: backfill uses 2-tier approach: Polymarket API first, Graph fallback
- BKFL-02: Token bucket rate limiter at 20 req/s (Data API limit per RESEARCH.md)
- BKFL-03: Graph asset_id selection uses non-zero asset rule (avoids 48% bug)
- BKFL-04: Graph price conversion handles decimal odds (>1.0 → 1/price)
- BKFL-05: backfill sets traders.backfill_complete = True when done
- BKFL-06: Zero trades have synthetic market_ids after backfill
- RESL-03: HTTP 425 retry logic for matching engine restarts
- SANI-01: Sanity checks runnable before score: no synthetic IDs, all entities have game, resolved positions in window, outcomes set, end_dates set

**Success Criteria:**
1. `backfill --niche esports` fetches trades via Polymarket API first
2. Graph fallback activates when API returns no data for a trader
3. Zero trades have synthetic market_ids (all resolve to condition_id)
4. Zero trades have asset_id="0" (USDC selection bug avoided)
5. Prices >1.0 are converted to implied probability (1/price)
6. traders.backfill_complete = True after completion
7. Retry logic handles HTTP 425 during matching engine restarts

---

### Phase 4: Position Engine

**Goal:** Trades aggregated into positions with direction, size, and entry price.

**Dependencies:** Phase 3 complete (trades exist with valid token_id references)

**Status:** ✅ Complete (2026-03-29)

**Plans:** 2 plans

**Plans:**
- [x] 04-01-PLAN.md - build-positions command (SQL aggregation with GROUP BY)
- [x] 04-02-PLAN.md - resolve-positions command (CASE-based PnL computation)

**Requirements:**
- POSI-01: build-positions aggregates trades per (trader_address, market_id) pair
- POSI-02: Position direction: LONG (net buyer), SHORT (net seller), FLAT (net≈0)
- POSI-03: Position size is absolute net size in tokens
- POSI-04: avg_entry_price is volume-weighted across all trades
- POSI-05: entry_timestamp and last_trade_timestamp tracked separately
- POSI-06: build-positions fails loudly if market_entities.game IS NULL for any market
- RSLV-01: resolve-positions computes pnl using markets.outcome (YES/NO)
- RSLV-02: LONG+YES: size * (1.0 - entry), LONG+NO: size * (0.0 - entry)
- RSLV-03: SHORT+NO: size * entry, SHORT+YES: size * (entry - 1.0)
- RSLV-04: FLAT positions have pnl = 0

**Success Criteria:**
1. `build-positions --niche esports` creates one row per (trader, market) pair
2. Positions show correct direction (LONG/SHORT/FLAT) based on net trade flow
3. avg_entry_price is volume-weighted average across all trades
4. `resolve-positions --niche esports` computes pnl for resolved positions
5. PnL formulas produce correct results for all 4 outcome combinations
6. Command fails if any market_entities.game IS NULL

---

### Phase 5: Scoring Engine

**Goal:** Traders ranked by quintile using CLV, ROI, and Sharpe ratio.

**Dependencies:** Phase 4 complete (resolved positions exist in 30-day window)

**Status:** ✅ Complete (2026-03-29)

**Plans:** 5 plans

**Plans:**
- [x] 05-01-PLAN.md - Data extraction with 30-day window filtering
- [x] 05-02-PLAN.md - CLV, ROI, Sharpe metrics calculation
- [x] 05-03-PLAN.md - Z-score normalization and quintile assignment
- [x] 05-04-PLAN.md - Score CLI command with database write
- [x] 05-05-PLAN.md - Integration tests for full scoring pipeline

**Requirements:**
- SCOR-01: score uses 30-day rolling window (configurable per niche)
- SCOR-02: CLV = (resolution_price - entry_price) / entry_price
- SCOR-03: ROI = total_pnl / total_capital_deployed
- SCOR-04: Sharpe = mean(trade_returns) / std(trade_returns)
- SCOR-05: All metrics z-score normalized against all traders
- SCOR-06: composite = z_clv + z_roi + z_sharpe
- SCOR-07: quintile = pd.qcut(composite, 5, labels=[1,2,3,4,5])
- SCOR-08: min_positions threshold enforced (30 for esports, configurable)
- SCOR-09: score returns one row per qualifying trader

**Success Criteria:**
1. `score --niche esports` returns one row per trader with ≥30 resolved positions
2. CLV, ROI, Sharpe calculated correctly for each trader
3. Metrics are z-score normalized against all traders in niche
4. Composite score = z_clv + z_roi + z_sharpe
5. Quintile assignment via pd.qcut produces ~20% of traders in each quintile
6. lift_scores table populated with all metrics and quintile rankings

---

### Phase 6: Signal Detection

**Goal:** Consensus signals identified when ≥2 Q5 traders converge on same market.

**Dependencies:** Phase 5 complete (lift_scores with quintile rankings exist)

**Status:** ✅ Complete (2026-03-29)

**Plans:** 3 plans

**Plans:**
- [x] 06-01-PLAN.md - Core detection logic (convergence.py, writer.py)
- [x] 06-02-PLAN.md - CLI integration (detect command with Rich UX)
- [x] 06-03-PLAN.md - TDD integration tests (test_detection.py)

**Requirements:**
- DETC-01: detect reads lift_scores WHERE quintile = 5 (Q5 traders only)
- DETC-02: detect reads positions WHERE resolved = False (open markets)
- DETC-03: Signal generated when ≥2 Q5 traders converge on same market+direction
- DETC-04: signals table stores: market_id, direction, q5_count, avg_score, first_seen, last_updated

**Success Criteria:**
1. `detect --niche esports` identifies Q5 traders from lift_scores
2. Signals generated only for unresolved (open) markets
3. Signal requires ≥2 Q5 traders on same market with same direction
4. signals table populated with market_id, direction, q5_count, avg_score
5. first_seen and last_updated timestamps tracked for each signal

---

### Phase 7: FLAT Position Tracking

**Goal:** Traders who exit before market resolution are correctly scored — exit price tracked, realized PnL computed without needing market outcome.

**Dependencies:** Phase 6 complete (full pipeline through signal detection)

**Plans:** 3 plans

**Status:** ✅ Complete (2026-04-06)

**Plans:**
- [x] 07-01-PLAN.md — Schema migration (avg_exit_price) + BUY/SELL aggregation split
- [x] 07-02-PLAN.md — FLAT-first resolution pass + extraction + CLV fix
- [x] 07-03-PLAN.md — Tests: build-positions, resolve-positions, scoring metrics, integration

**Requirements:**
- FLAT-01: positions table has avg_exit_price NUMERIC(10,6) column (migration-safe)
- FLAT-02: build-positions computes avg_entry_price from BUY trades only (volume-weighted)
- FLAT-03: build-positions computes avg_exit_price from SELL trades only (volume-weighted)
- FLAT-04: FLAT positions use gross BUY volume as size (not net≈0)
- FLAT-05: resolve-positions resolves FLAT positions immediately using avg_exit_price (no market outcome needed): pnl = size * (avg_exit_price - avg_entry_price)
- FLAT-06: scoring/extraction.py returns avg_exit_price and direction columns
- FLAT-07: calculate_clv uses avg_exit_price as resolution_price for FLAT direction (not outcome map)
- FLAT-08: All affected tests updated to cover new FLAT behavior

**Success Criteria:**
1. positions table has avg_exit_price column after migration
2. avg_entry_price reflects BUY-only weighted average (not blended with sells)
3. avg_exit_price reflects SELL-only weighted average
4. FLAT position size = total BUY volume (not zero)
5. FLAT positions resolve with correct realized PnL without requiring markets.outcome
6. CLV calculation for FLAT positions uses avg_exit_price as close price
7. Tests cover FLAT PnL, FLAT CLV, and the round-trip scoring of a trader who exits before resolution

---

### Phase 8: Detect Enrichment

**Goal:** Signals carry CLV dominance, entry price range, and tier — enabling actionable prioritization without relying on avg_score noise.

**Dependencies:** Phase 7 complete (positions have correct entry/exit prices)

**Plans:** 3 plans

**Status:** ✅ Complete (2026-04-06)

**Plans:**
- [x] 08-01-PLAN.md — Schema migration (4 new signals columns) + convergence query enrichment
- [x] 08-02-PLAN.md — Writer upsert update + detect.py wiring
- [x] 08-03-PLAN.md — TDD integration tests (test_enrichment.py)

**Requirements:**
- ENRC-01: signals table has clv_dominant_count INTEGER column (migration-safe)
- ENRC-02: signals table has avg_entry_price NUMERIC(10,6) column (migration-safe)
- ENRC-03: signals table has min_entry_price NUMERIC(10,6) column (migration-safe)
- ENRC-04: signals table has tier TEXT column (migration-safe)
- ENRC-05: convergence query computes clv_dominant_count = count of Q5 traders with clv_zscore > 0
- ENRC-06: convergence query computes avg_entry_price = AVG(positions.avg_entry_price) for converging traders
- ENRC-07: convergence query computes min_entry_price = MIN(positions.avg_entry_price) for LONG signals
- ENRC-08: tier assigned: q5_count=1 → WATCH, q5_count=2 → CONSIDER, q5_count>=3 → ACT
- ENRC-09: writer upserts all new fields; avg_score retained but not used as quality signal

**Success Criteria:**
1. signals table has clv_dominant_count, avg_entry_price, min_entry_price, tier after migration
2. detect populates all four new fields on every signal
3. clv_dominant_count correctly counts Q5 traders with clv_zscore > 0
4. tier is WATCH/CONSIDER/ACT based solely on q5_count thresholds
5. avg_entry_price and min_entry_price reflect Q5 traders' actual position entry prices
6. Tests assert all new fields are populated and correct on detected signals

---

### Phase 9: Alert System + Pipeline Health

**Goal:** Detected signals delivered to user via alerts, with lifecycle management (acknowledgement, escalation, missed-alert handling) and periodic health checks that verify the pipeline is producing correct results end-to-end.

**Dependencies:** Phase 8 complete (enriched signals with tier/entry price exist)

**Status:** Planned

**Plans:** 3 plans

Plans:
- [x] 09-01-PLAN.md — Health foundation: dual-channel notify, health_log table, psutil, test scaffold
- [x] 09-02-PLAN.md — Per-cron pre-flight checks + health-check CLI command
- [x] 09-03-PLAN.md — Daily summaries + weekly health reports (Q5 diff, scoring drift, quiet canary)

**Requirements:**
- HLTH-01: Per-cron pre-flight checks (memory/disk thresholds, stage exit codes, lift_scores freshness)
- HLTH-02: Daily summary (signals count, traders discovered/backfilled, errored stages)
- HLTH-03: Weekly health report (Q5 diff, scoring drift, data completeness, quiet canary)
- HLTH-04: Dual-channel alert delivery — Telegram bot + macOS native notifications
- HLTH-05: Alert + skip cycle on pre-flight failure — never kill external processes
- HLTH-06: Health check results logged for historical review

**Success Criteria:**
1. Cron aborts early with alert when memory/disk below threshold
2. Failed stages trigger Telegram + macOS notification with stage name and error
3. Daily summary delivered via both channels with signal/trader/error counts
4. Weekly report shows Q5 list changes, scoring drift, and data completeness
5. "Suspiciously quiet" canary fires when no new signals for 7 days with active markets
6. Skipped cron cycles are logged and user is informed via both channels

---

## Progress

| Phase | Status | Requirements | Success Criteria |
|-------|--------|--------------|------------------|
| 1 - Foundation + Integration Test | ✅ Complete | 10 | 5 |
| 2 - Data Ingestion Layer | ✅ Complete (2026-03-29) | 11 | 6 |
| 3 - Trade Backfill (2-Tier) | ✅ Complete (2026-03-29) | 8 | 7 |
| 4 - Position Engine | ✅ Complete (2026-03-29) | 10 | 6 |
| 5 - Scoring Engine | ✅ Complete (2026-03-29) | 9 | 6 |
| 6 - Signal Detection | ✅ Complete (2026-03-29) | 4 | 5 |
| 7 - FLAT Position Tracking | ✅ Complete (2026-04-06) | 8 | 7 |
| 8 - Detect Enrichment | ✅ Complete (2026-04-06) | 9 | 6 |
| 9 - Alert System + Pipeline Health | Planned | 6 | 6 |

---

## Requirement Coverage

**v1 Requirements:** 81 total

| Category | Count | Phases |
|----------|-------|--------|
| SCHM (Schema) | 2 | Phase 1 |
| TCAT (Token Catalog) | 3 | Phase 1 |
| CLI (CLI Interface) | 2 | Phase 1 |
| NICH (Niche Config) | 3 | Phase 1 |
| INGE (Ingestion) | 4 | Phase 2 |
| CLSF (Classification) | 1 | Phase 2 |
| DSVR (Discovery) | 2 | Phase 2 |
| ENTY (Entity Extraction) | 3 | Phase 2 |
| RESL (Resilience - assertions) | 2 | Phase 2 |
| BKFL (Backfill) | 6 | Phase 3 |
| RESL (Retry logic) | 1 | Phase 3 |
| SANI (Sanity checks) | 1 | Phase 3 |
| POSI (Positions) | 6 | Phase 4 |
| RSLV (Resolution) | 4 | Phase 4 |
| SCOR (Scoring) | 9 | Phase 5 |
| DETC (Detection) | 4 | Phase 6 |
| HLTH (Pipeline Health) | 6 | Phase 9 |
| ALRT (Alerts) | 3 | Phase 7 |
| UX (User Experience) | 6 | Phase 8 |

**Coverage:** 81/81 requirements mapped

---

## Phase Dependencies

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
  ↓         ↓         ↓         ↓         ↓         ↓         ↓
Schema   Ingestion  Backfill  Positions  Scoring  Detection  Alerts
  ↓         ↓         ↓         ↓         ↓         ↓
 NICH      ENTY      BKFL      RSLV      SCOR      DETC      ALRT
                    ↓
         Phase 8 (UX overlays all phases)
```

**Critical Path:**
- Phase 1 (token catalog) must complete before Phase 3 (backfill) to avoid synthetic IDs
- Phase 2 (market_entities) must complete before Phase 4 (positions) to enable JOINs
- Phase 4 (resolved positions) must complete before Phase 5 (scoring) for 30-day window
- Phase 5 (quintile rankings) must complete before Phase 6 (detection) for Q5 identification

---

*Roadmap created: 2026-03-29*
*Last updated: 2026-04-11 — Phase 9 planned (3 plans)*
