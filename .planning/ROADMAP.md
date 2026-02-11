# Roadmap: Polymarket eSports Smart Money Tracker

## Overview

This roadmap delivers an intelligence tool that identifies expert eSports traders on Polymarket, scores their specialization depth, and surfaces consensus signals when multiple experts converge on positions. The journey progresses through seven phases: establishing data infrastructure and taxonomy-driven classification, building historical evaluation and expertise scoring engines, detecting consensus signals while filtering herding behavior, and finally delivering alerts and CLI interfaces. Each phase builds upon the previous, culminating in a complete system that transforms raw Polymarket data into actionable intelligence about where informed eSports traders are moving.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Data collection and storage infrastructure
- [x] **Phase 2: Classification & Discovery** - Taxonomy system and trader identification
- [x] **Phase 3: Historical Evaluation** - Performance tracking and validation framework
- [x] **Phase 4: Scoring Engine** - Specialization depth and expertise calculation
- [x] **Phase 5: Signal Detection** - Consensus identification and herding filters
- [x] **Phase 6: Alerting System** - Multi-channel alert delivery
- [ ] **Phase 7: CLI Interface** - User commands and presentation layer

## Phase Details

### Phase 1: Foundation
**Goal**: Establish reliable data ingestion from Polymarket CLOB API and persistent local storage
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06
**Success Criteria** (what must be TRUE):
  1. System can fetch active eSports events and markets from Polymarket API without hitting rate limits
  2. System can retrieve complete trade histories for any trader address
  3. System persists market, trader, and position data in SQLite with proper indexing
  4. System filters trade history by date range and resolution status
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — Project scaffolding, configuration, and database schema
- [x] 01-02-PLAN.md — API client with rate limiting and retry (TDD)
- [x] 01-03-PLAN.md — Category filter and trade aggregation (TDD)
- [x] 01-04-PLAN.md — Ingestion pipeline and query layer

### Phase 2: Classification & Discovery
**Goal**: Classify markets into eSports taxonomy and identify active traders
**Depends on**: Phase 1
**Requirements**: TAXO-01, TAXO-02, TAXO-03, DATA-02
**Success Criteria** (what must be TRUE):
  1. System classifies Polymarket markets into game-level eSports categories using YAML taxonomy
  2. System discovers traders participating in active eSports markets from order books
  3. Adding a new eSports category requires only YAML changes, not code modification
  4. System tracks current open positions with size, direction, and entry price
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md — Taxonomy YAML schema, loader, and classifier (TDD)
- [x] 02-02-PLAN.md — Stateless position tracker (TDD)
- [x] 02-03-PLAN.md — DB models, classification pipeline, and trader discovery

### Phase 3: Historical Evaluation
**Goal**: Enable historical performance analysis with validation framework
**Depends on**: Phase 2
**Requirements**: PERF-01, PERF-02, PERF-03, PERF-04
**Success Criteria** (what must be TRUE):
  1. System calculates PnL, win rate, and total volume for each trader across multiple timeframes (7d, 30d, 90d, all-time)
  2. System identifies traders with consistent performance vs lucky streaks using cross-timeframe analysis
  3. System tracks market resolution states and excludes disputed/unresolved markets from performance metrics
  4. System provides out-of-sample validation framework for testing expertise scores on historical data
**Plans**: 5 plans

Plans:
- [x] 03-01-PLAN.md — Performance metrics: PnL, win rate, volume (TDD)
- [x] 03-02-PLAN.md — Timeframes and trader profiles (TDD)
- [x] 03-03-PLAN.md — Consistency detection: cross-timeframe stability (TDD)
- [x] 03-04-PLAN.md — DB models, time-windowed queries, and evaluation pipeline
- [x] 03-05-PLAN.md — Out-of-sample validation framework (TDD)

### Phase 4: Scoring Engine
**Goal**: Calculate specialization depth scores that identify domain experts
**Depends on**: Phase 3
**Requirements**: SCOR-01, SCOR-02, SCOR-03, SCOR-04, SCOR-05
**Success Criteria** (what must be TRUE):
  1. System produces 0-100 expertise scores per trader per eSports category incorporating concentration, win rate, sample size, and recency
  2. System enforces minimum sample size (5+ resolved markets in category) before assigning scores
  3. System applies recency weighting so recent performance counts more than old activity
  4. System generates ranked leaderboard of top traders per eSports niche
  5. Scores distinguish game-level specialists from generalists
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — Concentration metrics and specialization classification (TDD)
- [x] 04-02-PLAN.md — Composite expertise scoring engine (TDD)
- [x] 04-03-PLAN.md — DB models, leaderboard queries, and scoring pipeline

### Phase 5: Signal Detection
**Goal**: Detect expert consensus on markets with confidence scoring and first-mover tracking
**Depends on**: Phase 4
**Requirements**: SGNL-01, SGNL-02, SGNL-03, SGNL-04, SGNL-05
**Success Criteria** (what must be TRUE):
  1. System detects consensus when 3+ expert traders (score >70) take the same position with 75%+ supermajority
  2. System calculates 0-100 confidence score combining agreement %, sample size, and position sizes
  3. System provides herding assessment stub (deferred to future phase if needed)
  4. System surfaces markets ranked by expert activity in past 1/6/24 hours
  5. System distinguishes first movers from fast-followers in consensus detection
**Plans**: 3 plans

Plans:
- [x] 05-01-PLAN.md — Consensus detection and confidence scoring (TDD)
- [x] 05-02-PLAN.md — SignalSnapshot model and signal queries
- [x] 05-03-PLAN.md — Signal detection pipeline orchestration

### Phase 6: Alerting System
**Goal**: Deliver consensus signals via Telegram with retry reliability, signal event classification, and extended metadata
**Depends on**: Phase 5
**Requirements**: ALRT-01, ALRT-03, ALRT-04
**Success Criteria** (what must be TRUE):
  1. System sends consensus signal alerts to Telegram with market context, expert count, consensus direction, and confidence
  2. System classifies signal events as NEW, STRENGTHENING, WEAKENING, or LOST via snapshot comparison
  3. System retries failed alert deliveries with exponential backoff
  4. Alert payloads include complete signal metadata including first-mover identity, expert addresses, and position sizes
**Plans**: 3 plans

Plans:
- [x] 06-01-PLAN.md — Signal event detection via snapshot comparison (TDD)
- [x] 06-02-PLAN.md — Telegram HTML alert formatter with extended metadata (TDD)
- [x] 06-03-PLAN.md — Telegram client, delivery orchestration, and deduplication

### Phase 7: CLI Interface
**Goal**: Provide command-line tools for market exploration, trader analysis, and signal monitoring
**Depends on**: Phase 6
**Requirements**: CLI-01, CLI-02, CLI-03, CLI-04, CLI-05, POLL-01, POLL-02, POLL-03
**Success Criteria** (what must be TRUE):
  1. User can list active eSports markets with their taxonomy classification
  2. User can view detailed trader profiles including stats, scores, and position history
  3. User can view current consensus signals ranked by confidence score
  4. User can view ranked leaderboards of eSports experts per game niche
  5. User can trigger manual market sweeps and automated hourly polling runs
**Plans**: TBD

Plans:
- [ ] TBD during planning

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 4/4 | Complete | 2026-02-06 |
| 2. Classification & Discovery | 3/3 | Complete | 2026-02-06 |
| 3. Historical Evaluation | 5/5 | Complete | 2026-02-06 |
| 4. Scoring Engine | 3/3 | Complete | 2026-02-06 |
| 5. Signal Detection | 3/3 | Complete | 2026-02-07 |
| 6. Alerting System | 3/3 | Complete | 2026-02-11 |
| 7. CLI Interface | 0/TBD | Not started | - |
