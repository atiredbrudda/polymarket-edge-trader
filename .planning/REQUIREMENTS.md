# Requirements: Polymarket Smart Money Tracker v1.1

**Defined:** 2026-02-13
**Core Value:** Make the pipeline practical for daily use with targeted scanning, decoupled operations, and deep niche expertise detection.

## v1.1 Requirements

### Targeted Market Scanning

- [ ] **SCAN-01**: User can specify which niche categories to scan via CLI option (e.g., `--niche esports`, `--niche epl`)
- [ ] **SCAN-02**: User can specify a time-to-close window to filter markets (e.g., `--closing-within 48h`)
- [ ] **SCAN-03**: System filters markets early in pipeline instead of fetching ALL markets then filtering client-side
- [ ] **SCAN-04**: System supports multiple niche categories in a single scan (e.g., `--niche esports --niche crypto`)

### Pipeline Decoupling

- [ ] **PIPE-01**: User can run address discovery independently without triggering history backfill
- [ ] **PIPE-02**: User can run history backfill independently for previously discovered traders
- [ ] **PIPE-03**: System tracks which traders have been discovered but not yet backfilled
- [ ] **PIPE-04**: User can view discovery and backfill status separately via CLI

### Deep Niche Scoring

- [ ] **DEEP-01**: System calculates expertise scores at tournament level (depth 2) in addition to game level
- [ ] **DEEP-02**: System calculates expertise scores at team level (depth 3) in addition to game level
- [ ] **DEEP-03**: System identifies "hidden specialists" — traders with average game-level scores but high tournament/team-level scores
- [ ] **DEEP-04**: User can view trader expertise breakdown by taxonomy depth (game, tournament, team) via CLI
- [ ] **DEEP-05**: Leaderboard supports filtering by any taxonomy depth (not just game level)

## Future Requirements

Deferred from v1.1:

- Jon-Becker dataset retroactive analysis (bulk historical scoring)
- Watchlist management and alerts
- Discord webhook alerting (ALRT-02 from v1.0)
- Whale alerting (large position threshold alerts)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web dashboard | Premature until signal quality is proven |
| Auto-trading / bot execution | Awareness tool, not a trading bot |
| Real-time streaming | Hourly polling sufficient |
| New taxonomy categories (politics, crypto) | Architecture supports it but eSports is focus for v1.1 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCAN-01 | Phase 10 | Pending |
| SCAN-02 | Phase 10 | Pending |
| SCAN-03 | Phase 10 | Pending |
| SCAN-04 | Phase 10 | Pending |
| PIPE-01 | Phase 11 | Pending |
| PIPE-02 | Phase 11 | Pending |
| PIPE-03 | Phase 11 | Pending |
| PIPE-04 | Phase 11 | Pending |
| DEEP-01 | Phase 12 | Pending |
| DEEP-02 | Phase 12 | Pending |
| DEEP-03 | Phase 12 | Pending |
| DEEP-04 | Phase 12 | Pending |
| DEEP-05 | Phase 12 | Pending |

**Coverage:**
- v1.1 requirements: 13 total
- Mapped to phases: 13 (100%)
- Unmapped: 0

---
*Requirements defined: 2026-02-13*
*Roadmap created: 2026-02-13*
