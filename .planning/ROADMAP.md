# Roadmap: Polymarket Smart Money Tracker

## Overview

Category-agnostic intelligence pipeline that discovers expert niche traders on Polymarket, scores their specialization depth, and surfaces consensus signals. Architecture generalizes to any Polymarket category via taxonomy configuration.

## Milestones

- ✅ **v1.0 MVP** — Phases 1-9 (shipped 2026-02-13)
- ✅ **v1.1 Targeted Scanning & Deep Niche Scoring** — Phases 10-14 (shipped 2026-02-21)
- 🚧 **v1.2 Market Resolution & Deep Classification** — Phases 15-18 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-9) — SHIPPED 2026-02-13</summary>

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

<details>
<summary>✅ v1.1 Targeted Scanning & Deep Niche Scoring (Phases 10-14) — SHIPPED 2026-02-21</summary>

- [x] Phase 10: Targeted Market Scanning (2/2 plans) — completed 2026-02-13
- [x] Phase 11: Pipeline Decoupling (2/2 plans) — completed 2026-02-14
- [x] Phase 12: Deep Niche Scoring (3/3 plans) — completed 2026-02-14
- [x] Phase 13: Esports Token Catalog & JBecker Classification (3/3 plans) — completed 2026-02-16
- [x] Phase 14: Timestamp Fix & Pipeline Decomposition (2/2 plans) — completed 2026-02-16

See `.planning/milestones/v1.1-ROADMAP.md` for full details.

</details>

### 🚧 v1.2 Market Resolution & Deep Classification (In Progress)

**Milestone Goal:** Integrate Gamma Events API data to fix the two critical v1.1 gaps — market outcome resolution and deep token classification — enabling the scoring pipeline to produce real leaderboard results end-to-end.

- [ ] **Phase 15: Gamma Events Ingestion** — Download and persist ~8,500 closed eSports events from Gamma API with full metadata
- [ ] **Phase 16: Market Outcome Resolution** — Populate `markets.outcome` for all resolved markets using stored Gamma event data
- [ ] **Phase 17: Deep Token Classification** — Enrich token catalog with game/tournament/team `node_path` from Gamma event tags
- [ ] **Phase 18: End-to-End Validation** — Verify the scoring pipeline produces a real leaderboard on JBecker data

## Phase Details

### Phase 15: Gamma Events Ingestion
**Goal**: Gamma Events API data is downloaded and persisted locally, providing the authoritative source for market resolution and deep classification
**Depends on**: Phase 14 (v1.1 complete)
**Requirements**: GAMMA-01, GAMMA-02
**Success Criteria** (what must be TRUE):
  1. User can run a single CLI command that downloads all ~8,500 closed eSports events from `gamma-api.polymarket.com/events` in ~30 seconds
  2. Downloaded events are persisted to the local database and survive process restart
  3. Stored event records include `clobTokenIds` (linking to markets), `outcomePrices` (winning side), and hierarchical tags (game/tournament/team slugs)
  4. Re-running the command is idempotent — no duplicate events created, existing data updated or skipped cleanly
**Plans**: TBD

### Phase 16: Market Outcome Resolution
**Goal**: Every resolved market in the database has `markets.outcome` populated, enabling PnL calculations in the scoring pipeline
**Depends on**: Phase 15
**Requirements**: RESOL-01, RESOL-02
**Success Criteria** (what must be TRUE):
  1. User can run a resolution command that populates `markets.outcome` for all markets linked to stored Gamma events
  2. Markets resolved as YES win have outcome encoded as `"YES"` (or the winning token ID); NO wins encoded as `"NO"`
  3. `markets.outcome` is NULL only for markets with genuinely unresolved or missing Gamma data — not as a default
  4. A summary is reported showing count of markets resolved vs. skipped
**Plans**: TBD

### Phase 17: Deep Token Classification
**Goal**: Token catalog entries carry `node_path` and `depth` at game, tournament, and team levels derived from Gamma event tags, enabling multi-depth expertise scoring to function correctly
**Depends on**: Phase 15
**Requirements**: CLASS-01, CLASS-02
**Success Criteria** (what must be TRUE):
  1. Token catalog entries previously stuck at `node_path=NULL` receive correct `node_path` values at game level (e.g., `esports/cs2`) or deeper
  2. Token catalog `depth` field reflects actual classification depth: 1 for game-level, 2 for tournament-level, 3 for team-level tokens
  3. Tokens linked to Gamma events with game + tournament + team tags receive `depth=3`; game-only tags receive `depth=1`
  4. Classification is verifiable — user can query a known token ID and see its resolved `node_path` and `depth`
**Plans**: TBD

### Phase 18: End-to-End Validation
**Goal**: The full scoring pipeline produces a non-empty leaderboard with correctly computed win rates and expertise scores on real JBecker data
**Depends on**: Phase 16, Phase 17
**Requirements**: E2E-01, E2E-02
**Success Criteria** (what must be TRUE):
  1. `score` command produces at least one expertise score row (non-empty output) when run on JBecker-backfilled trader data
  2. Leaderboard shows traders ranked by expertise score with win rates calculated from resolved market outcomes (not NULL)
  3. A trader known to have traded resolved eSports markets appears in the leaderboard with a plausible score
  4. No pipeline errors or empty-result aborts when resolution and classification data are present
**Plans**: TBD

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
| 10. Targeted Market Scanning | v1.1 | 2/2 | Complete | 2026-02-13 |
| 11. Pipeline Decoupling | v1.1 | 2/2 | Complete | 2026-02-14 |
| 12. Deep Niche Scoring | v1.1 | 3/3 | Complete | 2026-02-14 |
| 13. Esports Token Catalog | v1.1 | 3/3 | Complete | 2026-02-16 |
| 14. Timestamp Fix & Pipeline Decomp | v1.1 | 2/2 | Complete | 2026-02-16 |
| 15. Gamma Events Ingestion | v1.2 | 0/? | Not started | - |
| 16. Market Outcome Resolution | v1.2 | 0/? | Not started | - |
| 17. Deep Token Classification | v1.2 | 0/? | Not started | - |
| 18. End-to-End Validation | v1.2 | 0/? | Not started | - |
