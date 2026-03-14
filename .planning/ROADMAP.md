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
- [ ] **Phase 19: Self-Healing Token Catalog** — Automatically detect and patch unclassifiable trades after every backfill run, ensuring no trade silently lacks game/category classification
- [ ] **Phase 20: eSports Token Gap Recovery** — Recover the 156 null-token eSports markets (3,633 trades, 1,451 traders) by fetching token IDs from Gamma Events API and hardening the ingest path that caused the gap

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
**Plans**: 2 plans
Plans:
- [ ] 15-01-PLAN.md — GammaEvent ORM model + GammaMarketClient bulk download method
- [ ] 15-02-PLAN.md — Persistence layer + polymarket ingest-events CLI command

### Phase 16: Market Outcome Resolution
**Goal**: Every resolved market in the database has `markets.outcome` populated, enabling PnL calculations in the scoring pipeline
**Depends on**: Phase 15
**Requirements**: RESOL-01, RESOL-02
**Success Criteria** (what must be TRUE):
  1. User can run a resolution command that populates `markets.outcome` for all markets linked to stored Gamma events
  2. Markets resolved as YES win have outcome encoded as `"YES"` (or the winning token ID); NO wins encoded as `"NO"`
  3. `markets.outcome` is NULL only for markets with genuinely unresolved or missing Gamma data — not as a default
  4. A summary is reported showing count of markets resolved vs. skipped
**Plans**: 2 plans
Plans:
- [ ] 16-01-PLAN.md — Resolution logic (TDD): determine_winner(), classify_token_outcome(), resolve_market_outcomes()
- [ ] 16-02-PLAN.md — polymarket resolve-outcomes CLI command wired to resolution logic

### Phase 17: Deep Token Classification
**Goal**: Token catalog entries carry `node_path` and `depth` at game, tournament, and team levels derived from Gamma event tags, enabling multi-depth expertise scoring to function correctly
**Depends on**: Phase 15
**Requirements**: CLASS-01, CLASS-02
**Success Criteria** (what must be TRUE):
  1. Token catalog entries previously stuck at `node_path=NULL` receive correct `node_path` values at game level (e.g., `esports/cs2`) or deeper
  2. Token catalog `depth` field reflects actual classification depth: 1 for game-level, 2 for tournament-level, 3 for team-level tokens
  3. Tokens linked to Gamma events with game + tournament + team tags receive `depth=3`; game-only tags receive `depth=1`
  4. Classification is verifiable — user can query a known token ID and see its resolved `node_path` and `depth`
**Plans**: 2 plans
Plans:
- [ ] 17-01-PLAN.md — Token classification logic (TDD) + classify-tokens CLI command
- [ ] 17-02-PLAN.md — Code quality cleanup: counter naming, dead code integration, idempotency test

### Phase 18: End-to-End Validation
**Goal**: The full scoring pipeline produces a non-empty leaderboard with correctly computed win rates and expertise scores on real JBecker data
**Depends on**: Phase 16, Phase 17
**Requirements**: E2E-01, E2E-02
**Success Criteria** (what must be TRUE):
  1. `score` command produces at least one expertise score row (non-empty output) when run on JBecker-backfilled trader data
  2. Leaderboard shows traders ranked by expertise score with win rates calculated from resolved market outcomes (not NULL)
  3. A trader known to have traded resolved eSports markets appears in the leaderboard with a plausible score
  4. No pipeline errors or empty-result aborts when resolution and classification data are present
**Plans**: 2 plans
Plans:
- [ ] 18-01-PLAN.md — TDD resolve_positions() function + resolve-positions CLI command
- [ ] 18-02-PLAN.md — Diagnostic + MarketClassification backfill + E2E score/leaderboard verification

### Phase 19: Self-Healing Token Catalog
**Goal**: After every backfill run, trades with no `token_catalog` entry are detected and patched automatically — first via local `gamma_events` join, then via Gamma API lookup — so no trade is permanently unclassifiable
**Depends on**: Phase 18
**Requirements**: CAT-01, CAT-02, CAT-03
**Success Criteria** (what must be TRUE):
  1. After `backfill` completes, any `trades.market_id` with no matching `token_catalog.condition_id` is detected automatically
  2. For eSports markets: game/tournament/team `node_path` is resolved via local `gamma_events` join (no API call needed when data exists locally)
  3. For markets not in `gamma_events`: a Gamma API lookup is attempted and results are persisted to `token_catalog`
  4. Non-eSports markets (Sports, Politics, etc.) are inserted into `token_catalog` with their correct category but no `node_path` — ensuring they are known, not silently invisible
  5. The existing 401-market backlog (10,850 trades) is patched on first run
  6. Running the patch step again is idempotent — no duplicate rows, no unnecessary API calls
**Plans**: 2 plans
Plans:
- [ ] 19-01-PLAN.md — 3-tier patch engine (TDD): src/catalog/patcher.py + 12 tests
- [ ] 19-02-PLAN.md — CLI wiring: patch-catalog command + backfill auto-hook (both paths)

### Phase 20: eSports Token Gap Recovery
**Goal**: All 156 null-token eSports markets have token IDs populated and are fully classified in `token_catalog` with correct `node_path`, so 3,633 previously unclassifiable trades are properly attributed to traders' eSports specialization scores
**Depends on**: Phase 19
**Requirements**: GAP-01, GAP-02, GAP-03
**Success Criteria** (what must be TRUE):
  1. A recovery script/command fetches eSports events from Gamma API by tag and extracts per-market `conditionId` + `clobTokenIds` for the 156 null-token gaps
  2. `markets.tokens` is populated for all recovered markets, enabling Tier 1 patcher to run
  3. Patcher successfully classifies all recoverable markets in `token_catalog` with correct `node_path`
  4. `ingest.py` populate-tokens block (~line 1777) is fixed to use events-based lookup instead of broken `?conditionId=` param — preventing recurrence
  5. After recovery, `leaderboard` scores reflect the 3,633 newly classified trades (traders' eSports specialization scores update)
  6. Zero eSports markets remain permanently stuck with `tokens=NULL` due to the broken ingest path
**Plans**: 2 plans
Plans:
- [ ] 20-01-PLAN.md — Events-based token recovery: fetch by tag, populate markets.tokens, re-run patcher
- [ ] 20-02-PLAN.md — Fix ingest.py populate-tokens block + re-score affected traders

### Phase 21: Market Entity Extraction

**Goal**: During `discover`, Claude API extracts {team_a, team_b, tournament, game, market_type} from each market's question text and stores entities per market in the `market_entities` table, normalized against taxonomy aliases
**Depends on:** Phase 20
**Requirements**: ENT-01, ENT-02, ENT-03, ENT-04, ENT-05
**Plans:** 2 plans

Plans:
- [ ] 21-01-PLAN.md — MarketEntity ORM model + LLM extraction function (src/extraction/llm_extractor.py)
- [ ] 21-02-PLAN.md — Taxonomy normalizer + wire extraction into discover command

### Phase 22: Org-Team Mapping

**Goal:** Build TraderTeamStats ORM model and query layer that joins positions to market_entities, computing per-team win/loss stats per trader. Wire into a `polymarket team-stats` CLI command. Establishes the LONG=team_a / SHORT=team_b direction convention for Phase 23.
**Requirements**: MAP-01, MAP-02, MAP-03, MAP-04, MAP-05, MAP-06, MAP-07
**Depends on:** Phase 21
**Plans:** 2 plans

Plans:
- [ ] 22-01-PLAN.md — TraderTeamStats ORM model + get_team_stats_for_trader() query function (TDD, MAP-01..MAP-06)
- [ ] 22-02-PLAN.md — polymarket team-stats CLI command + integration test (MAP-07)

### Phase 23: Contextual Analyze Command

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 22
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 23 to break down)

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
| 15. Gamma Events Ingestion | v1.2 | 0/2 | Planned | - |
| 16. Market Outcome Resolution | v1.2 | 0/2 | Planned | - |
| 17. Deep Token Classification | v1.2 | 0/2 | Planned | - |
| 18. End-to-End Validation | v1.2 | 0/2 | Not started | - |
| 19. Self-Healing Token Catalog | v1.2 | 0/2 | Planned | - |
| 20. eSports Token Gap Recovery | v1.2 | 0/2 | Not started | - |
| 21. Market Entity Extraction | v1.3 | 0/2 | Planned | - |
