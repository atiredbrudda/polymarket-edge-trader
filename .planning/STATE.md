# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-05)

**Core value:** Surface where smart money is moving in eSports markets so the user can see what informed traders are doing and factor that into their own thinking.
**Current focus:** Phase 7 - CLI Interface

## Current Position

Phase: 6 of 7 (Alerting System)
Plan: 3 of 3 complete
Status: Phase 6 complete
Last activity: 2026-02-11 — Plan 06-03 complete (Telegram bot integration & delivery pipeline)

Progress: [█████░░░░░] 57% (21/37 total plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 21
- Average duration: 4.78 min
- Total execution time: 1.67 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 - Foundation | 4/4 | 30min | 7.5min |
| 2 - Classification & Discovery | 3/3 | 15min | 5min |
| 3 - Historical Evaluation | 5/5 | 19.45min | 3.89min |
| 4 - Scoring Engine | 3/3 | 13.4min | 4.47min |
| 5 - Signal Detection | 3/3 | 16min | 5.33min |
| 6 - Alerting System | 3/3 | 14.71min | 4.90min |

**Recent Trend:**
- Last 5 plans: 4.5min (05-02), 6min (05-03), 5.5min (06-01), 3.83min (06-02), 5.38min (06-03)
- Trend: TDD + pure functions consistently fast (3.8-6min), Phase 6 complete at 4.90min average
- Phase 6 COMPLETE: All 3 plans done - signal detection, formatting, Telegram integration

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
- **[03-01] Voided market exclusion:** Voided markets excluded from all metrics calculations per resolution handling rules
- **[03-01] Win rate returns None for no data:** Distinguishes "no positions" from "0% win rate" for downstream logic
- **[03-01] Mark-to-market unrealized PnL:** Unresolved positions valued at current market price, flagged as unrealized
- **[03-02] Rolling windows from current time:** 7d/30d/90d windows calculated from current time, not calendar periods
- **[03-02] Classification by unique markets:** Selective vs active based on unique markets entered, not trade count (50 trades on 3 markets = selective)
- **[03-02] Profile-specific consistency bars:** Selective traders get looser variance (100), active traders tighter (50) per data volume
- **[03-03] 7d window excluded from consistency:** Too noisy for meaningful cross-timeframe comparison, only 30d/90d/all used
- **[03-03] Sparse threshold: 5 resolved markets:** Minimum for statistical confidence, windows with < 5 flagged as low-confidence
- **[03-03] Alternation rate threshold: 0.4:** >= 0.4 is alternating (consistent), < 0.4 is clustered (streaky)
- **[03-04] Grace period for resolved positions: 4 hours:** 2x UMA 2-hour challenge period for safety
- **[03-04] Composite unique index on (trader_address, timeframe):** Enables efficient PerformanceSnapshot upsert operations
- **[03-04] Chronological outcome ordering (ASC):** For streak analysis vs DESC for recent positions display
- **[03-05] Temporal holdout over k-fold:** Strict time-based splits prevent lookahead bias per research best practices
- **[03-05] Walk-forward with 90-day test windows:** Expanding training windows simulate realistic re-training as data accumulates
- **[03-05] Manual Spearman correlation:** No scipy dependency, Decimal precision throughout
- **[03-05] metric_fn parameter for extensibility:** Enables Phase 4 scoring engine to plug in custom evaluation logic
- **[04-01] Game threshold lower than eSports threshold:** 0.5 vs 0.7 allows multi-game specialists (trader with 55% CS2, 45% Valorant qualifies for both)
- **[04-01] Independent per-game classification:** Same trader evaluated separately for each game, can be specialist in multiple games
- **[04-01] primary_game only for specialists:** None for generalists, game slug for specialists - clear API contract for downstream logic
- **[04-02] Recency < 1 day gets full weight:** Same-day trading (e.g., 8am to 12pm) shouldn't be penalized by exponential decay
- **[04-02] Sample size confidence n - min + 1:** Ensures positive confidence at exactly minimum threshold (avoids 1-exp(0)=0 edge case)
- **[04-02] Consistency multiplier bonus-only:** 1.05x for score >= 80 AND stable, 1.0x baseline for all others, never penalty below 1.0
- **[04-02] Percentile rank None until batch normalization:** Population-relative ranks computed in batch via normalize_scores_to_percentiles for efficiency
- **[04-03] ExpertiseScore rows append-only:** New INSERT on each scoring run, no updates - enables score history for trend analysis
- **[04-03] Volume proxy fallback:** abs(size * avg_entry_price) when available, abs(size) when avg_entry_price is None
- **[04-03] Consistency from PerformanceSnapshot:** Retrieve consistency_score and consistency_signal from timeframe="all" snapshot
- **[04-03] Leaderboard max(computed_at) subquery:** Retrieve latest scores per trader using subquery pattern for efficiency
- **[05-01] Expert threshold for consensus:** raw_score > 70 matches Phase 4 scoring engine convention
- **[05-01] Agreement denominator includes all directions:** 4 LONG + 1 SHORT = 80% agreement (not 100%), prevents inflated confidence
- **[05-01] FLAT positions excluded from consensus:** Consensus is about directional alignment (LONG vs SHORT), FLAT is neutral exit
- **[05-01] Confidence formula weights:** 60% agreement + 30% sample size + 10% uniformity (from user research)
- **[05-01] Asymptotic sample size component:** (1 - exp(-(n - min_experts) / 10)) rewards larger samples with diminishing returns
- **[05-01] Fast follower window: 6 hours:** Metadata classification only, doesn't affect consensus or confidence calculations
- **[05-02] SignalSnapshot append-only design:** Matches ExpertiseScore pattern with computed_at field for history tracking
- **[05-02] Position market+timestamp index:** ix_position_market_last_trade for time-window expert activity queries
- **[05-02] Conditional module imports:** signals/__init__.py uses try/except for parallel plan execution support
- **[05-02] UTC-aware datetime in queries:** datetime.now(UTC) avoids utcnow() deprecation warnings
- **[05-03] SignalSnapshot field naming:** expert_addresses_json (not expert_addresses) for CSV storage
- **[05-03] Signal lost detection:** Create inactive snapshot when consensus drops, preserves append-only history for Phase 6 delta analysis
- **[05-03] Herding stub deferred:** assess_herding returns "not_analyzed" per user decision in CONTEXT.md
- **[05-03] Time-window filtering at query layer:** get_ranked_signals filters by expert activity windows for 1h/6h/24h views
- **[06-03] In-memory TTL deduplication:** Dict-based cache with cleanup on each check, no background thread or persistence needed
- **[06-03] Graceful failure handling:** Log error + continue pipeline, don't block other alerts (best-effort delivery)
- **[06-03] Fixed retry parameters:** 5 attempts, 2-60s exponential backoff matching Settings defaults (tenacity decorator limitation)

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

**Phase 3 (Historical Evaluation):**
- ✓ COMPLETE - All Phase 3 plans finished
- ✓ [03-01] Performance metrics calculator complete - realized/unrealized PnL, win rate, volume (27 tests)
- ✓ [03-02] Timeframe windows and profile classification complete - 7d/30d/90d/all filtering, selective vs active (26 tests)
- ✓ [03-03] Consistency detection complete - cross-timeframe stability, streak analysis, profile-specific bars (20 tests)
- ✓ [03-04] Evaluation storage & queries complete - PerformanceSnapshot/TraderProfile models, time-windowed queries (20 tests)
- ✓ [03-05] Validation framework complete - temporal holdout, walk-forward, Spearman correlation (28 tests)
- Phase 3 tests: 121 (27 + 26 + 20 + 20 + 28)
- Total project tests: 234 (62 Phase 1 + 51 Phase 2 + 121 Phase 3)

**Phase 4 (Scoring Engine):**
- ✓ COMPLETE - All Phase 4 plans finished
- ✓ [04-01] Concentration metrics complete - two-tier eSports/game concentration with specialist classification (22 tests)
- ✓ [04-02] Composite scoring engine complete - weighted components with consistency multiplier and percentile normalization (38 tests)
- ✓ [04-03] Leaderboard pipeline complete - ExpertiseScore model, leaderboard queries, full scoring orchestration (13 tests)
- ✓ Validation framework ready: temporal holdout with walk-forward testing available for weight tuning
- Expertise score weighting: DEFAULT_WEIGHTS set to win_rate 40%, concentration 25%, recency 20%, sample_size 15% (tunable via validation framework)
- Game patch tracking integration: Need reliable source for patch releases to tag markets with game versions
- Phase 4 tests: 73 (22 from 04-01, 38 from 04-02, 13 from 04-03)
- Total project tests: 307 (62 Phase 1 + 51 Phase 2 + 121 Phase 3 + 73 Phase 4)
- Ready for Phase 5 (Signal Detection)

**Phase 5 (Signal Detection):**
- ✓ COMPLETE - All Phase 5 plans finished
- ✓ [05-01] Consensus detection and confidence scoring complete - pure functions for expert consensus (27 tests)
- ✓ [05-02] Signal database layer complete - SignalSnapshot model, 4 query functions, 15 integration tests
- ✓ [05-03] Signal pipeline orchestration complete - end-to-end refresh and ranking (13 tests)
- Pure functions: detect_consensus, identify_first_mover, classify_followers, calculate_confidence_score
- Pipeline functions: refresh_market_signal, refresh_all_signals, get_ranked_signals, assess_herding (stub)
- Consensus thresholds: min_experts=3, min_agreement_pct=75% (configurable defaults from research)
- Confidence formula: 60% agreement + 30% sample size (asymptotic) + 10% uniformity (CV)
- FLAT positions excluded from consensus calculation (numerator and denominator)
- First-mover identification via earliest entry_timestamp, fast follower window: 6 hours
- Signal lost detection: inactive snapshots created when consensus drops below thresholds
- Time-window ranking: 1h/6h/24h views via get_ranked_signals
- Append-only history: multiple snapshots per market for Phase 6 delta detection
- Herding stub: assess_herding returns "not_analyzed" per user decision (deferred)
- Phase 5 tests: 55 (27 from 05-01, 15 from 05-02, 13 from 05-03)
- Total project tests: 362 (307 pre-Phase 5 + 55 Phase 5)
- Ready for Phase 6 (Alerting & Delivery)

**Phase 6 (Alerting System):**
- ✓ COMPLETE - All 3 plans finished
- ✓ [06-01] Signal event detection complete - NEW/STRENGTHENING/WEAKENING/LOST classification (12 tests)
- ✓ [06-02] Alert formatter complete - Telegram HTML with event headers, HTML escaping, address truncation (16 tests)
- ✓ [06-03] Telegram bot integration complete - delivery pipeline, deduplication, retry logic (11 tests)
- Event detection: compare latest snapshots to detect state changes in signals
- Formatter: pure function producing rich Telegram HTML messages
- Delivery pipeline: end-to-end orchestration from signals to Telegram messages
- TelegramAlerter: exponential backoff retry (5 attempts, 2-60s wait) with tenacity
- AlertDeduplicator: in-memory TTL cache (60min default) prevents duplicate alerts
- Graceful failure handling: log errors, continue pipeline, don't block other alerts
- Phase 6 tests: 39 (12 from 06-01, 16 from 06-02, 11 from 06-03)
- Total project tests: 401 (362 pre-Phase 6 + 39 Phase 6)
- Ready for Phase 7 (Scheduled Delivery & CLI)

## Session Continuity

Last session: 2026-02-11
Stopped at: Phase 6 execution complete, all plans verified
Resume file: None
Next: Phase 7 planning - CLI interface for market exploration, trader analysis, signal monitoring, and scheduled polling
