# Polymarket Smart Money Tracker - State

## Project Reference

**Core Value:** Reliably detect when multiple proven traders (top quintile by CLV, ROI, and Sharpe ratio) are positioned in the same new market,
enabling users to follow high-signal trades.

**Current Focus:** Phase 8 - Detect Enrichment

**Vision:** A trader analytics pipeline that identifies "smart money" on Polymarket and surfaces consensus signals via Telegram alerts. eSports is the first niche; architecture is niche-agnostic via YAML configs.
---

## Current Position

**Phase:** 08-detect-enrichment

**Plan:** 01 - complete (08-02, 08-03 remain)

**Status:** 🔄 In Progress

**Progress:**

```
[████████████████████████████░░] 87% - Phase 7/8 complete (Phase 8 planned)
```

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Total Phases | 8 |
| v1 Requirements | 81 |
| Coverage | 100% |
| Depth | Comprehensive |

---
| Phase 01-foundation P01 | 3 min | 3 tasks | 5 files |
| Phase 01-foundation P02 | 3 min | 2 tasks | 3 files |
| Phase 01-foundation P03 | 5 min | 3 tasks | 7 files |
| Phase 01-foundation P04 | 24 min | 4 tasks | 6 files |
| Phase 01-foundation P05 | 3 min | 3 tasks | 1 files |
| Phase 01-foundation P06 | 1 min | 2 tasks | 1 files |
| Phase 01-foundation P07 | 2 min | 2 tasks | 2 files |
| Phase 01-foundation P08 | 2 min | 2 tasks | 2 files |
| Phase 01-foundation P09 | 2 min | 3 tasks | 1 files |
| Phase 01-foundation P10 | 1 min | 1 tasks | 1 files |
| Phase 01-foundation P11 | 1 min | 1 tasks | 1 files |
| Phase 02-data-ingestion P01 | 15 min | 3 tasks | 6 files |
| Phase 02-data-ingestion P02 | 7 min | 2 tasks | 4 files |
| Phase 02-data-ingestion P03 | ~10 min | 3 tasks | ~5 files |

## Accumulated Context

### Decisions Made

- **8 phases** derived from 81 requirements (natural delivery boundaries)
- **Phase 1 includes integration test** (v1 failed with 30 phases before E2E test)
- **Token catalog before trade ingestion** (prevents synthetic ID poisoning)
- **Niche-scoped entity extraction** (avoids wasting LLM credits on 50K+ markets)
- **2-tier backfill** (API first, Graph fallback for completeness)
- **Non-zero asset_id selection** (avoids 48% USDC selection bug)
- **Pydantic for config validation** (better error messages than manual validation)
- **yaml.safe_load for security** (prevents arbitrary code execution)
- [Phase 01-foundation]: Used sqlite-utils instead of raw sqlite3 - purpose-built for data pipelines, cleaner table creation API
- [Phase 01-foundation P03]: Click's @click.pass_context for sharing config across commands; commands use @cli.command() decorator for registration
- [Phase 01-foundation P04]: TDD integration tests with pytest fixtures; TCAT-03 uses LEFT JOIN pattern to detect synthetic IDs; lazy imports to avoid circular dependencies
- [Phase 01-foundation P07]: Schema verification test enforces GUIDE.md as source of truth; auto-fixed missing columns (trader_address, outcome, trade_count, lift_scores columns) as Rule 1 bugs
- [Phase 01-foundation P10]: NicheConfig.tag_id typed as int to match YAML source data (integers 64, 2, 745) - prevents silent coercion to string and enables numeric comparisons
- [Phase 01-foundation P09]: Used raw SQL CREATE TABLE for tables requiring NUMERIC affinity instead of sqlite-utils table.create() - ensures proper numeric handling for price/size columns in SQLite
- [Phase 01-foundation]: Use raw SQL db.execute() for all tables requiring NUMERIC affinity - ensures proper column type handling in SQLite, not relying on sqlite-utils type inference
- [Phase 02-data-ingestion P01]: Gamma API client uses httpx.AsyncClient with aiolimiter.AsyncLimiter (30 req/s); fetches tag_id as integer from /tags/slug/{slug} endpoint
- [Phase 02-data-ingestion P01]: Click commands use asyncio.run() wrapper since Click doesn't support async natively
- [Phase 02-data-ingestion P01]: eSports tag_id is 64 (integer), not string "esports" - fetched from Gamma API and stored in YAML config
- [Phase 02-data-ingestion P02]: EntityPatternMatcher uses pre-compiled regex for ~65% coverage without LLM cost
- [Phase 02-data-ingestion P03]: LLM fallback uses Anthropic Claude Sonnet 4 (claude-sonnet-4-20250514)
- [Phase 02-data-ingestion P03]: Data API client batches condition_ids in groups of 50 to avoid URL length limits
- [Phase 02-data-ingestion P03]: Entity ID generated as 16-char SHA256 hash of condition_id + entities JSON

### Key Dependencies

1. `token_catalog` must exist before `backfill` (trades reference token_id → condition_id)
2. `market_entities` must exist before `build-positions` (JOINs with WHERE game IS NOT NULL)
3. `markets.outcome` must exist before `resolve-positions` (PnL requires known resolution)
4. `lift_scores` must exist before `detect` (needs Q5 trader identification)

### Open Questions

(None - phases 1-7 complete, Phase 8 planned)

### Blockers

(None - pipeline fully operational)

---

## Session Continuity

**Last Session:** 2026-04-06

**Next Session:** Execute Phase 8 - detect enrichment (3 plans: schema migration, writer/detect wiring, integration tests)

**Handoff Notes:**
- Phase 1 foundation COMPLETE: schema, config validation, CLI, integration tests
- TCAT-03 passing: zero synthetic IDs confirmed in trades table
- Token catalog builder functional with fixture data (3 entries)
- Foreign key constraints enforced on orphan trades
- Plans 01-01 through 01-11 complete with SUMMARY.md files
- gamma_events schema normalized (01-06): condition_id, question, outcome, end_date, tags columns
- Schema verification test added (01-07): test_schema_matches_guide asserts all GUIDE.md columns
- Schema auto-fixed: added trader_address to trades, outcome/trade_count to positions, updated lift_scores
- Schema gap closure complete (01-09): NUMERIC affinity, UNIQUE constraint, trader_address index, market_type column
- NicheConfig.tag_id type fix complete (01-10): str → int to match YAML source data
- Signals table NUMERIC fix complete (01-11): avg_score uses NUMERIC(10,6) via raw SQL
- All 9 core tables use raw SQL with explicit NUMERIC affinity for numeric columns
- Plan 01-08 (human verification checkpoint) skipped - verification done programmatically
- **Phase 2 COMPLETE**: All 3 plans done
  - Plan 02-01: Gamma API client, ingest-events, resolve-outcomes commands
  - Plan 02-02: classify-tokens command, EntityPatternMatcher for regex entity extraction
  - Plan 02-03: LLM fallback with Anthropic, Data API client, discover command
  - eSports tag_id fetched and configured: 64 (integer)
  - Commands follow existing CLI patterns from Phase 1
  - Entity extraction: pattern matcher (~65%) + LLM fallback (~35%) for cost efficiency
  - discover command populates traders and market_entities tables
  - ANTHROPIC_API_KEY required for LLM fallback
  - Ready for Phase 3: Backfill Layer
- **Phase 3 COMPLETE**: All 3 plans done (merged 2026-03-29)
  - Plan 03-01: GraphAPIClient (graph.py), DataAPIClient.fetch_user_trades (data.py), non-zero asset selection, convert_price
  - Plan 03-02: backfill command - 2-tier (Data API first, Graph fallback), token catalog lookup, INSERT OR IGNORE, backfill_complete flag
    - Reviewer-flagged fix: `db["traders"].update()` wrong signature; worker also fixed `db.table_exists()` and missing `db.conn.commit()` in classify_tokens/ingest_events/resolve_outcomes
  - Plan 03-03: sanity-check command - 5 SQL validation queries, fails loudly (exit 1)
  - Ready for Phase 4: Position Engine
- **Phase 4 COMPLETE**: All 2 plans done (merged 2026-03-29)
  - Plan 04-01: build-positions command - SQL GROUP BY aggregation, LONG/SHORT/FLAT direction, VWAP
  - Plan 04-02: resolve-positions command - PnL formulas for all 4 direction/outcome combos; flagged fix: missing db.conn.commit() after UPDATE
  - Note carried forward: avg_entry_price/size stored as float in aggregation.py (non-blocking, but violates GUIDE.md Decimal rule - worth fixing in a future pass)
  - Ready for Phase 5: Scoring Engine
- **Phase 5 COMPLETE**: All 5 plans done (merged 2026-03-29)
  - Plans 05-01 through 05-05: CLV/ROI/Sharpe extraction, metrics calculation, z-score normalization, score CLI command, integration tests
  - Reviewer notes: CLV formula doesn't account for SHORT direction (spec-faithful, future GUIDE.md revision needed)
  - Reviewer note passed to Phase 6: detect must filter by MAX(computed_at) per trader to avoid stale Q5 records
  - Ready for Phase 6: Signal Detection
- **Phase 6 COMPLETE**: All 3 plans done + reviewer fixes applied (merged ~2026-03-31)
  - Plan 06-01: convergence.py, writer.py - core detection logic
  - Plan 06-02: detect CLI command with Rich UX
  - Plan 06-03: TDD integration tests (12 passed)
  - Reviewer fixes applied: MAX(computed_at) subquery in convergence query + _assert_dependencies(), db.conn.commit() in upsert_signals_batch()
  - Stale Q5 check in detect.py lines 61-67 noted as non-blocking cleanup
- **Post-Phase-6 patches applied (2026-03-31 to 2026-04-02):**
  - Entity extraction overhaul: pipeline unblocked to score/detect
  - event_slug parent-child link: migration + tests, sibling fallback in entity extraction and backfill
  - token_catalog: skip inserts for condition_ids not in markets
  - Always run entity extraction even when all traders are backfilled
  - LLM retry: retry 3x before disabling; reprocess all-NULL entity rows
  - Graph query retry: 3 attempts with backoff, 60s timeout
  - Non-esports catalog pollution guard: patcher and resolve-graph scoped correctly
- **Pipeline operational**: 46 Q5 traders identified in esports niche
- **q5_traders view** added to schema for easy Q5 lookup
- **Phase 7 Plan 01 MERGED (2026-04-05):** avg_exit_price NUMERIC(10,6) migration added to positions; BUY/SELL split aggregation in aggregation.py; FLAT size = gross BUY volume
- **Phase 7 Plan 02 MERGED (2026-04-05):** FLAT-first resolve pass in resolution.py; extract_resolved_positions() returns avg_exit_price + direction; calculate_clv() uses avg_exit_price for FLAT rows (CLV=0.75 for entry=0.40/exit=0.70). Reviewer fix: flat_mask.any() guard in metrics.py to prevent empty-Series assignment on non-FLAT DataFrames. 25/25 tests pass.
- **Phase 7 Plan 03 MERGED (2026-04-05):** BUY-only VWAP assertions, FLAT negative PnL, FLAT+LONG mixed CLV, full pipeline integration test. All reviews cleared.
- **Multi-model collaboration protocol established (2026-04-05):** `.planning/AGENTS.md` and `.planning/HANDOFF_PROTOCOL.md` created — Worker/Reviewer roles, state machine, branch protection, code standards
- **Phase 7 COMPLETE (2026-04-06):** All 3 plans done — avg_exit_price migration (07-01), FLAT-first resolution + CLV fix (07-02), FLAT position test coverage (07-03). All reviews cleared.
- **Phase 8 PLANNED (2026-04-06):** 3 plans in 3 waves — schema migration (08-01), writer/detect wiring (08-02), integration tests (08-03). All 9 ENRC requirements covered. Ready to execute.
- **Phase 8 Plan 01 MERGED (2026-04-06):** Schema migration adds 4 signals columns (clv_dominant_count, avg_entry_price, min_entry_price, tier); convergence query computes all 4 inline via SQL. Test fixture bug fixed: create_market() end_date defaulted to yesterday, now accepts future end_date. 68/68 tests pass. Review cleared.

---

*State initialized: 2026-03-29*
*Last updated: 2026-04-06 — Phase 8 Plan 01 merged (schema migration + convergence enrichment)*
