# Technology Stack

**Analysis Date:** 2026-02-12

## Languages

**Primary:**
- Python 3.11+ - All application code, pipelines, and CLI

## Runtime

**Environment:**
- Python 3.11 or higher (configured in `pyproject.toml`)
- Virtual environment required (Homebrew Python is externally-managed)

**Package Manager:**
- pip/setuptools
- Lockfile: Not present (dependencies managed in `pyproject.toml`)

## Frameworks

**Core:**
- `py-clob-client` (>=0.34.5) - Polymarket CLOB API client for market and trade data
- `SQLAlchemy` (>=2.0.46) - ORM for database models and queries in `src/db/models.py`
- `Web3.py` (>=6.0.0) - Polygon blockchain interaction via RPC endpoints (Phase 8)

**Configuration:**
- `pydantic` (>=2.12.5) - Data validation for API responses in `src/api/models.py`
- `pydantic-settings` (>=2.0) - Environment variable loading via `src/config/settings.py`
- `python-dotenv` (>=1.0) - .env file loading

**HTTP & Networking:**
- `httpx` (>=0.28.1) - Modern async-capable HTTP client for Polymarket Data API
- `requests` - Graph API queries in `src/graph/client.py`

**Retry & Rate Limiting:**
- `tenacity` (>=9.1.3) - Exponential backoff retry logic in API clients (`src/api/client.py`, `src/blockchain/client.py`)
- Custom `RateLimiter` (token bucket) in `src/api/rate_limiter.py` - 50 req/s (80% of Polymarket's 60/s limit)

**Logging:**
- `loguru` (>=0.7.3) - Structured logging throughout codebase

**CLI:**
- `click` (>=8.1) - Command-line interface entry point in `src/cli/commands.py`
- `rich` (>=13.0) - Terminal output formatting and tables

**Alerting:**
- `python-telegram-bot` (>=22.6) - Telegram integration in `src/alerts/telegram.py`

**Data Processing:**
- `pyyaml` (>=6.0) - YAML taxonomy parsing for market classification

## Key Dependencies

**Critical:**
- `py-clob-client` - Only way to access Polymarket CLOB API; provides market discovery and trade history
- `SQLAlchemy` - All data persistence; enables category-agnostic schema design
- `Web3.py` - Required for blockchain fallback method (Phase 8 blockchain integration)
- `tenacity` - Ensures reliability of API calls to unstable RPC endpoints and rate-limited APIs

**Infrastructure:**
- `httpx` - Required for Polymarket public Data API (doesn't require authentication)
- `requests` - Required for The Graph API queries (GraphQL endpoint)
- `python-telegram-bot` - Required for alert delivery (Phase 6)

## Configuration

**Environment:**
- Configured via `.env` file (optional values in `.env.example`)
- Loaded by `pydantic-settings` in `src/config/settings.py` using `BaseSettings`
- Key configs:
  - `POLYMARKET_API_HOST` - CLOB endpoint (default: production)
  - `POLYMARKET_API_KEY` - Optional authentication key
  - `DATABASE_URL` - SQLite path (default: `sqlite:///data/polymarket.db`)
  - `MAX_REQUESTS_PER_SECOND` - Rate limit (default: 50)
  - `POLYGON_RPC_URL` - Blockchain RPC endpoint (Alchemy, Infura, QuickNode, Ankr, or public)
  - `THE_GRAPH_API_KEY` - The Graph API key for subgraph queries
  - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` - Alert delivery credentials
  - `LOG_LEVEL` and `LOG_DIR` - Logging configuration

**Build:**
- `pyproject.toml` - Setuptools configuration with project metadata, dependencies, and CLI entry point
- Build backend: `setuptools>=68.0`

## Database

**Primary:**
- SQLite (configured with WAL mode for write concurrency)
- Location: `data/polymarket.db` (created on first run via `src/db/session.py`)
- Schema: 17 tables defined in `src/db/models.py` (Markets, Traders, Trades, TraderCategorySummary, TaxonomyNode, MarketClassification, Position, TraderProfileDB, PerformanceSnapshot, ExpertiseScore, SignalSnapshot, BlockchainSyncState, etc.)
- Precision: `Numeric(20,6)` for volumes, `Numeric(10,6)` for prices (Decimal precision to avoid float rounding)
- Indexes: Composite indexes on (trader, timestamp), (market, timestamp), (market, trader) for time-series queries

**Concurrency:**
- WAL (Write-Ahead Logging) mode enabled via pragma in `src/db/session.py`
- Foreign key constraints enforced via pragma

## Platform Requirements

**Development:**
- Python 3.11+
- Virtual environment (venv, poetry, or uv)
- SQLite 3 (standard with Python)
- Network access to:
  - `https://clob.polymarket.com` - Polymarket CLOB API
  - `https://data-api.polymarket.com` - Polymarket public Data API
  - `https://gateway.thegraph.com` - The Graph subgraph queries
  - Polygon RPC endpoint (Alchemy, Infura, QuickNode, Ankr, or public)

**Production:**
- Same as development (pure Python, no external services required)
- Optional: Telegram bot token for alert delivery
- Optional: The Graph API key for faster trader history queries
- Optional: Polygon RPC credentials for blockchain fallback

## Testing

**Test Framework:**
- `pytest` (>=8.0) - Test runner
- `pytest-cov` - Code coverage
- `pytest-mock` - Mocking utilities
- Test files: `tests/` directory with 350+ tests across pipeline, discovery, scoring, signals, and blockchain modules

**Run Commands:**
```bash
pytest tests/                      # Run all tests
pytest tests/ -v                   # Verbose output
pytest tests/ --cov=src            # With coverage
pytest tests/test_*.py -k keyword  # Run specific tests
```

## External Services

**Required APIs:**
- Polymarket CLOB API (`https://clob.polymarket.com`) - Market metadata and simplified market data
- Polymarket Data API (`https://data-api.polymarket.com`) - Public trade history

**Optional APIs:**
- The Graph (`https://gateway.thegraph.com`) - GraphQL subgraph queries for trader histories (preferred over blockchain)
- Polygon RPC - Blockchain trade history as fallback

**Optional Services:**
- Telegram Bot API - Alert delivery (only if credentials provided)

---

*Stack analysis: 2026-02-12*
