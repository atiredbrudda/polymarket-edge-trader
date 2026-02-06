---
phase: 02-classification-discovery
plan: 03
subsystem: database, pipeline
tags: [sqlalchemy, taxonomy, pattern-matching, position-tracking, trader-discovery]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: Database models, session management, ingestion pipeline
  - phase: 02-01
    provides: YAML taxonomy system, PatternMatcher, detect_market_type
  - phase: 02-02
    provides: Stateless position tracker with calculate_position and calculate_pnl

provides:
  - TaxonomyNode, MarketClassification, and Position database models
  - ClassificationPipeline for syncing taxonomy to DB and classifying markets
  - discover_esports_traders with dual thresholds (5+ trades AND $500+ volume)
  - compute_and_store_positions for position persistence
  - refresh_all_positions for batch position updates

affects: [03-evaluation-scoring, 04-signal-detection, 05-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Taxonomy sync: YAML → DB upsert for queryable hierarchy"
    - "Classification pipeline: Pattern matching → TaxonomyNode lookup → MarketClassification persistence"
    - "Trader discovery: SQL joins (trades → classifications → nodes) with HAVING clause thresholds"
    - "Position upsert: Check existing → update or insert with same fields"

key-files:
  created:
    - src/pipeline/classify.py
    - src/discovery/trader_discovery.py
    - tests/test_classify_pipeline.py
    - tests/test_discovery.py
  modified:
    - src/db/models.py
    - src/config/settings.py

key-decisions:
  - "Taxonomy sync uses slug-based upsert (update if exists, insert if new)"
  - "Trader discovery requires BOTH thresholds (5+ trades AND $500+ volume, not OR)"
  - "Position upsert maintains all fields (size, direction, avg_entry_price, timestamps)"
  - "eSports filtering uses slug.like('esports%') for all taxonomy descendants"

patterns-established:
  - "Classification pipeline: sync → classify → persist in batches of 100"
  - "Trader discovery: join-based filtering via market_classifications table"
  - "Position computation: pure function calculate_position → ORM persistence"

# Metrics
duration: 5min
completed: 2026-02-06
---

# Phase 02 Plan 03: Niche Detection Integration Summary

**Database models for taxonomy/classification/positions, pipeline integration with 5+ trade AND $500+ volume thresholds, 113 tests passing**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-06T04:26:09Z
- **Completed:** 2026-02-06T04:31:43Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- TaxonomyNode, MarketClassification, and Position models with proper indexes and foreign keys
- ClassificationPipeline syncs YAML taxonomy to DB and classifies markets with review flagging
- Trader discovery enforces dual thresholds: 5+ trades AND $500+ volume (both required)
- Position computation integrates calculate_position from position_tracker with database persistence
- All 113 tests pass (101 existing + 12 new integration tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DB models and configuration** - `4970ee2` (feat)
   - TaxonomyNode model with slug, depth, parent_id, patterns_json
   - MarketClassification model linking markets to taxonomy nodes
   - Position model for computed trader positions
   - New settings: taxonomy_path, trader_min_trades, trader_min_volume

2. **Task 2: Build classification pipeline and trader discovery** - `ebff492` (feat)
   - ClassificationPipeline: sync_taxonomy_to_db, classify_market, classify_all_markets
   - discover_esports_traders with join-based filtering and HAVING thresholds
   - compute_and_store_positions with position upsert logic
   - refresh_all_positions for batch updates
   - 12 integration tests (5 pipeline + 7 discovery)

**Plan metadata:** (pending - to be committed)

## Files Created/Modified

- `src/db/models.py` - Added TaxonomyNode, MarketClassification, Position models with indexes
- `src/config/settings.py` - Added taxonomy_path, trader_min_trades, trader_min_volume settings
- `src/pipeline/classify.py` - ClassificationPipeline with taxonomy sync and market classification
- `src/discovery/trader_discovery.py` - Trader discovery and position computation functions
- `tests/test_classify_pipeline.py` - 5 tests for taxonomy sync and classification pipeline
- `tests/test_discovery.py` - 7 tests for trader discovery thresholds and position storage

## Decisions Made

**1. Slug-based taxonomy upsert**
- Rationale: Enables taxonomy updates without losing DB data
- Implementation: Query by slug, update if found, insert if new
- Benefit: Taxonomy YAML changes sync cleanly to existing DB

**2. Dual threshold enforcement (AND not OR)**
- Rationale: Prevents noise from casual traders (many small bets) or one-off whales (single large bet)
- Implementation: HAVING clause with both count(distinct trade_id) >= 5 AND sum(size * price) >= 500
- Benefit: Higher signal quality for niche trader detection

**3. Position upsert maintains all fields**
- Rationale: Position refresh should update all computed fields, not just size/direction
- Implementation: Check for existing position, update all fields if found, insert if new
- Benefit: Positions always reflect current state, no drift from partial updates

**4. eSports filtering via slug prefix**
- Rationale: Simple and efficient way to match all taxonomy descendants
- Implementation: WHERE slug LIKE 'esports%' captures root, games, tournaments, teams
- Benefit: No need for recursive CTE or multiple joins for hierarchical filtering

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**1. SQLAlchemy DetachedInstanceError in test**
- Issue: Accessing market.condition_id outside session context
- Resolution: Access market_id directly as string literal instead of via detached ORM object
- Impact: Test pattern clarified for future integration tests

**2. Trader E volume calculation**
- Issue: Test expected $600 volume but trades computed to $300 (6 trades × 100 size × 0.5 price)
- Resolution: Increased size from 100 to 200 per trade to reach $600 total
- Impact: Test data now matches expected thresholds

Both issues were minor test data/assertion fixes, not implementation bugs.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Phase 2 Complete:**
- Taxonomy classification operational (YAML → DB → pattern matching)
- Position tracking operational (trade history → weighted average → persistence)
- Trader discovery operational (dual thresholds → qualified trader list)
- 113 tests passing (62 Phase 1 + 39 Phase 2 + 12 integration)

**Ready for Phase 3 (Evaluation & Scoring):**
- Traders can be discovered via discover_esports_traders()
- Positions can be computed via compute_and_store_positions()
- Market classifications available via MarketClassification table
- All necessary data models in place for expertise scoring

**No blockers.** Phase 2 complete with all success criteria met.

---
*Phase: 02-classification-discovery*
*Completed: 2026-02-06*
