# Architecture

**Analysis Date:** 2026-02-12

## Pattern Overview

**Overall:** Pipeline-based intelligence system with layered processing stages and pluggable data sources

**Key Characteristics:**
- Event-first trader discovery (start from active markets, backtrack history)
- Category-agnostic design with config-driven routing
- Append-only signal history (enable auditing without state mutations)
- Pure function evaluation layers decoupled from ORM
- Multiple data source support (API, blockchain, The Graph)

## Layers

**API Layer:**
- Purpose: Polymarket CLOB client abstraction with retry logic and rate limiting
- Location: `src/api/`
- Contains: PolymarketClient (py-clob-client wrapper), rate limiter, Pydantic models
- Depends on: py-clob-client SDK, httpx, tenacity
- Used by: Pipeline ingestion stages

**Data Persistence Layer:**
- Purpose: SQLAlchemy ORM models and database session management
- Location: `src/db/`
- Contains: Market, Trader, Trade, TraderCategorySummary, ExpertiseScore, SignalSnapshot models
- Depends on: SQLAlchemy 2.0, SQLite with WAL mode
- Used by: All pipeline stages for CRUD operations

**Configuration Layer:**
- Purpose: Settings management with environment variable loading
- Location: `src/config/settings.py`
- Contains: Pydantic Settings class with all runtime configuration
- Depends on: pydantic-settings
- Used by: All modules for configuration access

**Ingestion Pipeline:**
- Purpose: Orchestrate data flow from API/blockchain to database with category routing
- Location: `src/pipeline/ingest.py`
- Contains: IngestionPipeline class coordinating market ingestion, trader discovery, history backfill
- Depends on: API client, database session, category filter
- Used by: CLI commands, automated polling

**Classification Layer:**
- Purpose: Route trades to detail or summary storage based on category configuration
- Location: `src/pipeline/filters.py`, `src/taxonomy/`
- Contains: CategoryFilter (routing), PatternMatcher (regex-based market classification), taxonomy loader
- Depends on: YAML taxonomy configuration
- Used by: Ingestion pipeline for trade routing

**Evaluation Layer:**
- Purpose: Pure computation functions for performance metrics and expertise scoring
- Location: `src/evaluation/`
- Contains: metrics (PnL, win rate), concentration (specialization analysis), scoring (composite expertise), consistency, validation
- Depends on: Decimal arithmetic only (no ORM)
- Used by: Scoring pipeline, signal detection

**Scoring Pipeline:**
- Purpose: Calculate expertise scores for traders across games and generate leaderboards
- Location: `src/pipeline/scoring_pipeline.py`
- Contains: LeaderboardEntry dataclass, batch score computation, percentile normalization
- Depends on: Evaluation layer, database queries
- Used by: CLI leaderboard commands, signal detection

**Signal Detection Pipeline:**
- Purpose: Identify expert consensus and generate consensus signals with confidence scoring
- Location: `src/signals/pipeline.py`
- Contains: SignalResult dataclass, consensus detection, first-mover classification, signal persistence
- Depends on: Detection (pure functions), database session
- Used by: Alerting layer, signal queries

**Alert Layer:**
- Purpose: Detect new/changing signals and deliver notifications
- Location: `src/alerts/`
- Contains: TelegramAlerter, AlertDetector, AlertFormatter, delivery retry logic
- Depends on: python-telegram-bot
- Used by: CLI polling commands

**CLI Layer:**
- Purpose: Command-line interface with rich formatting and scheduler
- Location: `src/cli/`
- Contains: Click command group, formatters (Rich tables), scheduler (APScheduler-compatible)
- Depends on: Click, Rich, loguru
- Used by: Entry point `polymarket` command

**Data Sources (Pluggable):**
- API source: `src/api/client.py` - Direct REST queries (100-trade limit, instant)
- Blockchain source: `src/blockchain/client.py` - Polygon RPC logs (49M blocks, 6-7 hours)
- Graph source: `src/graph/client.py` - The Graph subgraph queries (instant, zero storage)

## Data Flow

**Market Discovery Flow:**

1. API Client fetches active Polymarket markets
2. Markets are persisted to database with category metadata
3. Category Filter classifies each market by type (detail category or summary)

**Trader Discovery Flow:**

1. Active markets → get market trades from API
2. Extract unique trader addresses from trades
3. Create Trader records with first_seen timestamp
4. Immediately store trades that led to discovery

**Trader History Backfill (Hybrid):**

1. Try The Graph (preferred) - instant, zero storage
2. Fallback to blockchain if Graph unavailable - 6-7 hours, complete
3. Fallback to API if blockchain unavailable - instant, 100-trade limit
4. For each trade: fetch market metadata, categorize by category
5. Route to Trade table (detail) or TraderCategorySummary (aggregate)
6. Mark trader.backfill_complete = True

**Evaluation Flow:**

1. Query all positions for a trader in a game
2. Calculate performance metrics (PnL, win rate per timeframe)
3. Calculate concentration metrics (game vs esports level)
4. Calculate consistency multiplier across timeframes
5. Compute composite expertise score: weighted sum + consistency bonus
6. Normalize to percentiles against population

**Signal Detection Flow:**

1. Find all markets with expert positions
2. For each market, query latest expert scores
3. Detect consensus: 3+ experts, 75%+ agreement
4. Identify first-mover by earliest timestamp
5. Classify followers (fast vs slow)
6. Persist SignalSnapshot (append-only)
7. Classify signal status: NEW, STRENGTHENING, WEAKENING, LOST

**State Management:**
- Markets: Upsert pattern (update if exists, insert if new)
- Traders: Immutable creation, backfill_complete flag for progression
- Trades: Insert-only with trade_id deduplication
- Summaries: Upsert with volume/count aggregation
- Expertise Scores: Append-only snapshots for history
- Signals: Append-only snapshots for event tracking
- All tables: created_at timestamp for audit trail

## Key Abstractions

**IngestionPipeline:**
- Purpose: Single orchestration point for all data ingestion
- Examples: `src/pipeline/ingest.py`
- Pattern: Dependency injection (client, session_factory, category_filter)
- Methods: ingest_active_markets(), discover_traders_from_market(), ingest_trader_history_hybrid(), run_full_sweep()

**CategoryFilter:**
- Purpose: Config-driven trade routing (detail vs summary)
- Examples: `src/pipeline/filters.py`
- Pattern: O(1) case-insensitive lookup with set of lowercased categories
- Methods: requires_detail(), route_trades()

**PatternMatcher:**
- Purpose: Hierarchical market classification with deepest-match-wins
- Examples: `src/taxonomy/classifier.py`
- Pattern: Precompiled regex with metadata tuples
- Methods: classify(), classify_batch()

**LeaderboardEntry:**
- Purpose: Immutable leaderboard row with specialization labels
- Examples: `src/pipeline/scoring_pipeline.py`
- Pattern: Frozen dataclass with all computed values

**SignalResult:**
- Purpose: Immutable consensus detection result
- Examples: `src/signals/pipeline.py`
- Pattern: Frozen dataclass with expert list, confidence, first-mover, follower classifications

**Settings:**
- Purpose: Central configuration with environment variable overrides
- Examples: `src/config/settings.py`
- Pattern: Pydantic BaseSettings with @lru_cache decorated get_settings()
- Properties: All have sensible defaults, overridable via env vars

## Entry Points

**CLI Entry Point:**
- Location: `src/cli/commands.py` (polymarket command group)
- Triggers: User runs `polymarket [command] [options]`
- Responsibilities:
  - Dependency injection (_get_dependencies)
  - Database auto-creation
  - Command routing (markets, trader, signals, leaderboard, sweep, poll)
  - Error handling and rich formatting

**Polling Entry Point:**
- Location: `src/cli/scheduler.py`
- Triggers: `polymarket poll` command
- Responsibilities:
  - Hourly scheduling of full sweeps
  - Signal detection and alerting
  - Graceful shutdown on Ctrl+C

**Programmatic Entry Point:**
- Location: IngestionPipeline.run_full_sweep() or individual methods
- Triggers: External orchestration or testing
- Responsibilities: Complete data refresh cycle

## Error Handling

**Strategy:** Graceful degradation with per-stage error isolation

**Patterns:**

1. **API Client Errors:** Exponential backoff retry (tenacity) + rate limit recovery
2. **Market Ingestion:** Log and continue (one market failure doesn't stop batch)
3. **Trader Discovery:** Log and continue (one trader discovery failure doesn't stop market loop)
4. **History Backfill:** Try Graph → fallback to blockchain → fallback to API
5. **Pipeline Stages:** Per-trader try/except with rollback on failure
6. **Database:** Explicit rollback on exception in finally block
7. **Alerts:** Retry with exponential backoff, deduplication by 60min TTL

All errors logged to `logs/cli_session.log` via loguru with structured context.

## Cross-Cutting Concerns

**Logging:**
- Framework: loguru with rotating file handler
- Location: `src/utils/logging.py`
- CLI logs: `logs/cli_session.log` (captures all terminal output)
- Levels: DEBUG (trace execution), INFO (key checkpoints), WARNING (recoverable), ERROR (failures)

**Validation:**
- Pydantic models validate all API responses
- CategoryFilter validates category names (case-insensitive)
- ExpertiseScore validates minimum trade counts (MIN_RESOLVED_MARKETS = 5)
- SignalDetection validates minimum expert count (3) and agreement (75%)

**Authentication:**
- API: Optional API key (read-only mode)
- Blockchain: Public RPC endpoints (no auth required)
- The Graph: Paid API key in .env (THE_GRAPH_API_KEY)
- Telegram: Bot token + chat ID in .env

**Rate Limiting:**
- Token bucket: 50 req/s (80% of 60/s Polymarket sustained limit)
- Implementation: `src/api/rate_limiter.py` with asyncio.Semaphore pattern
- Applies to: All API client calls
- Retry: Automatic backoff on 429 responses

**Precision:**
- Financial values: Decimal type (no float rounding errors)
- Scores: Decimal(Decimal("0-100"))
- Volumes: Numeric(20,6) in database
- Prices: Numeric(10,6) in database (capped at 1.0)

---

*Architecture analysis: 2026-02-12*
