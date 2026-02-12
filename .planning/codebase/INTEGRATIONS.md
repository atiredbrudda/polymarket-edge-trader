# External Integrations

**Analysis Date:** 2026-02-12

## APIs & External Services

**Polymarket CLOB API:**
- Service: `https://clob.polymarket.com`
- What it's used for: Market discovery, market metadata, simplified market endpoints
- SDK/Client: `py_clob_client.client.ClobClient` (py-clob-client)
- Auth: Optional via `POLYMARKET_API_KEY` (read-only mode if not provided)
- Implementation: `src/api/client.py` - `PolymarketClient.get_markets()`, `get_market()`

**Polymarket Data API:**
- Service: `https://data-api.polymarket.com`
- What it's used for: Public trade history, trader trades, market trades (does not require authentication)
- SDK/Client: Direct HTTP calls via `httpx`
- Auth: None required
- Implementation: `src/api/client.py` - `PolymarketClient.get_market_trades()`, `get_trader_trades()`
- Endpoints:
  - `/trades?market={condition_id}` - Fetch trades for a specific market
  - `/trades?proxyWallet={trader_address}` - Fetch all trades for a trader

**The Graph - Polymarket Orderbook Subgraph:**
- Service: `https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}`
- Subgraph ID: `7fu2DWYK93ePfzB24c2wrP94S3x4LGHUrQxphhoEypyY`
- What it's used for: Complete trader histories, order events, account statistics (PREFERRED method over blockchain scanning)
- SDK/Client: Direct GraphQL queries via `requests`
- Auth: Required - `THE_GRAPH_API_KEY` in `.env` or settings
- Implementation: `src/graph/client.py` - `GraphClient.get_trader_trades()`, `get_account_stats()`
- Query method: GraphQL POST requests to The Graph gateway
- Performance: Instant results (3 seconds for 2,000+ trades), zero storage overhead
- Capabilities:
  - Fetches orderFilledEvents where trader is maker or taker
  - Supports pagination (skip/first parameters)
  - Returns complete trade data: amounts, fees, timestamps, block numbers, transaction hashes

## Data Storage

**Databases:**
- SQLite (local file-based)
  - Connection: `sqlite:///data/polymarket.db` (configurable via `DATABASE_URL`)
  - Client: SQLAlchemy ORM with `sqlalchemy.orm.Session`
  - Schema: 17 tables in `src/db/models.py`
  - Initialization: `src/db/session.py` - `init_db()` creates engine, tables, session factory
  - WAL mode enabled for write concurrency
  - Foreign key constraints enforced

**File Storage:**
- Local filesystem only
  - Database: `data/polymarket.db` (SQLite)
  - Logs: `logs/` directory (configured via `LOG_DIR`)
  - Taxonomy: `data/taxonomy/esports.yaml` (YAML configuration file)
  - Test fixtures and data in `tests/` directory

**Caching:**
- None - All data queried fresh from APIs and stored in SQLite
- Rate limiting: In-memory token bucket (`src/api/rate_limiter.py`) for API request pacing

## Authentication & Identity

**Polymarket API:**
- Auth type: Optional API key (read-only mode works without it)
- Credential location: `POLYMARKET_API_KEY` in `.env`
- Implementation: Passed to `ClobClient(key=...)` in `src/api/client.py`

**The Graph API:**
- Auth type: API key required
- Credential location: `THE_GRAPH_API_KEY` in `.env`
- Implementation: In GraphQL endpoint URL and settings in `src/config/settings.py`
- Obtaining key: Sign up at `https://thegraph.com/studio/`

**Telegram Bot:**
- Auth type: Bot token + Chat ID (both required)
- Credential location: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Implementation: `src/alerts/telegram.py` - `TelegramAlerter` wraps `telegram.Bot`
- Obtaining credentials:
  - Bot token: Create bot via @BotFather on Telegram
  - Chat ID: Send message to bot and retrieve chat ID

**Polygon RPC:**
- Auth type: Optional (depends on provider)
- Credential location: `POLYGON_RPC_URL` in `.env`
- Providers supported:
  - Alchemy (recommended, free tier): `https://polygon-mainnet.g.alchemy.com/v2/{API_KEY}`
  - Infura: `https://polygon-mainnet.infura.io/v3/{PROJECT_ID}`
  - QuickNode: `https://your-endpoint-name.polygon-mainnet.quiknode.pro/{API_KEY}/`
  - Ankr (free public): `https://rpc.ankr.com/polygon`
  - Public RPC (fallback, unreliable): `https://polygon-rpc.com`
- Implementation: `src/blockchain/client.py` - `PolygonBlockchainClient` via `Web3(Web3.HTTPProvider(...))`

## Monitoring & Observability

**Error Tracking:**
- None - Errors logged via loguru

**Logs:**
- Approach: Structured logging via `loguru` throughout codebase
- Output: Console (DEBUG/INFO/WARNING/ERROR) + file rotating logs
- Configuration: `LOG_LEVEL` (default: INFO) and `LOG_DIR` (default: logs/)
- Special: CLI session log file captured in `logs/cli_session.log`
- Files: `src/config/settings.py` configures log paths
- Usage: Every API call, database operation, and pipeline step logs via `logger.info()`, `logger.debug()`, etc.

## CI/CD & Deployment

**Hosting:**
- None specified - Pure Python application designed to run locally or on any server with Python 3.11+

**CI Pipeline:**
- None configured in repo

**Deployment:**
- Manual via pip install from `pyproject.toml`
- Entry point: `polymarket` command (Click-based CLI in `src/cli/commands.py`)

## Environment Configuration

**Required env vars:**
- None strictly required - All have sensible defaults
- Most useful to set:
  - `DATABASE_URL` - SQLite database path
  - `LOG_LEVEL` - Logging verbosity
  - `THE_GRAPH_API_KEY` - For fast trader history queries
  - `POLYGON_RPC_URL` - For blockchain integration
  - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` - For alerts

**Optional env vars:**
- `POLYMARKET_API_KEY` - For authenticated Polymarket API access (not required for read-only)
- `BACKFILL_MONTHS` - Historical data window (default: 12)
- `DETAIL_CATEGORIES` - JSON array of categories to store full trade detail (default: `["eSports"]`)
- `MAX_REQUESTS_PER_SECOND` - API rate limit (default: 50)
- `BLOCKCHAIN_BATCH_SIZE` - Blocks per RPC query (default: 100, must be 10 for Alchemy free)
- Retry configuration: `retry_*` settings for API and blockchain operations

**Secrets location:**
- `.env` file (ignored by git via `.gitignore`)
- Must provide: Telegram credentials, The Graph API key, Polygon RPC credentials
- Never commit `.env` - use `.env.example` as template

## Webhooks & Callbacks

**Incoming:**
- None - Pure polling/pull architecture

**Outgoing:**
- Telegram messages: Alerts sent via `python-telegram-bot` to chat ID
- No other outgoing webhooks

## Rate Limiting & Throttling

**Polymarket APIs:**
- Limit: 60 requests/second sustained
- Implementation: Token bucket rate limiter at 50 req/s (80% of limit) in `src/api/rate_limiter.py`
- Per-request: `rate_limiter.acquire()` blocks until token available
- Thread-safe: Uses `Lock` for concurrent access

**Polymarket Blockchain (RPC):**
- Per-provider limits vary:
  - Alchemy free: 10 blocks per eth_getLogs call
  - Infura: 100k requests/day
  - QuickNode: Custom limits
- Implementation: Retry logic with exponential backoff in `src/blockchain/client.py`
- Rate limit delay: 0.1 seconds between RPC calls

**The Graph:**
- Limit: Per-API-key rate limits (consult The Graph documentation)
- Implementation: Direct GraphQL requests, no rate limiting applied in code

**Telegram:**
- Limit: Telegram's standard bot rate limits
- Implementation: Retry on 429 with exponential backoff in `src/alerts/telegram.py`

## Retry Logic

**API Calls:**
- Framework: `tenacity` library with exponential backoff
- Policy: Retry on ConnectionError, TimeoutError, httpx.HTTPError
- Config in `src/config/settings.py`:
  - `retry_max_attempts`: 5
  - `retry_backoff_multiplier`: 2.0
  - `retry_min_wait`: 2.0 seconds
  - `retry_max_wait`: 60.0 seconds
- Implementation: `src/api/client.py` - `_retry_call()` method

**Blockchain RPC:**
- Policy: Retry on ConnectionError, TimeoutError
- Config:
  - `blockchain_retry_attempts`: 3
  - `blockchain_retry_min_wait`: 2.0 seconds
  - `blockchain_retry_max_wait`: 30.0 seconds
- Implementation: `src/blockchain/client.py` - `_retry_rpc_call()` method

**Telegram Alerts:**
- Policy: Retry on RetryAfter (429), NetworkError, TimedOut
- Config:
  - `alert_retry_max_attempts`: 5
  - `alert_retry_min_wait`: 2.0 seconds
  - `alert_retry_max_wait`: 60.0 seconds
- Implementation: `src/alerts/telegram.py` - `_send_with_retry()` with `@retry` decorator

## Data Format & APIs

**Polymarket Data:**
- Format: JSON from REST APIs
- Trade data: condition_id, proxyWallet, side, size, price, timestamp, outcome, transactionHash

**The Graph Data:**
- Format: GraphQL query responses (JSON)
- orderFilledEvents schema: id, maker, taker, makerAmountFilled, takerAmountFilled, makerAssetId, takerAssetId, fee, timestamp, blockNumber, transactionHash, side, price

**Blockchain Data:**
- Format: Polygon RPC JSON-RPC
- Events: OrderFilled event logs from CTF Exchange contracts
- Contracts: `0x4bFb41d5B0B7dPEDcD46Q8519fDF50aC2948ee9d` (main), `0x4d97DCd97db8b547914d80FACA3370138D0d8b25` (negRisk)

---

*Integration audit: 2026-02-12*
