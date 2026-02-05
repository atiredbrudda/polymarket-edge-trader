# Requirements: Polymarket eSports Smart Money Tracker

**Defined:** 2026-02-05
**Core Value:** Surface where smart money is moving in eSports markets so the user can see what informed traders are doing and factor that into their own thinking.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Data Foundation

- [ ] **DATA-01**: System can fetch active eSports events and markets from Polymarket CLOB API
- [ ] **DATA-02**: System can discover traders participating in active eSports markets
- [ ] **DATA-03**: System can retrieve complete trade history for a given trader address
- [ ] **DATA-04**: System can filter trade history by date range and market resolution status
- [ ] **DATA-05**: System stores market, trader, and position data in local SQLite database
- [ ] **DATA-06**: System respects Polymarket API rate limits with built-in rate limiter

### Taxonomy

- [ ] **TAXO-01**: System uses YAML-based taxonomy definitions for eSports categories (game-level granularity)
- [ ] **TAXO-02**: System classifies Polymarket markets into taxonomy categories via keyword matching
- [ ] **TAXO-03**: Adding a new category requires only a YAML file change, not code changes

### Performance Analytics

- [ ] **PERF-01**: System calculates PnL, win rate, and total volume for each trader
- [ ] **PERF-02**: System tracks current open positions with size, direction (YES/NO), and entry price
- [ ] **PERF-03**: System calculates metrics across multiple timeframes (7d, 30d, 90d, all-time)
- [ ] **PERF-04**: System identifies traders with consistent performance vs lucky streaks across timeframes

### Scoring Engine

- [ ] **SCOR-01**: System calculates specialization depth score (0-100) per trader per eSports category
- [ ] **SCOR-02**: Score incorporates category concentration, category win rate, sample size, and recency
- [ ] **SCOR-03**: System enforces minimum sample size (5+ resolved eSports markets) before scoring
- [ ] **SCOR-04**: System applies recency weighting so recent performance counts more than old
- [ ] **SCOR-05**: System produces ranked leaderboard of traders per eSports niche

### Signal Detection

- [ ] **SGNL-01**: System detects consensus when 2+ expert traders (score >70) take same position
- [ ] **SGNL-02**: System calculates consensus strength weighted by expertise scores
- [ ] **SGNL-03**: System detects potential herding by analyzing bet timing (cluster vs independent)
- [ ] **SGNL-04**: System surfaces markets ranked by expert activity in past 1/6/24 hours
- [ ] **SGNL-05**: System generates signal confidence score (0-100) combining agreement and sample size

### Alerting

- [ ] **ALRT-01**: System sends consensus signal alerts to Telegram via bot integration
- [ ] **ALRT-02**: System sends consensus signal alerts to Discord via webhook
- [ ] **ALRT-03**: Alert payloads include market context, expert count, consensus direction, and confidence
- [ ] **ALRT-04**: System retries failed alert deliveries with exponential backoff

### CLI Interface

- [ ] **CLI-01**: User can list active eSports markets and their classification
- [ ] **CLI-02**: User can view trader profile with stats, scores, and position history
- [ ] **CLI-03**: User can view current signals ranked by confidence
- [ ] **CLI-04**: User can view ranked leaderboard of eSports experts per niche
- [ ] **CLI-05**: User can trigger a manual sweep of active markets

### Polling

- [ ] **POLL-01**: System runs automated hourly sweeps of active eSports markets
- [ ] **POLL-02**: System discovers new traders and updates scores during each sweep
- [ ] **POLL-03**: System generates and delivers alerts when new consensus signals are detected

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Alerting Enhancements

- **ALRT-05**: System supports generic webhook output (JSON payloads to arbitrary URLs)
- **ALRT-06**: System sends large position (whale) alerts when trades exceed configurable threshold

### Watchlists

- **WTCH-01**: User can create and manage custom trader watchlists
- **WTCH-02**: User can compare multiple traders side-by-side
- **WTCH-03**: System alerts when watchlist traders make moves in eSports markets

### Validation

- **VALD-01**: System can backtest consensus signals against historical resolved markets
- **VALD-02**: System reports hit rate and theoretical ROI for past signals

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Automated trading execution | Regulatory risk, liability; this is an awareness tool, not a trading bot |
| Market outcome predictions | We track what experts do, not predict outcomes |
| Broad multi-category coverage (politics, crypto) | Architecture supports it, but specialization IS the product for v1 |
| Real-time orderbook depth / market making data | Market maker domain, not intelligence tool domain |
| Social/community features | CLI + webhooks architecture, not a social platform |
| Portfolio management / position sizing advice | Financial advice = regulatory minefield |
| Historical replay / time machine UI | High complexity, low ROI; CLI not suited for interactive replay |
| Web dashboard | Premature until signal quality is proven |
| Mobile app | CLI + webhooks covers interface needs |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | — | Pending |
| DATA-02 | — | Pending |
| DATA-03 | — | Pending |
| DATA-04 | — | Pending |
| DATA-05 | — | Pending |
| DATA-06 | — | Pending |
| TAXO-01 | — | Pending |
| TAXO-02 | — | Pending |
| TAXO-03 | — | Pending |
| PERF-01 | — | Pending |
| PERF-02 | — | Pending |
| PERF-03 | — | Pending |
| PERF-04 | — | Pending |
| SCOR-01 | — | Pending |
| SCOR-02 | — | Pending |
| SCOR-03 | — | Pending |
| SCOR-04 | — | Pending |
| SCOR-05 | — | Pending |
| SGNL-01 | — | Pending |
| SGNL-02 | — | Pending |
| SGNL-03 | — | Pending |
| SGNL-04 | — | Pending |
| SGNL-05 | — | Pending |
| ALRT-01 | — | Pending |
| ALRT-02 | — | Pending |
| ALRT-03 | — | Pending |
| ALRT-04 | — | Pending |
| CLI-01 | — | Pending |
| CLI-02 | — | Pending |
| CLI-03 | — | Pending |
| CLI-04 | — | Pending |
| CLI-05 | — | Pending |
| POLL-01 | — | Pending |
| POLL-02 | — | Pending |
| POLL-03 | — | Pending |

**Coverage:**
- v1 requirements: 35 total
- Mapped to phases: 0
- Unmapped: 35 ⚠️

---
*Requirements defined: 2026-02-05*
*Last updated: 2026-02-05 after initial definition*
