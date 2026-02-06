# Phase 1: Foundation - Research

**Researched:** 2026-02-06
**Domain:** Python API data pipeline with SQLite persistence
**Confidence:** MEDIUM

## Summary

This research investigates building a reliable data ingestion pipeline from the Polymarket CLOB API with SQLite persistence. The standard approach combines py-clob-client (official Polymarket library) with SQLAlchemy 2.0 for data modeling, Pydantic for validation, and Tenacity for retry logic. The architecture follows separation of concerns with distinct layers for API client, data validation, and persistence.

Key technical challenges include managing Polymarket's tiered rate limits (varying by endpoint from 60/s sustained to 500/s burst), designing category-agnostic schemas that don't hardcode eSports assumptions, and handling partial/aggregate storage patterns where full detail is stored selectively while summaries capture broader activity.

The research reveals several Polymarket-specific gotchas (stale orderbook data, price validation inconsistencies, decimal precision issues) and SQLite best practices for time-series data (composite indexes on category+timestamp, batch inserts in transactions, careful denormalization for query performance).

**Primary recommendation:** Use a three-layer architecture (API client with Tenacity retry, Pydantic validation models, SQLAlchemy persistence) with configuration-driven category filtering to maintain flexibility as target categories evolve beyond eSports.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**API data scope:**
- Backfill depth: 12 months of trader history when first discovered. Recent enough to evaluate expertise, avoids burning API calls on ancient data.
- Trade fetching strategy: Fetch ALL markets for each trader (needed for category concentration ratio in Phase 4), but only store eSports trades in full detail. Store aggregate summary for non-eSports activity (total volume, trade count, category breakdown).
- Market metadata: Store market metadata alongside trades — question text, end date, outcome, category. Needed downstream for classification (Phase 2) and display (Phase 7).
- Data scope per trade: Full trade records for eSports markets (trader, market, side, size, price, timestamp). Summary-only for non-eSports.

**Design Philosophy:**
- Pipeline must be category-agnostic by design — eSports is the first case study, not a hard-coded assumption. The "fetch all, store eSports detail + summary for rest" pattern should generalize to any category.
- The 12-month backfill window is a starting default, not a hard limit. Should be configurable.

### Claude's Discretion

- Rate limiting strategy (how aggressive, backoff behavior, caching)
- Database schema design (table structure, indexing, denormalization)
- Project/package structure and module boundaries
- Config file format and location
- Error handling for API failures and incomplete data

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| py-clob-client | 0.34.5+ | Polymarket CLOB API | Official Polymarket Python client, maintained by Polymarket team |
| SQLAlchemy | 2.0.46+ | ORM and schema definition | Industry standard Python ORM, 2.0 has unified query API and better async support |
| Pydantic | 2.12.5+ | API response validation | De facto standard for data validation in Python, v2 has significant performance improvements |
| httpx | 0.28.1+ | HTTP client (if needed beyond py-clob-client) | Modern async-capable HTTP client, but py-clob-client handles most API interactions |
| Tenacity | 9.1.3+ | Retry logic with backoff | Apache-licensed retry library with exponential backoff, exception filtering, and flexible stop conditions |
| Loguru | 0.7.3+ | Logging | Zero-config logging with sensible defaults, thread-safe, supports rotation/compression |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars | 1.38.0+ | Data analysis (optional for Phase 1) | If doing data transformations before storage; may be more relevant in later phases |
| python-dotenv | 1.0+ | Environment variable loading | Load API keys and config from .env files |
| dynaconf | 3.2.11+ | Configuration management | If needing multi-environment configs (dev/staging/prod) with YAML/TOML support |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SQLAlchemy | Raw SQLite3 | SQLAlchemy adds ORM overhead but provides migrations, query builder, type safety |
| Tenacity | backoff library | Tenacity has more flexible retry conditions and better async support |
| Loguru | stdlib logging | stdlib requires more configuration but offers finer control over handlers/formatters |
| Pydantic | dataclasses + manual validation | Pydantic provides runtime validation and JSON serialization out of the box |

**Installation:**
```bash
pip install py-clob-client==0.34.5 sqlalchemy==2.0.46 pydantic==2.12.5 tenacity==9.1.3 loguru==0.7.3 python-dotenv==1.0
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── api/                 # API client layer
│   ├── client.py        # py-clob-client wrapper with retry logic
│   ├── rate_limiter.py  # Rate limiting coordination
│   └── models.py        # Pydantic models for API responses
├── db/                  # Database layer
│   ├── models.py        # SQLAlchemy ORM models
│   ├── schema.py        # Table definitions and indexes
│   └── session.py       # Session management
├── pipeline/            # Data pipeline orchestration
│   ├── ingest.py        # Main ingestion logic
│   ├── filters.py       # Category filtering (eSports vs others)
│   └── aggregators.py   # Summary/aggregate calculation
├── config/              # Configuration
│   └── settings.py      # Config loading (env vars, YAML, etc.)
└── utils/
    └── logging.py       # Loguru configuration
```

### Pattern 1: Layered API Client with Retry

**What:** Wrap py-clob-client methods with Tenacity retry decorators to handle transient failures and rate limiting.

**When to use:** For all external API calls where network failures or rate limit throttling can occur.

**Example:**
```python
# Source: Tenacity documentation + py-clob-client examples
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from py_clob_client.client import ClobClient
from py_clob_client.exceptions import PolyApiException
from loguru import logger

class PolymarketClient:
    def __init__(self, host: str, api_key: str = None):
        self.client = ClobClient(host, key=api_key) if api_key else ClobClient(host)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying after {retry_state.outcome.exception()}, attempt {retry_state.attempt_number}"
        )
    )
    def get_markets(self):
        """Fetch markets with automatic retry on transient failures."""
        response = self.client.get_simplified_markets()
        return response.get("data", [])

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError))
    )
    def get_trader_trades(self, trader_address: str):
        """Fetch trade history for a trader with retry logic."""
        # Note: py-clob-client's get_trades() returns user's own trades
        # For other traders, may need to use different endpoint or approach
        return self.client.get_trades()
```

### Pattern 2: Pydantic Validation Models

**What:** Define Pydantic models mirroring API response structure for validation before persistence.

**When to use:** Immediately after receiving API responses to catch malformed data early.

**Example:**
```python
# Source: Pydantic v2 documentation + Polymarket API structure
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from decimal import Decimal

class MarketResponse(BaseModel):
    token_id: str = Field(..., alias="id")
    question: str
    end_date: datetime = Field(..., alias="endDate")
    category: str
    outcome: str | None = None

    @field_validator('end_date', mode='before')
    @classmethod
    def parse_end_date(cls, v):
        # Handle Unix timestamp or ISO string
        if isinstance(v, int):
            return datetime.fromtimestamp(v)
        return v

class TradeResponse(BaseModel):
    market_id: str = Field(..., alias="market")
    trader_address: str = Field(..., alias="trader")
    side: str  # "BUY" or "SELL"
    size: Decimal
    price: Decimal
    timestamp: datetime

    class Config:
        # Allow SQLAlchemy models to be converted
        from_attributes = True

class TraderSummary(BaseModel):
    """Aggregate summary for non-target-category trades."""
    trader_address: str
    category: str
    total_volume: Decimal
    trade_count: int
    first_trade: datetime
    last_trade: datetime
```

### Pattern 3: Category-Agnostic Filter Pipeline

**What:** Use configuration-driven category filtering to separate "detail storage" categories from "summary storage" categories.

**When to use:** During ingestion to determine whether to store full trade details or aggregated summaries.

**Example:**
```python
# Source: Clean Architecture patterns + user requirements
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class CategoryFilter:
    """Configuration for category-based storage strategy."""
    detail_categories: List[str]  # e.g., ["eSports"]
    summary_categories: List[str] | None = None  # None = "everything else"

    def requires_detail_storage(self, category: str) -> bool:
        """Check if category requires full trade detail storage."""
        return category.lower() in [c.lower() for c in self.detail_categories]

    def requires_summary_storage(self, category: str) -> bool:
        """Check if category requires summary/aggregate storage."""
        if self.summary_categories is None:
            # Store summaries for all non-detail categories
            return not self.requires_detail_storage(category)
        return category.lower() in [c.lower() for c in self.summary_categories]

# Usage in pipeline
def process_trader_trades(trades: List[TradeResponse], filter: CategoryFilter):
    """Route trades to detail or summary storage based on category."""
    detail_trades = []
    summary_groups = {}

    for trade in trades:
        if filter.requires_detail_storage(trade.category):
            detail_trades.append(trade)
        elif filter.requires_summary_storage(trade.category):
            # Group for aggregation
            key = (trade.trader_address, trade.category)
            if key not in summary_groups:
                summary_groups[key] = []
            summary_groups[key].append(trade)

    return detail_trades, summary_groups
```

### Pattern 4: SQLAlchemy Composite Indexes for Time Series

**What:** Define composite indexes on (category, timestamp) and (trader_address, timestamp) for efficient querying.

**When to use:** In SQLAlchemy model definitions to optimize range queries and filtering.

**Example:**
```python
# Source: SQLAlchemy 2.0 documentation + time series best practices
from sqlalchemy import Column, String, Integer, DECIMAL, DateTime, Index
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    market_id = Column(String(100), nullable=False)
    trader_address = Column(String(42), nullable=False, index=True)
    category = Column(String(50), nullable=False)
    side = Column(String(4), nullable=False)  # BUY/SELL
    size = Column(DECIMAL(20, 6), nullable=False)
    price = Column(DECIMAL(10, 6), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Composite indexes for efficient queries
    __table_args__ = (
        Index('ix_trader_timestamp', 'trader_address', 'timestamp'),
        Index('ix_category_timestamp', 'category', 'timestamp'),
        Index('ix_market_timestamp', 'market_id', 'timestamp'),
    )

class TraderCategorySummary(Base):
    __tablename__ = "trader_category_summary"

    id = Column(Integer, primary_key=True)
    trader_address = Column(String(42), nullable=False)
    category = Column(String(50), nullable=False)
    total_volume = Column(DECIMAL(20, 6), nullable=False)
    trade_count = Column(Integer, nullable=False)
    first_trade = Column(DateTime, nullable=False)
    last_trade = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('ix_summary_trader_category', 'trader_address', 'category', unique=True),
    )
```

### Pattern 5: Configuration Management with Environment Variables

**What:** Use python-dotenv or dynaconf to manage API keys, rate limits, and category filters via config files.

**When to use:** Always, to keep secrets out of code and make configuration portable across environments.

**Example:**
```python
# Source: Dynaconf/python-dotenv best practices
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # API configuration
    polymarket_api_host: str = "https://clob.polymarket.com"
    polymarket_api_key: str | None = None

    # Rate limiting
    max_requests_per_second: int = 50  # Conservative (80% of 60/s sustained)
    retry_max_attempts: int = 5
    retry_backoff_multiplier: int = 2

    # Data pipeline configuration
    backfill_months: int = 12
    detail_categories: List[str] = ["eSports"]  # Configurable for future expansion

    # Database
    database_url: str = "sqlite:///data/polymarket.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Usage
settings = Settings()
```

### Anti-Patterns to Avoid

- **Hardcoding category names in business logic:** Category filtering should be config-driven, not if/else chains checking for "eSports" strings. Use the CategoryFilter pattern instead.
- **Storing all trades in one table without indexing:** Time-series data without composite indexes leads to slow queries. Always index (trader, timestamp) and (category, timestamp).
- **Retrying forever without backoff:** Can amplify rate limit problems. Always use exponential backoff with maximum attempt limits.
- **Mixing API models with DB models:** Keep Pydantic (API validation) separate from SQLAlchemy (persistence). Use explicit conversion functions.
- **Ignoring Polymarket rate limit tiers:** Different endpoints have different limits. Track per-endpoint rate limits separately.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry logic with exponential backoff | Custom retry loops with sleep() | Tenacity library | Handles edge cases like jitter, exception filtering, async support, retry callbacks |
| API response validation | Manual dict.get() chains | Pydantic models | Type safety, automatic validation, better error messages, JSON schema generation |
| Rate limiting across endpoints | Simple time.sleep() or token bucket | Tenacity + per-endpoint tracking | Polymarket has different limits per endpoint; simple sleep doesn't account for burst vs sustained |
| Database migrations | Manual ALTER TABLE scripts | Alembic (SQLAlchemy migrations) | Tracks migration history, handles rollbacks, works across environments |
| Configuration management | Hardcoded constants or raw os.environ | dynaconf or pydantic-settings | Environment-aware configs, type validation, multiple file format support |
| Logging configuration | print() statements or basic logging.basicConfig() | Loguru | Thread-safe, automatic rotation, structured logging, zero config |
| Decimal/precision handling | float for prices | Decimal type | Floating-point errors accumulate in financial calculations; Decimal provides exact precision |

**Key insight:** Data pipelines have many edge cases (network failures, malformed responses, rate limits, precision errors). Battle-tested libraries handle these better than custom code. Invest time in integration, not reinventing retry logic or validation.

## Common Pitfalls

### Pitfall 1: Polymarket API Stale Data and Inconsistencies

**What goes wrong:** The py-clob-client library has documented issues with stale orderbook data while other endpoints return accurate prices. Price validation also inconsistent (API rejects 0.999 while UI accepts it).

**Why it happens:** Polymarket's CLOB architecture has multiple data sources (orderbook cache vs real-time price feeds) that can desynchronize. Price validation rules differ between frontend and backend.

**How to avoid:**
- Don't rely solely on orderbook endpoints for current prices; cross-reference with `get_price()` or `get_last_trade_price()`
- For price bounds, use 0.01-0.99 range (documented API limits) not 0.01-0.999
- Implement data freshness checks (timestamp comparison) before trusting cached data

**Warning signs:** Orderbook prices don't match recent trade prices; API 400 errors on price validation that work in UI.

### Pitfall 2: SQLite Missing Primary Keys and Poor Indexing

**What goes wrong:** Tables without primary keys or composite indexes on time-series data cause 25-100x slower queries as data grows.

**Why it happens:** SQLite doesn't enforce primary keys by default (allows ROWID). Developers skip indexing during prototyping.

**How to avoid:**
- Always define explicit primary key (INTEGER PRIMARY KEY AUTOINCREMENT)
- Create composite indexes on query patterns: `Index('ix_trader_timestamp', 'trader_address', 'timestamp')`
- Use `EXPLAIN QUERY PLAN` to verify indexes are used

**Warning signs:** Queries slow down dramatically as table grows past 10k rows; EXPLAIN shows "SCAN TABLE" instead of "SEARCH TABLE USING INDEX".

### Pitfall 3: Inadequate Transaction Batching

**What goes wrong:** Inserting trades one-by-one can be 20x slower than batching in transactions. Default autocommit behavior in SQLite commits each statement.

**Why it happens:** SQLAlchemy sessions don't automatically batch inserts; each `session.add()` + `session.commit()` is a separate transaction.

**How to avoid:**
- Batch inserts inside a single transaction: `session.bulk_insert_mappings(Trade, trades_list)`
- Configure SQLAlchemy to use WAL mode for SQLite: `PRAGMA journal_mode=WAL`
- Commit after processing each trader's full history, not after each trade

**Warning signs:** Ingestion takes minutes for hundreds of trades; disk I/O spikes during writes.

### Pitfall 4: Rate Limit Confusion Between Burst and Sustained

**What goes wrong:** Polymarket endpoints have different burst vs sustained rate limits (e.g., POST /order allows 500/s burst but only 60/s sustained). Naive rate limiting hits sustained limits.

**Why it happens:** Developers implement simple "max N requests per second" without accounting for sliding window and sustained rate differences.

**How to avoid:**
- Use conservative sustained rate for planning (60/s for order endpoints, not 500/s burst)
- Implement per-endpoint rate tracking (different limits for /trades, /markets, /order)
- Polymarket uses throttling (queues requests) rather than rejection, but sustained overload still causes delays

**Warning signs:** Requests succeed but latency increases dramatically; responses delayed by seconds instead of milliseconds.

### Pitfall 5: Trader Trade History Scope Mismatch

**What goes wrong:** py-clob-client's `get_trades()` returns the authenticated user's trades, NOT arbitrary trader addresses. Developers expect it to fetch any trader's history.

**Why it happens:** API authentication scope limits data access. Public endpoints don't expose individual trader histories by address.

**How to avoid:**
- Understand py-clob-client scope: `get_trades()` requires authentication and returns only YOUR trades
- To discover other traders: parse market participants from market data, orderbook snapshots, or public trade events
- Store discovered trader addresses and track their market participation indirectly

**Warning signs:** `get_trades()` returns empty list for non-authenticated addresses; API returns 401 Unauthorized when trying to fetch others' data.

### Pitfall 6: Category Hardcoding vs Configuration

**What goes wrong:** Hardcoding `if category == "eSports"` throughout codebase makes it impossible to extend to other categories without code changes.

**Why it happens:** User requirement specifies eSports, developers take the shortcut of literal string comparisons.

**How to avoid:**
- Use CategoryFilter pattern with configuration-driven lists
- Implement strategy pattern: `requires_detail_storage(category)` instead of direct string checks
- Test with multiple categories from day one (even if only eSports is active)

**Warning signs:** grep shows "eSports" string scattered across multiple files; adding a new category requires code changes instead of config changes.

### Pitfall 7: Decimal Precision Loss in Financial Data

**What goes wrong:** Using Python float for prices/volumes causes precision errors that compound over calculations (e.g., 0.1 + 0.2 != 0.3 in float).

**Why it happens:** Binary floating-point cannot exactly represent many decimal fractions.

**How to avoid:**
- Always use `Decimal` type for financial values (prices, volumes, totals)
- Configure SQLAlchemy to use DECIMAL column type: `Column(DECIMAL(20, 6))`
- Configure Pydantic to use Decimal: `price: Decimal`

**Warning signs:** Calculated totals don't match expected values; rounding errors accumulate in aggregations.

## Code Examples

Verified patterns from official sources:

### Initializing py-clob-client (Read-Only Mode)

```python
# Source: https://github.com/Polymarket/py-clob-client
from py_clob_client.client import ClobClient

# Read-only access (no authentication needed for market data)
client = ClobClient("https://clob.polymarket.com")

# Fetch all markets
markets = client.get_simplified_markets()
print(f"Found {len(markets['data'])} markets")
```

### Tenacity Retry with Exponential Backoff

```python
# Source: https://tenacity.readthedocs.io/
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(
        f"Retry attempt {retry_state.attempt_number} after {retry_state.outcome.exception()}"
    )
)
def fetch_with_retry(url: str):
    # Your API call here
    pass
```

### SQLAlchemy 2.0 Batch Insert with Transaction

```python
# Source: SQLAlchemy 2.0 best practices
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

engine = create_engine("sqlite:///data/polymarket.db")
Session = sessionmaker(bind=engine)

def batch_insert_trades(trades_data: list[dict]):
    """Insert trades in a single transaction for 20x speedup."""
    session = Session()
    try:
        # Use bulk_insert_mappings for best performance
        session.bulk_insert_mappings(Trade, trades_data)
        session.commit()
        logger.info(f"Inserted {len(trades_data)} trades")
    except Exception as e:
        session.rollback()
        logger.error(f"Batch insert failed: {e}")
        raise
    finally:
        session.close()
```

### Loguru Configuration with Rotation

```python
# Source: https://loguru.readthedocs.io/
from loguru import logger

# Remove default handler
logger.remove()

# Add console handler with custom format
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO"
)

# Add file handler with rotation and compression
logger.add(
    "logs/pipeline_{time:YYYY-MM-DD}.log",
    rotation="50 MB",    # Rotate when file reaches 50MB
    retention=10,        # Keep last 10 files
    compression="zip",   # Compress rotated files
    level="DEBUG"
)

# Usage
logger.info("Pipeline started")
logger.debug("Fetching markets from API")
logger.error("API call failed", extra={"endpoint": "/markets"})
```

### Pydantic Settings with Environment Variables

```python
# Source: Pydantic documentation
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    polymarket_api_host: str = "https://clob.polymarket.com"
    database_url: str = "sqlite:///data/polymarket.db"
    detail_categories: List[str] = ["eSports"]
    backfill_months: int = 12

    class Config:
        env_file = ".env"
        env_prefix = "POLYMARKET_"  # Loads POLYMARKET_API_HOST, etc.

# .env file:
# POLYMARKET_API_HOST=https://clob.polymarket.com
# POLYMARKET_DATABASE_URL=sqlite:///data/polymarket.db
# POLYMARKET_DETAIL_CATEGORIES=["eSports","Politics"]

settings = Settings()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SQLAlchemy 1.x query() API | SQLAlchemy 2.0 unified select() | SQLAlchemy 2.0 (2023) | Unified ORM and Core query syntax, better type hints |
| Pydantic v1 Config class | Pydantic v2 model_config | Pydantic 2.0 (2023) | 5-50x performance improvement, different validation API |
| requests library for async | httpx library | httpx 1.0 (2021) | Native async/await support, HTTP/2 |
| Custom retry loops | Tenacity library | Standard practice (~2020) | Declarative retry configuration, less boilerplate |
| NullPool for SQLite in SQLAlchemy | QueuePool default | SQLAlchemy 2.0 | Better connection reuse, but need to enable WAL mode |
| Manual rate limiting | Cloudflare throttling (Polymarket) | Polymarket 2024+ | Requests queued instead of rejected, but sustained limits still apply |

**Deprecated/outdated:**
- **SQLAlchemy 1.x query() API:** Still works but deprecated; use `select()` construct instead
- **Pydantic v1:** v2 has breaking changes; check migration guide if using old examples
- **py-clob-client signature_type defaults:** Older versions defaulted to different signature types; explicitly set signature_type

## Open Questions

Things that couldn't be fully resolved:

1. **How to fetch trade history for arbitrary trader addresses?**
   - What we know: py-clob-client's `get_trades()` only returns authenticated user's trades
   - What's unclear: Whether Polymarket API provides public endpoint to query trades by trader address
   - Recommendation: Start by tracking traders discovered from market participation (orderbooks, recent trades on markets). May need to parse blockchain events for complete history.

2. **Exact rate limit consumption per API call type**
   - What we know: Different endpoints have different burst/sustained limits; CLOB uses Cloudflare throttling
   - What's unclear: How rate limits compound across multiple concurrent requests; whether read-only endpoints share rate limit pool
   - Recommendation: Implement conservative rate limiting (80% of documented sustained rates) and monitor response latencies. Add instrumentation to track per-endpoint usage.

3. **Market category taxonomy completeness**
   - What we know: Polymarket has category field on markets; eSports is one category
   - What's unclear: Complete list of categories, whether they're hierarchical, how often taxonomy changes
   - Recommendation: Store category as-is from API (don't normalize immediately). Build custom taxonomy in Phase 2 based on observed categories.

4. **Trade execution fragmentation across transactions**
   - What we know: Large trades may be split into multiple transaction entities with same `market_order` and `match_time`
   - What's unclear: How to reliably reconcile these; whether py-clob-client handles it automatically
   - Recommendation: Store trades as received; handle reconciliation during analysis phase. Index on (market_order, match_time) for grouping.

## Sources

### Primary (HIGH confidence)

- **py-clob-client GitHub:** https://github.com/Polymarket/py-clob-client - Official client library, examples, API patterns
- **Polymarket API Documentation:** https://docs.polymarket.com/quickstart/introduction/rate-limits - Rate limiting tiers and endpoint limits
- **SQLAlchemy 2.0 Documentation:** https://docs.sqlalchemy.org/en/21/core/constraints.html - Index definitions and constraints
- **Tenacity Documentation:** https://tenacity.readthedocs.io/ - Retry strategies and configuration
- **Pydantic Documentation:** https://docs.pydantic.dev/latest/ - Validation patterns (v2)

### Secondary (MEDIUM confidence)

- [Data Pipeline Design Patterns - Start Data Engineering](https://www.startdataengineering.com/post/code-patterns/) - Python pipeline architecture patterns
- [Dagster: Data Pipeline Architecture 5 Design Patterns](https://dagster.io/guides/data-pipeline-architecture-5-design-patterns-with-examples) - Layered architecture patterns
- [API Error Handling & Retry Strategies: Python Guide 2026](https://easyparser.com/blog/api-error-handling-retry-strategies-python-guide) - Retry and backoff patterns
- [Loguru: Complete Guide to Logging](https://betterstack.com/community/guides/logging/loguru/) - Logging best practices
- [SQLite Time Series Best Practices](https://moldstud.com/articles/p-handling-time-series-data-in-sqlite-best-practices) - Indexing strategies for time-series data
- [Common SQLite Pitfalls](https://moldstud.com/articles/p-common-pitfalls-when-working-with-sqlite-database-avoid-these-mistakes-for-better-performance) - Performance issues and solutions
- [Pydantic V2 + SQLAlchemy Integration](https://asim-poptani.medium.com/pydantic-v2-sqlalchemy-alembic-the-proper-way-56aed7847b5b) - Separation of concerns between validation and persistence
- [Python Project Best Practices](https://dagster.io/blog/python-project-best-practices) - Project structure and organization

### Tertiary (LOW confidence)

- [Polymarket API Overview Medium Article](https://medium.com/@gwrx2005/the-polymarket-api-architecture-endpoints-and-use-cases-f1d88fa6c1bf) - General architecture overview (not official)
- [Clean Architecture with Python](https://www.glukhov.org/post/2025/11/python-design-patterns-for-clean-architecture/) - Domain-driven design patterns
- General web search results on Python data pipelines and configuration patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries are official, well-documented, and verified through official docs
- Architecture: MEDIUM - Patterns are well-established but Polymarket-specific integration unverified in production
- Pitfalls: MEDIUM - Documented in GitHub issues and community sources, but not all tested firsthand
- Rate limiting specifics: MEDIUM - Official documentation exists but behavior under load not verified
- Trader history fetching: LOW - Unclear whether arbitrary trader address queries are supported by API

**Research date:** 2026-02-06
**Valid until:** 2026-03-06 (30 days - standard for stable libraries, but verify Polymarket API changes)

**Notes:**
- Polymarket API is actively developed; monitor GitHub issues for py-clob-client
- SQLAlchemy 2.0 and Pydantic v2 have breaking changes from v1; verify version compatibility
- Rate limits may change based on Polymarket's builder tier system
- Category taxonomy may evolve; design for flexibility
