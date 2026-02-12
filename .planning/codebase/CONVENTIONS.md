# Coding Conventions

**Analysis Date:** 2026-02-12

## Naming Patterns

**Files:**
- Lowercase with underscores: `client.py`, `rate_limiter.py`, `ingest.py`
- Test files: `test_*.py` (e.g., `test_api_client.py`)
- Module packages: Single word or underscore-separated (e.g., `src/api/`, `src/blockchain/`)

**Functions:**
- snake_case: `discover_esports_traders()`, `ingest_active_markets()`, `calculate_expertise_score()`
- Prefixed with action verbs: `get_`, `calculate_`, `discover_`, `validate_`, `route_`, `aggregate_`
- Test functions: `test_<what>_<expected_behavior>` (e.g., `test_market_response_validates_complete_data()`)

**Variables:**
- snake_case throughout: `trader_address`, `session_factory`, `market_id`, `total_volume`
- Abbreviated for addresses: `trader_address[:8]` in logs to shorten hex display
- Type hints included: `trader_address: str`, `session: Session`

**Types:**
- PascalCase for classes: `PolymarketClient`, `IngestionPipeline`, `CategoryFilter`, `MarketResponse`
- Type hints use modern union syntax: `str | None` instead of `Optional[str]`
- Dataclass names: `ExpertiseScoreResult`, `TradeWithCategory`

**Constants:**
- UPPERCASE: `MAX_REQUESTS_PER_SECOND`, `MIN_RESOLVED_MARKETS`, `RECENCY_HALF_LIFE_DAYS`
- Defined at module level in settings/config files

## Code Style

**Formatting:**
- No explicit linter/formatter configuration found (no .black, .ruff, .isort files)
- Implicit style: 4-space indentation, PEP 8 compatible
- Lines: Reasonable length, function bodies organized logically

**Linting:**
- Not configured at repo level
- Type hints enforced through Pydantic models and sqlalchemy.orm.Mapped
- SQLAlchemy 2.0 style with type hints: `Mapped[str]`, `Mapped[Decimal]`

## Import Organization

**Order:**
1. Standard library: `from datetime import datetime`, `from decimal import Decimal`, `from typing import Any`
2. Third-party packages: `from pydantic import BaseModel`, `from sqlalchemy import select`, `from loguru import logger`
3. Relative imports: `from src.api.client import PolymarketClient`, `from src.db.models import Market`

**Path Aliases:**
- Direct imports from src root: `from src.api.models import MarketResponse`
- No aliases like `@` or path mappings configured

**Pattern in client.py** (example):
```python
from typing import Callable, List, TypeVar

import httpx
from loguru import logger
from py_clob_client.client import ClobClient
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.api.models import MarketResponse, TradeResponse
from src.api.rate_limiter import RateLimiter
from src.config.settings import Settings, get_settings
```

## Error Handling

**Patterns:**
- Try/except blocks with specific logging: `logger.error(f"Failed to ingest markets: {e}")`
- Re-raise after logging: `except Exception as e: logger.error(...); raise`
- Graceful failure for non-critical operations: `except Exception: logger.warning(...)` (skip and continue)
- Tenacity for retry logic with exponential backoff on transient errors (ConnectionError, TimeoutError, HTTPError)
- Custom errors: `ValueError` raised with descriptive messages (e.g., "Blockchain client not configured")

**Example from ingest.py:**
```python
try:
    # Operation
except Exception as e:
    logger.error(f"Failed to ingest traders: {e}")
    raise
```

**Alert delivery pattern** (non-critical):
```python
try:
    # Send alert
except Exception:
    logger.warning("Failed to send alert")  # Continue pipeline, don't block
```

## Logging

**Framework:** loguru

**Patterns:**
- `logger.info()` for major operations: "Starting active market ingestion"
- `logger.debug()` for detailed flow: "Fetching markets (active=True, cursor=...)"
- `logger.warning()` for recoverable issues: "Market not found in database"
- `logger.error()` for exceptions: "Failed to ingest markets: {e}"

**Usage locations:**
- `src/api/client.py`: Rate limit initialization, retry warnings
- `src/pipeline/ingest.py`: Ingestion milestones, trade processing counts
- All major pipeline methods log start/completion with counts

## Comments

**When to Comment:**
- Complex business logic requiring explanation (e.g., category derivation from tags, concentration calculations)
- Non-obvious design decisions (e.g., "Cursor-based pagination terminates on next_cursor == 'LTE'")
- Workarounds or temporary code (marked with TODO)

**TODOs found:**
- `src/pipeline/ingest.py`: "TODO: Remove this after debugging" (testing mode)
- `src/graph/converters.py`: "TODO: Decode condition_id from assetId if needed"
- `src/evaluation/__init__.py`: "TODO: Uncomment when metrics module implemented"

**Docstrings:**
- Google-style format (Args, Returns, Raises sections)
- Present on all public methods and classes
- Indented with module docstring at top explaining purpose

**Example from client.py:**
```python
def _retry_call(self, func: Callable[[], T]) -> T:
    """Execute a function with retry logic.

    Args:
        func: Callable to execute with retry

    Returns:
        Result of function call

    Raises:
        RetryError: If all retry attempts exhausted
    """
```

## Function Design

**Size:**
- Range: 15-100 lines, organized by purpose
- Larger methods break into helper methods (e.g., `ingest_active_markets()` uses `_fetch_markets()`)
- Pipeline methods structured with clear steps in order

**Parameters:**
- Type hints mandatory: `trader_address: str`, `session: Session`
- Optional parameters with defaults: `active: bool = True`, `taxonomy_path: Optional[Path] = None`
- No long parameter lists (max 4-5, else use dataclass)

**Return Values:**
- Explicit return type hints: `-> List[MarketResponse]`, `-> int`, `-> Tuple[...]`
- Consistent return types (no fallback to None without annotating)
- Methods return counts/lists, not side-effect-only None

**Example function from aggregators.py:**
```python
def aggregate_trades(trades: list[Any], trader_address: str, category: str) -> dict:
    """Aggregate a list of trades into a category summary.

    Args:
        trades: List of TradeResponse objects
        trader_address: Trader wallet address
        category: Category name for this trade group

    Returns:
        Dict compatible with TraderCategorySummary model
    """
```

## Module Design

**Exports:**
- Classes and functions at module level: `PolymarketClient`, `IngestionPipeline`, `discover_esports_traders()`
- Private methods prefixed with underscore: `_retry_call()`, `_fetch_markets()`
- No explicit `__all__` but imports follow module structure

**Barrel Files:**
- Minimal use; mostly direct imports: `from src.api.client import PolymarketClient`
- `src/api/__init__.py`: Empty or minimal, imports not re-exported

**Example structure:**
```python
# src/api/client.py - Public API
class PolymarketClient:
    def get_markets(self) -> List[MarketResponse]: ...
    def _retry_call(self, func) -> T: ...  # Private

# Tests import directly
from src.api.client import PolymarketClient
```

## Pydantic Models

**Pattern:**
- Inherit from `BaseModel`
- Use `model_config = ConfigDict(...)` for Pydantic v2 settings
- Field validators with `@field_validator` or `@model_validator`
- Type hints on all fields: `condition_id: str`, `size: Decimal`
- Optional fields: `end_date: datetime | None = None`

**Example from models.py:**
```python
class MarketResponse(BaseModel):
    """Market data from Polymarket CLOB API."""

    condition_id: str
    question: str
    end_date_iso: str | None = None
    category: str | None = None
    active: bool

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def derive_category_from_tags(self) -> "MarketResponse": ...
```

## SQLAlchemy ORM Style

**Models:**
- SQLAlchemy 2.0 declarative with `Mapped` type hints
- Column definitions: `mapped_column(String(100), nullable=False)`
- Numeric precision: `Numeric(20, 6)` for volumes, `Numeric(10, 6)` for prices
- Timestamps with defaults: `default=datetime.utcnow`

**Queries:**
- Use `select()` syntax: `select(Market).where(...)`
- Leverage composite indexes for time-series queries
- Join tables with SQLAlchemy ORM relationships

**Example from models.py:**
```python
class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
```

## Dataclass Usage

**Pattern:**
- Frozen dataclasses for immutability: `@dataclass(frozen=True)`
- Simple data containers: `ExpertiseScoreResult`, `TradeWithCategory`
- No methods, only data attributes

**Example:**
```python
@dataclass
class TradeWithCategory:
    """Associates a trade with its market's category."""
    trade: Any  # TradeResponse
    category: str
```

---

*Convention analysis: 2026-02-12*
