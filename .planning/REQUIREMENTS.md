# Requirements: Polymarket Smart Money Tracker

**Defined:** 2026-03-29
**Core Value:** Reliably detect when multiple proven traders (top quintile by CLV, ROI, and Sharpe ratio) are positioned in the same new market, enabling users to follow high-signal trades.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Schema & Token Catalog

- [ ] **SCHM-01**: All 9 core tables created with correct types (NUMERIC(20,6) for sizes, NUMERIC(10,6) for prices)
- [ ] **SCHM-02**: SQLite WAL mode enabled for read concurrency
- [ ] **TCAT-01**: Token catalog built from Gamma API before any trade ingestion
- [ ] **TCAT-02**: Every token_id maps to condition_id, question, niche_slug, node_path
- [ ] **TCAT-03**: Integration test asserts zero synthetic market_ids in trades table

### Data Ingestion

- [ ] **INGE-01**: ingest-events fetches events from Gamma API by tag_id (niche)
- [ ] **INGE-02**: ingest-events populates gamma_events and markets tables
- [ ] **INGE-03**: resolve-outcomes sets markets.outcome (YES/NO) from gamma_events
- [ ] **CLSF-01**: classify-tokens populates token_catalog from Gamma API market data
- [ ] **DSVR-01**: discover fetches active markets and traders for niche from Polymarket API
- [ ] **DSVR-02**: discover populates traders, markets, market_entities tables
- [ ] **ENTY-01**: Entity extraction uses pattern matcher first (free, ~65% coverage)
- [ ] **ENTY-02**: LLM fallback only for unmatched market questions
- [ ] **ENTY-03**: Entity extraction scoped to WHERE markets.niche_slug = :niche

### Trade Backfill

- [ ] **BKFL-01**: backfill uses 2-tier approach: Polymarket API first, Graph fallback
- [ ] **BKFL-02**: Token bucket rate limiter at 50 req/s (80% of 60 req/s cap)
- [ ] **BKFL-03**: Graph asset_id selection uses non-zero asset rule (avoids 48% bug)
- [ ] **BKFL-04**: Graph price conversion handles decimal odds (>1.0 → 1/price)
- [ ] **BKFL-05**: backfill sets traders.backfill_complete = True when done
- [ ] **BKFL-06**: Zero trades have synthetic market_ids after backfill

### Position Engine

- [ ] **POSI-01**: build-positions aggregates trades per (trader_address, market_id) pair
- [ ] **POSI-02**: Position direction: LONG (net buyer), SHORT (net seller), FLAT (net=0)
- [ ] **POSI-03**: Position size is absolute net size in tokens
- [ ] **POSI-04**: avg_entry_price is volume-weighted across all trades
- [ ] **POSI-05**: entry_timestamp and last_trade_timestamp tracked separately
- [ ] **POSI-06**: build-positions fails loudly if market_entities.game IS NULL for any market
- [ ] **RSLV-01**: resolve-positions computes pnl using markets.outcome (YES/NO)
- [ ] **RSLV-02**: LONG+YES: size * (1.0 - entry), LONG+NO: size * (0.0 - entry)
- [ ] **RSLV-03**: SHORT+NO: size * entry, SHORT+YES: size * (entry - 1.0)
- [ ] **RSLV-04**: FLAT positions have pnl = 0

### Scoring Engine

- [ ] **SCOR-01**: score uses 30-day rolling window (configurable per niche)
- [ ] **SCOR-02**: CLV = (resolution_price - entry_price) / entry_price
- [ ] **SCOR-03**: ROI = total_pnl / total_capital_deployed
- [ ] **SCOR-04**: Sharpe = mean(trade_returns) / std(trade_returns)
- [ ] **SCOR-05**: All metrics z-score normalized against all traders
- [ ] **SCOR-06**: composite = z_clv + z_roi + z_sharpe
- [ ] **SCOR-07**: quintile = pd.qcut(composite, 5, labels=[1,2,3,4,5])
- [ ] **SCOR-08**: min_positions threshold enforced (30 for esports, configurable)
- [ ] **SCOR-09**: score returns one row per qualifying trader

### Signal Detection

- [ ] **DETC-01**: detect reads lift_scores WHERE quintile = 5 (Q5 traders only)
- [ ] **DETC-02**: detect reads positions WHERE resolved = False (open markets)
- [ ] **DETC-03**: Signal generated when ≥2 Q5 traders converge on same market+direction
- [ ] **DETC-04**: signals table stores: market_id, direction, q5_count, avg_score, first_seen, last_updated

### Alert System

- [ ] **ALRT-01**: alert reads signals table for new signals
- [ ] **ALRT-02**: Telegram bot integration via TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
- [ ] **ALRT-03**: Alert messages include: market question, direction, Q5 count, avg score

### CLI & UX

- [ ] **CLI-01**: All commands use Click for CLI interface
- [ ] **CLI-02**: All commands accept --niche flag for YAML config lookup
- [ ] **UX-01**: Every command prints header line on start
- [ ] **UX-02**: Every loop uses Rich Progress bar (description, bar, M/N count, elapsed)
- [ ] **UX-03**: Operations >1s without loop use Rich spinner
- [ ] **UX-04**: Every command prints summary on completion (counts, durations, skipped)
- [ ] **UX-05**: Errors print inline in red without stopping progress bar
- [ ] **UX-06**: Transient progress bars for sub-steps, persistent for main loop

### Resilience & Validation

- [ ] **RESL-01**: Every command asserts dependencies exist at startup
- [ ] **RESL-02**: Commands fail loudly with clear error messages (no silent 0-results)
- [ ] **RESL-03**: HTTP 425 retry logic for matching engine restarts
- [ ] **SANI-01**: Sanity checks runnable before score: no synthetic IDs, all entities have game, resolved positions in window, outcomes set, end_dates set

### Niche Configuration

- [ ] **NICH-01**: YAML config files in niches/ directory (esports.yaml, nba.yaml, etc.)
- [ ] **NICH-02**: Config includes: tag_id, slug, min_positions, scoring_window_days, entity_fields
- [ ] **NICH-03**: All known tag IDs documented (esports=64, nba=745, politics=2, crypto=21, etc.)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Features

- **ADV-01**: Portfolio holdings view per trader
- **ADV-02**: Trader clustering (find similar traders)
- **ADV-03**: Market impact scoring (how much trader moves the market)
- **ADV-04**: Sharpe ratio calculation (deferred from v1)
- **ADV-05**: Native mobile app (iOS/Android)

### Multi-Niche Expansion

- **NCH2-01**: NBA niche (tag_id=745, min_positions=10, 60-day window)
- **NCH2-02**: Politics niche (tag_id=2, min_positions=30, 90-day window)
- **NCH2-03**: Crypto niche (tag_id=21, min_positions=30, 30-day window)
- **NCH2-04**: All sports sub-niches (NFL, MLB, NHL, Premier League, etc.)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| JBecker dataset | All trades predate 30-day scoring window, zero contribution to scores |
| Polygon blockchain scan | 49M blocks to scan, 6-7 hours per trader, not viable |
| Real-time chat | High complexity, not core to smart money tracking |
| Auto-trading / execution | Regulatory risk, crosses into financial advice territory |
| Wallet identity guessing | Doxxing liability, privacy concerns |
| "Hot streak" indicators | Encourages gambling mentality vs skill-based analysis |
| OAuth login | API keys sufficient for v1 |
| Mobile app | Web-first, CLI + Telegram alerts sufficient |
| Global entity extraction | Must be niche-scoped to avoid wasting LLM credits on 50K+ irrelevant markets |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCHM-01 | Phase 1 | Pending |
| SCHM-02 | Phase 1 | Pending |
| TCAT-01 | Phase 1 | Pending |
| TCAT-02 | Phase 1 | Pending |
| TCAT-03 | Phase 1 | Pending |
| CLI-01 | Phase 1 | Pending |
| CLI-02 | Phase 1 | Pending |
| NICH-01 | Phase 1 | Pending |
| NICH-02 | Phase 1 | Pending |
| NICH-03 | Phase 1 | Pending |
| INGE-01 | Phase 2 | Pending |
| INGE-02 | Phase 2 | Pending |
| INGE-03 | Phase 2 | Pending |
| CLSF-01 | Phase 2 | Pending |
| DSVR-01 | Phase 2 | Pending |
| DSVR-02 | Phase 2 | Pending |
| ENTY-01 | Phase 2 | Pending |
| ENTY-02 | Phase 2 | Pending |
| ENTY-03 | Phase 2 | Pending |
| RESL-01 | Phase 2 | Pending |
| RESL-02 | Phase 2 | Pending |
| BKFL-01 | Phase 3 | Pending |
| BKFL-02 | Phase 3 | Pending |
| BKFL-03 | Phase 3 | Pending |
| BKFL-04 | Phase 3 | Pending |
| BKFL-05 | Phase 3 | Pending |
| BKFL-06 | Phase 3 | Pending |
| RESL-03 | Phase 3 | Pending |
| SANI-01 | Phase 3 | Pending |
| POSI-01 | Phase 4 | Pending |
| POSI-02 | Phase 4 | Pending |
| POSI-03 | Phase 4 | Pending |
| POSI-04 | Phase 4 | Pending |
| POSI-05 | Phase 4 | Pending |
| POSI-06 | Phase 4 | Pending |
| RSLV-01 | Phase 4 | Pending |
| RSLV-02 | Phase 4 | Pending |
| RSLV-03 | Phase 4 | Pending |
| RSLV-04 | Phase 4 | Pending |
| SCOR-01 | Phase 5 | Pending |
| SCOR-02 | Phase 5 | Pending |
| SCOR-03 | Phase 5 | Pending |
| SCOR-04 | Phase 5 | Pending |
| SCOR-05 | Phase 5 | Pending |
| SCOR-06 | Phase 5 | Pending |
| SCOR-07 | Phase 5 | Pending |
| SCOR-08 | Phase 5 | Pending |
| SCOR-09 | Phase 5 | Pending |
| DETC-01 | Phase 6 | Pending |
| DETC-02 | Phase 6 | Pending |
| DETC-03 | Phase 6 | Pending |
| DETC-04 | Phase 6 | Pending |
| ALRT-01 | Phase 7 | Pending |
| ALRT-02 | Phase 7 | Pending |
| ALRT-03 | Phase 7 | Pending |
| UX-01 | Phase 8 | Pending |
| UX-02 | Phase 8 | Pending |
| UX-03 | Phase 8 | Pending |
| UX-04 | Phase 8 | Pending |
| UX-05 | Phase 8 | Pending |
| UX-06 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 81 total
- Mapped to phases: 81
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-29*
*Last updated: 2026-03-29 after auto-generation from GUIDE.md*
