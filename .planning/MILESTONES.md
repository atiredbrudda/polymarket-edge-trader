# Milestones

## v1.2 Market Resolution & Deep Classification (Shipped: 2026-03-22)

**Phases completed:** 11 phases (15-25), 21 plans
**Timeline:** 29 days (2026-02-22 → 2026-03-22)
**Codebase:** ~39,673 LOC Python (19,100 src + 20,573 tests), 109 commits, 56 files changed

**Key accomplishments:**
1. Gamma Events API integration — bulk download of ~8,500 closed eSports events with clobTokenIds, outcomePrices, and hierarchical tags
2. Market outcome resolution — `markets.outcome` populated for all resolved markets, enabling real PnL calculations
3. Deep token classification — token catalog enriched with game/tournament/team `node_path` from Gamma event tags
4. Self-healing token catalog — 3-tier auto-patcher (local join → API lookup → category-only) detects and fixes unclassifiable trades after every backfill
5. eSports token gap recovery — 156 null-token markets recovered (3,633 trades), ingest.py populate-tokens block fixed
6. Entity-level intelligence — LLM extracts teams/tournaments from market questions during discover; per-team win rates computed via TraderTeamStats
7. Lift-based scoring v2 — replaced old composite scoring with backtest-validated z(CLV)+z(ROI)+z(Sharpe) formula; signal detection rewired to Q5 filtering

**Delivered:** Closed the two critical v1.1 gaps (market resolution + deep classification), then built entity-level intelligence (team/tournament extraction and per-team win rates) and replaced the original scoring engine with a backtest-validated lift-based formula. The pipeline now produces real leaderboard results end-to-end.

**Known Gaps:**
- 8 phases missing VERIFICATION.md (Nyquist non-compliant — code works, paperwork skipped)
- EntityAlpha model/functions from Phase 23 are dead code (superseded by Phase 25 lift-based analyze)
- Old `compute_game_scores`/`compute_all_game_scores`/`compute_taxonomy_scores` preserved but uncalled
- 158 null-token catalog gaps remain unfixable (markets with `tokens=NULL` in DB)
- ANALYZE-01..07 requirements superseded by LIFT-03

---

## v1.0 MVP (Shipped: 2026-02-13)

**Phases completed:** 9 phases, 29 plans
**Timeline:** 8 days (2026-02-05 → 2026-02-12)
**Codebase:** 26,306 LOC Python, 163 commits, 226 files

**Key accomplishments:**
1. Polymarket CLOB API integration with rate limiting, pagination, and 4-tier data ingestion (JBecker/API/Graph/Blockchain)
2. YAML-driven taxonomy classification for eSports markets (game/tournament/team depth)
3. Historical evaluation engine with PnL, win rate, consistency detection, and out-of-sample validation
4. Composite expertise scoring (0-100) with concentration, recency, and percentile normalization
5. Expert consensus signal detection with confidence scoring and first-mover tracking
6. Telegram alerting with event classification (NEW/STRENGTHENING/WEAKENING/LOST) and dedup
7. Full CLI interface with polling loop, leaderboards, trader profiles, and offline research via JBecker dataset

**Delivered:** Category-agnostic intelligence pipeline that discovers expert niche traders on Polymarket, scores their specialization depth, and surfaces consensus signals. eSports validated as first case study.

---


## v1.1 Targeted Scanning & Deep Niche Scoring (Shipped: 2026-02-21)

**Phases completed:** 14 phases, 41 plans (phases 10–14, incremental on v1.0's 9 phases)
**Timeline:** 8 days (2026-02-13 → 2026-02-21)
**Codebase:** ~32,065 LOC Python (15,400 src + 16,665 tests), 121 commits

**Key accomplishments:**
1. Targeted market scanning — `--niche` and `--closing-within` CLI options filter markets at API level (SCAN-01–04)
2. Pipeline decoupling — separate `discover` and `backfill` commands with per-trader state tracking (PIPE-01–04)
3. Multi-depth scoring — expertise scores at game (depth 1), tournament (depth 2), and team (depth 3) levels (DEEP-01–05)
4. Hidden specialist detection — identifies traders with average game scores but high sub-niche concentration
5. JBecker token catalog — 817k-row catalog bridges JBecker trade token IDs to taxonomy without Gamma API lookups
6. Timestamp fix + pipeline decomposition — `score`, `detect`, `alert` commands replace monolithic `sweep`; block_number timestamp resolution fixed

**Delivered:** Made the pipeline practical for daily use with niche-filtered scanning, decoupled discovery/backfill operations, full tournament/team-depth expertise scoring, and a JBecker token catalog enabling offline classification at scale.

**Known gaps recorded at completion:**
- Token catalog entries have `node_path=NULL` / `depth=NULL` — classification only reaches eSports root, not game/tournament/team depth
- Market outcome resolution missing — `markets.outcome=NULL` for all 117k markets; positions can't be resolved for PnL scoring
- Root cause: catalog builder uses Gamma Events API tag filtering (tag_id=64) which returns esports events but doesn't deep-classify them; PatternMatcher covers only 4 games with limited regex patterns

---

