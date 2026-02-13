# Roadmap: Polymarket Smart Money Tracker

## Overview

Category-agnostic intelligence pipeline that discovers expert niche traders on Polymarket, scores their specialization depth, and surfaces consensus signals. Architecture generalizes to any Polymarket category via taxonomy configuration.

## Milestones

- **v1.0 MVP** — Phases 1-9 (shipped 2026-02-13)
- **v1.1 Targeted Scanning & Deep Niche Scoring** — Phases 10-12 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-9) — SHIPPED 2026-02-13</summary>

- [x] Phase 1: Foundation (4/4 plans) — completed 2026-02-06
- [x] Phase 2: Classification & Discovery (3/3 plans) — completed 2026-02-06
- [x] Phase 3: Historical Evaluation (5/5 plans) — completed 2026-02-06
- [x] Phase 4: Scoring Engine (3/3 plans) — completed 2026-02-06
- [x] Phase 5: Signal Detection (3/3 plans) — completed 2026-02-07
- [x] Phase 6: Alerting System (3/3 plans) — completed 2026-02-11
- [x] Phase 7: CLI Interface (3/3 plans) — completed 2026-02-11
- [x] Phase 8: Blockchain History (2/2 plans) — completed 2026-02-11
- [x] Phase 9: JBecker Dataset (3/3 plans) — completed 2026-02-12

See `.planning/milestones/v1.0-ROADMAP.md` for full details.

</details>

### v1.1 Targeted Scanning & Deep Niche Scoring (In Progress)

**Milestone Goal:** Make the pipeline practical for daily use by narrowing market scanning to relevant niches with time filters, decoupling fast discovery from slow backfill, and extending scoring to tournament/team depth.

#### Phase 10: Targeted Market Scanning
**Goal**: User can scan specific niche categories and time windows instead of all markets
**Depends on**: Phase 9 (v1.0 complete)
**Requirements**: SCAN-01, SCAN-02, SCAN-03, SCAN-04
**Success Criteria** (what must be TRUE):
  1. User can specify one or more niche categories via CLI option (e.g., `--niche esports --niche crypto`)
  2. User can specify a time-to-close window to filter markets (e.g., `--closing-within 48h`)
  3. System fetches only markets matching niche and time filters from API (not client-side filtering)
  4. Pipeline ingests and processes only targeted markets, reducing API calls and processing time
**Plans**: 2 plans

Plans:
- [ ] 10-01-PLAN.md — TDD Gamma API client + duration parsing utilities
- [ ] 10-02-PLAN.md — Pipeline integration + CLI wiring (--niche, --closing-within)

#### Phase 11: Pipeline Decoupling
**Goal**: User can run address discovery and history backfill independently
**Depends on**: Phase 10
**Requirements**: PIPE-01, PIPE-02, PIPE-03, PIPE-04
**Success Criteria** (what must be TRUE):
  1. User can run address discovery command that finds traders without triggering history backfill
  2. User can run backfill command for previously discovered traders without re-discovering
  3. User can view which traders have been discovered but not yet backfilled via CLI status command
  4. System tracks backfill state per trader (discovered vs. backfilled) in database
**Plans**: 2 plans

Plans:
- [ ] 11-01-PLAN.md — TDD backfill state queries and index
- [ ] 11-02-PLAN.md — CLI commands (discover, backfill, status) and formatter

#### Phase 12: Deep Niche Scoring
**Goal**: System scores expertise at tournament and team level, not just game level
**Depends on**: Phase 9 (independent from Phase 10-11)
**Requirements**: DEEP-01, DEEP-02, DEEP-03, DEEP-04, DEEP-05
**Success Criteria** (what must be TRUE):
  1. System calculates expertise scores at game (depth 1), tournament (depth 2), and team (depth 3) levels
  2. User can view trader's expertise breakdown showing scores at all three taxonomy depths
  3. System identifies "hidden specialists" with high tournament/team scores despite average game scores
  4. Leaderboard supports filtering by any taxonomy depth (game, tournament, or team)
  5. User can discover niche experts (e.g., "Chelsea traders") who specialize at deep taxonomy levels
**Plans**: TBD

Plans:
- [ ] 12-01: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 4/4 | Complete | 2026-02-06 |
| 2. Classification & Discovery | v1.0 | 3/3 | Complete | 2026-02-06 |
| 3. Historical Evaluation | v1.0 | 5/5 | Complete | 2026-02-06 |
| 4. Scoring Engine | v1.0 | 3/3 | Complete | 2026-02-06 |
| 5. Signal Detection | v1.0 | 3/3 | Complete | 2026-02-07 |
| 6. Alerting System | v1.0 | 3/3 | Complete | 2026-02-11 |
| 7. CLI Interface | v1.0 | 3/3 | Complete | 2026-02-11 |
| 8. Blockchain History | v1.0 | 2/2 | Complete | 2026-02-11 |
| 9. JBecker Dataset | v1.0 | 3/3 | Complete | 2026-02-12 |
| 10. Targeted Market Scanning | v1.1 | 0/2 | Planned | - |
| 11. Pipeline Decoupling | v1.1 | 0/2 | Planned | - |
| 12. Deep Niche Scoring | v1.1 | 0/? | Not started | - |
