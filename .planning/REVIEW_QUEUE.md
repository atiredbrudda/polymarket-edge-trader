# Review Queue

Worker adds an entry here when a plan is ready for review.
Reviewer moves it from Pending → Cleared (or Flagged) after checking.

---

## Pending Review

<!-- Worker adds entries here -->

### Pipeline Todo #3 - Incremental Mode for ingest_events — 2026-04-06
- **Branch:** worker/todo3-ingest-events-incremental
- **Todo:** .planning/todos/pending/2026-04-06-add-incremental-mode-to-ingest-events-skip-full-fetch-on-re-runs.md
- **Summary:** .planning/todos/done/2026-04-06-add-incremental-mode-to-ingest-events-skip-full-fetch-on-re-runs-SUMMARY.md
- **Commits:** Initial implementation
- **Files changed:**
  - `src/polymarket_analytics/commands/ingest_events.py` (MODIFIED) — adds `--full` flag, market count check, incremental vs full fetch logic
  - `tests/test_ingest_events_incremental.py` (NEW) — 4 tests: INCR-01 through INCR-04
- **Worker notes:** 
  - Implementation matches spec exactly
  - First run: `closed=None` (fetch all)
  - Re-run: `closed=False` (active only)
  - `--full` flag forces full fetch for recovery/resolution sweep
  - Accepted limitation: newly resolved markets won't appear in incremental fetch (user should run `--full` periodically)
- **Checklist:**
  - [x] Tests pass (source .venv/bin/activate && pytest) — 97/97 (4 new + 93 existing)
  - [x] Linter clean (ruff check src/ tests/) — test file clean, pre-existing issues in other files unchanged
  - [x] No debug artifacts, no cosmetic changes outside scope
  - [x] STATE.md NOT touched (reviewer-only)
  - [x] Plan SUMMARY.md written



---

## Flagged

<!-- Reviewer moves entries here if issues found. Worker fixes and re-adds to Pending. -->


---

## Cleared

### Pipeline Todo #2 - Timestamp-based Selective Re-fetch — **CLEARED 2026-04-06**
- **Branch:** worker/pipeline-todo-02-timestamps
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Tests:** pytest ✓ (93/93 — 6 new timestamp selection tests + 87 existing)
- **Files in scope:**
  - `src/polymarket_analytics/db/schema.py` — migration adds `last_backfilled_at` + `last_trade_seen_at` TEXT columns; migrates existing `backfill_complete=1` traders to prevent mass re-fetch on first run
  - `src/polymarket_analytics/commands/backfill.py` — timestamp-based selection query replaces boolean; ISO conversion for `last_trade_seen_at`; both timestamps updated after backfill
  - `tests/test_backfill_timestamps.py` (NEW) — 6 tests: NULL selection, recently-refreshed skip, recent-activity include, stale-trader skip, format conversion, ISO storage
- **Reviewer fix (round 1):** Flagged `last_trade_seen_at` type mismatch — Unix int stored in TEXT column compared against ISO datetime string. Worker fixed with `isinstance(int)` guard + `datetime.fromtimestamp(...).isoformat()`.
- **Notes:** Fix is correct and targeted. Minor: `test_db` fixture injected but unused in test signatures — harmless. No reviewer fixes required this round. **Ready to merge.**

### Phase 08 Plan 03 - Enrichment Test Coverage — **CLEARED 2026-04-06**
- **Branch:** worker/08-detect-enrichment-p03
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Tests:** pytest ✓ (87/87 pass; 9 new enrichment tests all passing)
- **Files in scope:**
  - `tests/test_enrichment.py` (NEW) — 9 integration tests covering all ENRC requirements
  - `tests/test_scoring_extraction.py` (MODIFIED) — added `avg_exit_price` to expected columns in `test_extract_empty_result_no_crash`
- **Reviewer fix:** `test_scoring_extraction.py` line 235 — worker identified the pre-existing Phase 07 regression correctly but failed to include the fix in the commit. Added `"avg_exit_price"` to expected_columns list. One line, 477bb0c.
- **Notes:** All 9 enrichment tests match PLAN.md spec exactly. Logic correct: clv_dominant_count scoped to Q5 traders with positive zscore, tier thresholds ACT/CONSIDER/WATCH verified, entry price AVG/MIN correct, full round-trip passes. **Ready to merge.**

### Phase 08 Plan 02 - Writer/Detect Wiring — **CLEARED 2026-04-06**
- **Branch:** worker/08-detect-enrichment-p02
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Tests:** pytest ✓ (68/68 pass)
- **Files in scope:**
  - `src/polymarket_analytics/detection/writer.py` — 4 new optional params (None defaults), INSERT/UPDATE SQL updated, batch extraction with `in row` + `pd.isna()` guards
  - `src/polymarket_analytics/commands/detect.py` — docstring only
- **Reviewer notes:** Clean pass. None defaults preserve all 12 existing detection tests. Column-existence guards in batch function handle old DataFrames. avg_score retained per ENRC-09. No reviewer fixes required. **Merged to main.**

### Phase 08 Plan 01 - Schema Migration + Convergence Enrichment — **CLEARED 2026-04-06**
- **Branch:** worker/08-detect-enrichment-p01
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Tests:** pytest ✓ (68/68 pass)
- **Files in scope:**
  - `src/polymarket_analytics/db/schema.py` — migration-safe ALTER TABLE adds 4 signals columns
  - `src/polymarket_analytics/detection/convergence.py` — 4 new fields computed inline in SQL
  - `tests/conftest.py` — create_market() accepts optional end_date (backwards-compatible)
  - `tests/test_detection.py` — future_end_date fixture
- **Reviewer notes:** Clean pass. clv_dominant_count correctly scoped to Q5 traders. MIN/AVG entry price scoped by direction via GROUP BY. MAX(computed_at) subquery intact. No reviewer fixes required. **Merged to main via worker/08-detect-enrichment-p02.**

### Phase 07 Plan 03 - FLAT Position Test Coverage — **CLEARED 2026-04-05**
- **Branch:** worker/07-flat-position-tracking-p02
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Commits:** 030145a..4b77a62
- **Tests:** pytest ✓ (42/42 pass; 8 new FLAT tests all passing)
- **Files in scope:**
  - `tests/test_build_positions.py` — 2 new tests: BUY-only VWAP assertion (entry=0.40), LONG entry ignores SELL prices
  - `tests/test_resolve_positions.py` — 2 new tests: FLAT negative PnL (pnl=-20.0/outcome='LOSS'), FLAT-first pass skips NULL avg_exit_price (market-outcome path resolves to pnl=0/'FLAT')
  - `tests/test_scoring_metrics.py` — 2 new tests: mixed FLAT+LONG CLV (0.75 and 0.667 independently), missing direction column backward compat
  - `tests/test_integration.py` — 1 new test: full pipeline FLAT trader CLV≈0.75 (build→resolve→extract→score); schema assertion for avg_exit_price
- **Reviewer notes:** Clean pass. All 8 new tests match plan spec exactly. `test_resolve_flat_loss` count==2 assertion is correct (LONG decoy + FLAT both resolved in same pass). 2026-04-04 timestamp in integration test correctly within 30-day window. No reviewer fixes required.

### Phase 07 Plan 02 - FLAT-First Resolution + CLV Fix — **CLEARED 2026-04-05**
- **Branch:** worker/07-flat-position-tracking-p02
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Commits:** a62e476..030145a
- **Tests:** pytest ✓ (25/25 pass across test_resolve_positions, test_scoring_metrics, test_scoring_integration)
- **Files in scope:**
  - `src/polymarket_analytics/positions/resolution.py` — FLAT-first UPDATE pass, relaxed dependency checks, `calculate_pnl()` optional avg_exit_price
  - `src/polymarket_analytics/scoring/extraction.py` — adds `avg_exit_price` to SELECT and fallback columns
  - `src/polymarket_analytics/scoring/metrics.py` — CLV uses avg_exit_price for FLAT; reviewer added `flat_mask.any()` guard
  - `tests/test_resolve_positions.py` — 3 new tests (FLAT resolve, calculate_pnl FLAT)
  - `tests/test_scoring_metrics.py` — 1 new test (CLV=0.75 for FLAT trader)
  - `tests/test_scoring_integration.py` — avg_exit_price added to expected columns
- **Reviewer fix:** `metrics.py` — added `if flat_mask.any():` guard before `df.loc[flat_mask, "resolution_price"] = df.loc[flat_mask, "avg_exit_price"]`. Without this, assigning an empty object Series to a float64 column raises TypeError on older pandas when no FLAT rows exist. Worker misidentified 3 integration test failures as pre-existing.
- **Notes:** Implementation matches spec exactly. FLAT-first order correct (resolved=0 guard in market-outcome UPDATE handles exclusion). CLV formula clean.

### Phase 07 Plan 01 - avg_exit_price Schema + BUY/SELL Split Aggregation — **CLEARED 2026-04-05**
- **Branch:** worker/07-flat-position-tracking-p01
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Merge commit:** 30aaecb
- **Tests:** pytest ✓ (56/56 pass; 1 pre-existing detection test failure unrelated to this plan)
- **Files in scope:**
  - `src/polymarket_analytics/db/schema.py` — idempotent migration adds avg_exit_price NUMERIC(10,6) to positions
  - `src/polymarket_analytics/positions/aggregation.py` — BUY/SELL split VWAP, gross_buy_size, FLAT size override
- **Notes:** Clean implementation. SQL correct (NULLIF zero-guard on both VWAPs). Migration mirrors existing pattern exactly. Non-blocking: pre-existing `test_convergence_detection_basic` failure to address in Plan 07-03; pre-existing sqlite-utils upsert (INSERT OR REPLACE semantics) safe for now but watch if positions table gains auto-populated columns.

### Phase 06 Plan 03 - Signal Detection TDD Tests - **CLEARED ~2026-03-31**
- **Branch:** gsd/phase-06-signal-detection
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Reviewer fixes applied:**
  - Stale Q5 check in detect.py (lines 61-67, no MAX filter) cleaned up per reviewer note
- **Tests:** pytest ✓ (12 passed)
- **Files in scope:**
  - `tests/test_detection.py` - 12 integration tests for convergence detection

### Phase 06 (Plans 01+02) - Signal Detection - **CLEARED 2026-03-29**
- **Branch:** gsd/phase-06-signal-detection
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Round 2** - both flagged issues confirmed fixed:
  - convergence.py: MAX(computed_at) subquery added to convergence query ✓
  - convergence.py: _assert_dependencies() Q5 check also uses MAX(computed_at) ✓
  - writer.py: db.conn.commit() added at end of upsert_signals_batch() ✓
- **Reviewer note:** detect.py still has a stale Q5 check (lines 61-67, no MAX filter) that is now superseded by _assert_dependencies(). Not blocking - behavior is correct end-to-end - but worth cleaning up.
- **Files in scope:**
  - `src/polymarket_analytics/detection/convergence.py`
  - `src/polymarket_analytics/detection/writer.py`
  - `src/polymarket_analytics/detection/__init__.py`
  - `src/polymarket_analytics/commands/detect.py`
  - `src/polymarket_analytics/commands/__init__.py`

### Phase 05 (5 plans) - Scoring Engine - **CLEARED 2026-03-29**
- **Branch:** gsd/phase-05-scoring-engine
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Reviewer fixes required:** None
- **Files in scope:**
  - `src/polymarket_analytics/scoring/extraction.py` - SQL window query, niche JOIN, last_trade_timestamp
  - `src/polymarket_analytics/scoring/metrics.py` - CLV, ROI, Sharpe calculations
  - `src/polymarket_analytics/scoring/normalization.py` - z-scores, composite, quintile assignment
  - `src/polymarket_analytics/scoring/writer.py` - lift_scores upsert via sqlite-utils
  - `src/polymarket_analytics/commands/score.py` - CLI command, dependency assertions, pipeline orchestration
  - `tests/test_scoring_extraction.py` - 4 tests
  - `tests/test_scoring_metrics.py` - 13 tests
  - `tests/test_scoring_normalization.py` - 12 tests
  - `tests/test_scoring_integration.py` - 4 integration tests (48 total suite)
- **Notes:**
  - All formulas match GUIDE.md spec. Dependency assertions loud and correct. Niche scoping via JOIN correct. min_positions applied after z-scores per spec.
  - **Note for Phase 6 plan:** `window_end = datetime.now()` means each `score` run appends NEW lift_scores rows (not update). detect must filter by `MAX(computed_at)` or `MAX(window_end)` per trader to get current scores only - otherwise stale Q5 records will generate ghost signals.
  - **Known design gap (not blocking):** CLV formula doesn't account for SHORT direction - winning SHORT bets get negative CLV. Spec-faithful (GUIDE.md doesn't specify direction-aware CLV). Noted for future GUIDE.md revision.

### Phase 04 (2 plans) - Position Engine - **CLEARED 2026-03-29**
- **Branch:** gsd/phase-04-position-engine
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Notes:**
  - Plan 01 (build-positions): clean first pass
  - Plan 02 (resolve-positions): flagged for missing `db.conn.commit()` after `db.execute(UPDATE)` - fixed correctly. Non-blocking note about `float` vs `Decimal` in aggregation.py not addressed (acceptable, not a hard requirement this phase).
- **Files in scope:**
  - `src/polymarket_analytics/positions/aggregation.py` - build_positions_from_trades, direction logic, VWAP
  - `src/polymarket_analytics/positions/resolution.py` - resolve_position_pnl, calculate_pnl helper, db.conn.commit() fix
  - `src/polymarket_analytics/commands/build_positions.py` - CLI command
  - `src/polymarket_analytics/commands/resolve_positions.py` - CLI command
  - `tests/test_build_positions.py` - 5 tests: aggregation, direction, VWAP, fail-without-entities, idempotency
  - `tests/test_resolve_positions.py` - 5 tests: all 4 PnL formulas, Python helper, skip-unresolved, idempotency, fail-without-outcomes

### Phase 03 (3 plans) - Trade Backfill - **CLEARED 2026-03-29**
- **Branch:** gsd/phase-03-trade-backfill
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Notes:**
  - Plan 01 (graph.py + data.py): clean first pass
  - Plan 02 (backfill.py): flagged for `db["traders"].update()` wrong signature; worker also proactively fixed `db.table_exists()` (doesn't exist in sqlite-utils) and missing `db.conn.commit()` after `db.execute()` in classify_tokens/ingest_events/resolve_outcomes - all three confirmed correct and necessary
  - Plan 03 (sanity_check.py): clean first pass
- **Files in scope:**
  - `src/polymarket_analytics/api/graph.py` - GraphAPIClient, select_asset_id, convert_price, parse_graph_event
  - `src/polymarket_analytics/api/data.py` - fetch_user_trades, 20 req/s limiter
  - `src/polymarket_analytics/commands/backfill.py` - 2-tier backfill with correct update() call
  - `src/polymarket_analytics/commands/sanity_check.py` - 5 SQL validation checks
  - `src/polymarket_analytics/commands/classify_tokens.py` - table_exists fix + commit fix
  - `src/polymarket_analytics/commands/ingest_events.py` - commit fix
  - `src/polymarket_analytics/commands/resolve_outcomes.py` - commit fix
  - `src/polymarket_analytics/db/schema.py` - idx_trades_trader + idx_trades_trader_market indexes

### Phase 2 - Data Ingestion Layer (3 plans) - **CLEARED 2026-03-29**
- **Branch:** gsd/phase-02-data-ingestion
- **Cleared by:** Reviewer (Claude Sonnet 4.6)
- **Reviewer fixes required:** None - worker correctly addressed all Round 2 blockers.
- **Files in scope:**
  - `src/polymarket_analytics/commands/ingest_events.py` - reads `result`/`winner` for resolution
  - `src/polymarket_analytics/commands/classify_tokens.py` - reads `clobTokenIds`, handles JSON string, warns on synthetic fallback
  - `src/polymarket_analytics/commands/resolve_outcomes.py` - `result.rowcount` + `AND outcome IS NOT NULL` guard
  - `src/polymarket_analytics/api/gamma.py` - pagination, rate limiting (30 req/s)
  - `src/polymarket_analytics/db/schema.py` - 9 tables, WAL mode, NUMERIC affinity, FK enforcement
  - `tests/test_integration.py` - 5 tests: TCAT-03, TCAT-04, schema, FK, ingestion
- **Notes:** Critical token ID bug resolved - `classify_tokens` now reads `clobTokenIds` from Gamma API, which maps to real Polymarket token IDs. `resolve_outcomes` no longer marks closed-but-unresolved markets as resolved. TCAT-04 validates the API path with a mock. 5/5 tests pass.

---

## Entry Format

```
### Phase X Plan Y - short description
- **Branch:** worker/XX-description
- **Plan:** .planning/phases/XX-name/XX-0Y-PLAN.md
- **Summary:** .planning/phases/XX-name/XX-0Y-SUMMARY.md
- **Tests:** pytest ✓ (N passed)
- **Ready:** YYYY-MM-DD
```
