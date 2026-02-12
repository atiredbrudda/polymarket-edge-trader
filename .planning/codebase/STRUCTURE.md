# Codebase Structure

**Analysis Date:** 2026-02-12

## Directory Layout

```
GSD_Polymarket/
├── src/                          # All application code
│   ├── __init__.py              # Package root
│   ├── api/                     # Polymarket CLOB API client
│   ├── db/                      # SQLAlchemy ORM models and session
│   ├── config/                  # Settings and configuration
│   ├── pipeline/                # Data ingestion and scoring orchestration
│   ├── taxonomy/                # Market classification (YAML + regex)
│   ├── discovery/               # Trader discovery and position tracking
│   ├── evaluation/              # Pure scoring functions (metrics, concentration)
│   ├── signals/                 # Consensus detection and signal pipeline
│   ├── alerts/                  # Alert detection and Telegram delivery
│   ├── blockchain/              # Polygon blockchain RPC client
│   ├── graph/                   # The Graph subgraph client
│   ├── cli/                     # Click commands and formatters
│   └── utils/                   # Logging and utility functions
├── tests/                       # Comprehensive test suite (438 tests)
├── data/                        # Runtime data directory
│   └── taxonomy/                # YAML taxonomy files
├── logs/                        # CLI session logs
├── .planning/                   # GSD workflow artifacts
├── pyproject.toml              # Dependencies and entry point
├── .env                        # Environment variables (secrets)
└── README.md                   # Project documentation
```

## Directory Purposes

**`src/api/`:**
- Purpose: Polymarket CLOB API client abstraction
- Contains: PolymarketClient (wrapper), RateLimiter, Pydantic API models
- Key files: `client.py` (main client), `rate_limiter.py` (token bucket), `models.py` (MarketResponse, TradeResponse)
- Entry point: PolymarketClient initialization in CLI commands

**`src/db/`:**
- Purpose: Database abstraction layer with ORM models
- Contains: SQLAlchemy models (Market, Trader, Trade, ExpertiseScore, SignalSnapshot)
- Key files: `models.py` (all ORM classes), `session.py` (session factory and context managers)
- Dependencies: SQLAlchemy 2.0, SQLite database

**`src/config/`:**
- Purpose: Runtime configuration and settings management
- Contains: Pydantic Settings class with environment variable loading
- Key files: `settings.py` (Settings class with @lru_cache get_settings())
- Properties: API host, database URL, rate limits, taxonomy path, alert config

**`src/pipeline/`:**
- Purpose: Orchestration layers for data processing
- Contains: Ingestion, scoring, classification, filtering, and query modules
- Key files:
  - `ingest.py` (IngestionPipeline - market/trader/history ingestion)
  - `scoring_pipeline.py` (LeaderboardEntry, batch score computation)
  - `filters.py` (CategoryFilter for detail/summary routing)
  - `queries.py` (Database query helpers)
  - `classify.py` (Classification orchestration)
  - `aggregators.py` (Trade grouping and aggregation)

**`src/taxonomy/`:**
- Purpose: Market classification with hierarchical taxonomy
- Contains: YAML loader, regex-based pattern matcher, taxonomy models
- Key files:
  - `loader.py` (TaxonomyConfig loading from YAML)
  - `classifier.py` (PatternMatcher with precompiled regexes)
  - `models.py` (TaxonomyConfig, GameNode, TournamentNode, TeamNode dataclasses)
- Data files: `data/taxonomy/esports.yaml` (game/tournament/team hierarchy)

**`src/discovery/`:**
- Purpose: Trader identification and position tracking
- Contains: Position tracker for per-trader, per-market state
- Key files:
  - `trader_discovery.py` (Event-first discovery logic)
  - `position_tracker.py` (Track trader positions across markets)

**`src/evaluation/`:**
- Purpose: Pure functions for performance evaluation and scoring
- Contains: No classes, only duck-typed functions and frozen dataclasses
- Key files:
  - `scoring.py` (Composite expertise score: win_rate(0.4) + concentration(0.25) + recency(0.2) + sample_size(0.15))
  - `metrics.py` (PnL, win rate, realized metrics per timeframe)
  - `concentration.py` (Game-level vs eSports-level specialization)
  - `consistency.py` (Cross-timeframe stability)
  - `validation.py` (Data validation rules)
  - `profiles.py` (Trader profile generation)
  - `timeframes.py` (30d, 90d, all-time window helpers)

**`src/signals/`:**
- Purpose: Consensus detection and signal generation
- Contains: Pure detection functions and pipeline orchestration
- Key files:
  - `detection.py` (detect_consensus, identify_first_mover, classify_followers)
  - `confidence.py` (Confidence score calculation)
  - `pipeline.py` (SignalResult, refresh_market_signal, refresh_all_signals)
  - `queries.py` (Expert position queries)

**`src/alerts/`:**
- Purpose: Alert detection and delivery orchestration
- Contains: Telegram integration, alert formatting, delivery retry
- Key files:
  - `detector.py` (AlertDetector - new/strengthening/weakening/lost classification)
  - `formatter.py` (Rich markdown formatting for Telegram)
  - `telegram.py` (TelegramAlerter with retry logic)
  - `delivery.py` (Delivery orchestration and deduplication)

**`src/blockchain/`:**
- Purpose: Polygon blockchain RPC integration for complete trade history
- Contains: RPC client, event decoder, BlockchainTrade models
- Key files:
  - `client.py` (PolygonBlockchainClient with log filtering)
  - `decoder.py` (ABI decoding for Polymarket events)
  - `models.py` (BlockchainTrade with extraction methods)

**`src/graph/`:**
- Purpose: The Graph subgraph integration (preferred data source)
- Contains: GraphQL queries for instant indexed blockchain data
- Key files:
  - `client.py` (GraphClient with trader trade queries)
  - `converters.py` (Convert Graph trades to API TradeResponse format)

**`src/cli/`:**
- Purpose: Command-line interface and formatting
- Contains: Click command group, rich table formatters, polling scheduler
- Key files:
  - `commands.py` (Click @click.group, @click.command decorators for markets/trader/signals/leaderboard/sweep/poll)
  - `formatters.py` (Rich Table formatting functions)
  - `scheduler.py` (APScheduler-compatible polling loop)

**`src/utils/`:**
- Purpose: Shared utilities and logging setup
- Contains: Structured logging configuration
- Key files: `logging.py` (loguru configuration with rotating file handler)

**`tests/`:**
- Purpose: Comprehensive test suite across all phases
- Contains: 438 tests organized by phase
- Structure: Mirrors src/ directory with test_*.py files
- Key files:
  - `test_api_client.py` (API wrapper tests)
  - `test_discovery.py` (Trader discovery tests)
  - `test_evaluation.py` (Evaluation function tests)
  - `test_scoring_pipeline.py` (Score computation tests)
  - `test_signal_detection.py` (Consensus tests)
  - `test_alert_delivery.py` (Telegram integration tests)
  - `test_scheduler.py` (Polling scheduler tests)

**`data/`:**
- Purpose: Runtime data storage
- Contains: SQLite database, taxonomy YAML files, trader graphs (optional)
- Key files:
  - `data/polymarket.db` (SQLite WAL mode, auto-created)
  - `data/taxonomy/esports.yaml` (Game/tournament/team hierarchy)

**`logs/`:**
- Purpose: Session and debug logging
- Contains: CLI session logs for debugging
- Key files: `logs/cli_session.log` (rotating file, all CLI output)

## Key File Locations

**Entry Points:**
- `src/cli/commands.py`: CLI entry point (polymarket command group)
- `src/cli/scheduler.py`: Polling scheduler (polymarket poll)
- `pyproject.toml`: [project.scripts] defines polymarket = "src.cli.commands:cli"

**Configuration:**
- `src/config/settings.py`: All runtime settings
- `.env`: Environment variables (not committed, contains secrets)
- `data/taxonomy/esports.yaml`: Game/tournament/team taxonomy

**Core Logic:**
- `src/pipeline/ingest.py`: Data ingestion orchestration
- `src/pipeline/scoring_pipeline.py`: Score computation and leaderboards
- `src/signals/pipeline.py`: Consensus detection and signal generation
- `src/evaluation/scoring.py`: Expertise score formula

**Testing:**
- `tests/` directory: Full test suite
- `pytest.ini` or `pyproject.toml [tool.pytest]`: Test configuration

## Naming Conventions

**Files:**
- `client.py`: API client wrappers (e.g., `src/api/client.py`, `src/graph/client.py`)
- `models.py`: ORM models (e.g., `src/db/models.py`) or Pydantic models (e.g., `src/api/models.py`)
- `pipeline.py`: Orchestration layers (e.g., `src/signals/pipeline.py`)
- `queries.py`: Database query helpers
- `detection.py`: Pure detection logic
- `formatter.py`: Output formatting functions
- `commands.py`: Click CLI commands
- `test_*.py`: Test files (mirror src/ structure)

**Directories:**
- Plural form for packages with multiple modules: `alerts/`, `signals/`, `evaluation/`
- Descriptive names reflecting responsibility: `pipeline/`, `discovery/`, `blockchain/`, `graph/`
- Grouped by domain, not by layer: All scoring code (evaluation + scoring_pipeline) can be found

**Classes:**
- CamelCase: PolymarketClient, IngestionPipeline, CategoryFilter, PatternMatcher
- PascalCase: Market, Trader, Trade, SignalSnapshot, ExpertiseScore
- Descriptive names with role clarity: TelegramAlerter, RateLimiter, GraphClient

**Functions:**
- snake_case: ingest_active_markets(), discover_traders_from_market(), refresh_market_signal()
- Verb-first for actions: calculate_win_rate(), detect_consensus(), format_markets_table()
- Underscore prefix for private: _retry_call(), _compile_patterns()

**Variables:**
- snake_case: trader_address, market_id, detail_trades, expert_count
- Descriptive: session_factory, rate_limiter (not cl, rl)

**Types:**
- Frozen dataclasses for immutable results: LeaderboardEntry, SignalResult, ExpertiseScoreResult
- Pydantic models for API validation: MarketResponse, TradeResponse

## Where to Add New Code

**New Feature (e.g., new evaluation metric):**
- Primary code: `src/evaluation/metrics.py` (pure function)
- Pipeline integration: `src/pipeline/scoring_pipeline.py` (if affects scores)
- Tests: `tests/test_metrics.py` or `tests/test_scoring_pipeline.py`
- CLI exposure: `src/cli/commands.py` if user-facing

**New Component/Module (e.g., new data source):**
- Implementation: Create new directory `src/[domain]/` (e.g., `src/dataverse/` for Dataverse integration)
- Models: `src/[domain]/models.py` (data structures)
- Client: `src/[domain]/client.py` (API wrapper)
- Converters: `src/[domain]/converters.py` (if converting to internal formats)
- Integration: Wire into `src/pipeline/ingest.py` hybrid methods
- Tests: `tests/test_[domain]_integration.py`

**New Command:**
- Implementation: Add @click.command() to `src/cli/commands.py`
- Formatting: Add formatter function to `src/cli/formatters.py`
- Logic: Delegate to pipeline/discovery/evaluation modules (don't put business logic in CLI)
- Tests: `tests/test_cli_commands.py`

**Utilities:**
- Shared helpers: `src/utils/` (logging, validation helpers)
- Pure computation: `src/evaluation/` (if scoring-related)
- Database queries: `src/pipeline/queries.py` (reusable query builders)

**Tests:**
- Unit tests (functions): Co-located with source or `tests/test_*.py`
- Integration tests: `tests/test_*.py` with _integration suffix
- End-to-end: `tests/test_pipeline.py`
- Fixtures: `tests/conftest.py` (shared fixtures)
- Mocks: Use pytest-mock, define in test files or conftest

## Special Directories

**`.planning/`:**
- Purpose: GSD workflow artifacts (requirements, plans, executions)
- Generated: Yes (by GSD orchestrator)
- Committed: Yes (tracks all planning and execution history)

**`logs/`:**
- Purpose: Runtime logs (CLI sessions, errors)
- Generated: Yes (at runtime by loguru)
- Committed: No (.gitignore entry)

**`.venv/`:**
- Purpose: Python virtual environment
- Generated: Yes (by `python3 -m venv .venv`)
- Committed: No (.gitignore entry)

**`data/polymarket.db`:**
- Purpose: SQLite database with trader/market/trade data
- Generated: Yes (auto-created on first run)
- Committed: No (.gitignore entry, user-specific)

**`data/polymarket.db-wal`, `data/polymarket.db-shm`:**
- Purpose: SQLite WAL mode files (Write-Ahead Logging)
- Generated: Yes (by SQLite automatically)
- Committed: No (WAL mode temporary files)

**`polymarket_tracker.egg-info/`:**
- Purpose: Package metadata (generated by setuptools)
- Generated: Yes (`pip install -e .`)
- Committed: No (.gitignore entry)

---

*Structure analysis: 2026-02-12*
