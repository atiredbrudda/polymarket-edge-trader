# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-05)

**Core value:** Surface where smart money is moving in eSports markets so the user can see what informed traders are doing and factor that into their own thinking.
**Current focus:** Phase 2 - Classification & Discovery

## Current Position

Phase: 2 of 7 (Classification & Discovery)
Plan: 03 of 3 complete
Status: Phase 2 COMPLETE
Last activity: 2026-02-06 — Completed 02-03-PLAN.md (Niche Detection Integration)

Progress: [██░░░░░░░░] 20% (7/35 total plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 6.4 min
- Total execution time: 0.75 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 - Foundation | 4/4 | 30min | 7.5min |
| 2 - Classification & Discovery | 3/3 | 15min | 5min |

**Recent Trend:**
- Last 5 plans: 17min, 4min (02-01), 6min (02-02), 5min (02-03)
- Trend: Phase 2 consistently fast (5min avg), pure functions + TDD enable rapid iteration

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Event-first discovery approach: Start from active events to find traders, then backtrack their history (avoids scanning entire trader database)
- Custom taxonomy over Polymarket categories: Game-level granularity needed for niche detection (CS:GO vs LoL vs Dota 2)
- Hourly polling, not real-time: Awareness tool doesn't need sub-minute latency; reduces API pressure
- CLI + webhooks, no web UI: Prove signal quality first before investing in UI
- SQLite local-first storage: No external database infrastructure for v1
- **[01-01] Numeric columns for Decimal precision:** Use Numeric(20,6) for volumes, Numeric(10,6) for prices to avoid float errors
- **[01-01] SQLite WAL mode enabled:** Better write concurrency for data ingestion pipeline
- **[01-01] Category-agnostic data model:** detail_categories list configurable, no hardcoded eSports in business logic
- **[01-01] Virtual environment required:** Homebrew Python externally-managed, requires .venv/ activation
- **[01-02] Token bucket rate limiting:** Deque-based timestamp tracking with threading.Lock for thread safety
- **[01-02] Pydantic field validators:** Handle both ISO strings and Unix timestamps for dates
- **[01-02] Price validation range:** 0 < price < 1 (exclusive bounds) per Polymarket constraints
- **[01-02] Pagination cursor handling:** Terminates on next_cursor == 'LTE' or empty string
- **[01-03] Set-based category lookup:** O(1) case-insensitive category matching for filtering
- **[01-03] Decimal arithmetic:** All financial calculations use Decimal type to prevent float precision loss
- **[01-04] Event-first discovery:** Fetch active events → markets → discover traders from market trades
- **[01-04] Per-trader transactions:** Each trader ingestion commits independently to prevent cascade failures
- **[01-04] Multi-level deduplication:** Markets (condition_id), trades (trade_id), summaries (trader+category)
- **[01-04] Batch commit optimization:** Markets committed every 100 records for efficiency
- **[02-01] Cross-game team duplication:** Teams appear under multiple games separately for simpler path queries
- **[02-01] Deepest-match-wins classification:** Title matching multiple taxonomy levels returns deepest match for maximum specificity
- **[02-01] Context-aware dash detection:** Pattern \w+\s+-\s+\w+ matches team separators but avoids false positives
- **[02-01] Review flagging strategy:** Partial matches (game found, "vs" present, no team) flagged for taxonomy gaps
- **[02-02] Pure functions for position tracking:** Stateless calculation, no classes, easier to test and reason about
- **[02-02] Duck-typed trade input:** No SQLAlchemy imports, works with any object having right attributes
- **[02-02] Proportional cost basis reduction:** Partial closures maintain original weighted average entry price
- **[02-03] Taxonomy sync uses slug-based upsert:** Update if exists, insert if new - enables YAML updates without data loss
- **[02-03] Dual threshold enforcement (AND not OR):** 5+ trades AND $500+ volume both required to prevent noise
- **[02-03] Position upsert maintains all fields:** Refresh updates all computed fields, not just size/direction
- **[02-03] eSports filtering via slug prefix:** slug LIKE 'esports%' captures all taxonomy descendants efficiently

### Pending Todos

None yet.

### Blockers/Concerns

**Phase 1 (Foundation):**
- ✓ COMPLETE - All DATA requirements fulfilled (DATA-01 through DATA-06)
- ✓ API client, filters, ingestion pipeline, and query layer operational
- ✓ 62 tests passing across all foundation components

**Phase 2 (Classification & Discovery):**
- ✓ COMPLETE - All Phase 2 plans finished
- ✓ [02-01] YAML taxonomy system complete - 4 games, 40+ teams, pattern matching operational (18 tests)
- ✓ [02-02] Stateless position tracker complete - weighted average, entry timing, PnL calculation (21 tests)
- ✓ [02-03] Integration complete - taxonomy sync, classification pipeline, trader discovery (12 tests)
- Phase 2 tests: 51 (18 from 02-01, 21 from 02-02, 12 from 02-03)
- Total project tests: 113 (62 Phase 1 + 51 Phase 2)
- Ready for Phase 3 (Evaluation & Scoring)

**Phase 3-4 (Evaluation & Scoring):**
- Expertise score weighting: Formula coefficients require tuning via backtests on historical data
- Out-of-sample validation strategy needed to avoid overfitting
- Game patch tracking integration: Need reliable source for patch releases to tag markets with game versions
- Research flag: HIGH priority for scoring algorithm design

**Phase 5 (Signal Detection):**
- Consensus threshold calibration: 75% expert agreement is hypothesis, needs validation
- Herding detection timing thresholds: 2-hour window and 6-hour gaps are heuristics requiring historical validation
- Research flag: MEDIUM priority for threshold tuning

## Session Continuity

Last session: 2026-02-06
Stopped at: Completed 02-03-PLAN.md (Phase 2 complete: 113 tests passing)
Resume file: None
Next: Phase 3 planning (Evaluation & Scoring)
