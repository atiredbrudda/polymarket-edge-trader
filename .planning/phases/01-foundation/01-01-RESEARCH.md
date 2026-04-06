# Phase 1: Foundation + Integration Test - Research

**Researched:** 2026-03-29
**Domain:** Python data pipeline foundation, SQLite database management, CLI tooling
**Confidence:** HIGH

## Summary

This research covers the foundational stack for a Python-based trader analytics pipeline that ingests Polymarket data via the Gamma API, stores it in SQLite, and provides CLI commands for data management. The phase focuses on getting database schema, token catalog ingestion, and integration tests working before any real API complexity.

The recommended stack prioritizes developer productivity, correctness, and alignment with modern Python practices. Key decisions: **sqlite-utils** for database operations (not raw sqlite3 or SQLAlchemy), **Click** for CLI (confirmed), **PyYAML** for config, **httpx** for HTTP, **pydantic** for validation, **pytest** for testing, and **aiolimiter** for rate limiting.

**Primary recommendation:** Use sqlite-utils Python API for all database operations—it provides the right abstraction level between raw sqlite3 and full ORM, with built-in WAL mode support, foreign key helpers, and excellent bulk insert patterns.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlite-utils` | 3.39+ (2025-11-24) | SQLite database creation, schema management, bulk inserts | Purpose-built for data pipeline work; handles WAL mode, foreign keys, indexes, bulk operations with minimal code; by Simon Willison (Datasette creator) |
| `click` | 8.3.x | CLI framework | Confirmed in requirements; sensible defaults, automatic help pages, composable commands, lazy subcommand loading |
| `pydantic` | 2.12.5+ | Data validation, config parsing | Most widely used validation library; Rust-backed speed; type-hint driven; excellent error messages; 360M+ monthly downloads |
| `httpx` | Latest | HTTP client | Sync + async APIs; HTTP/1.1 + HTTP/2; connection pooling; timeouts everywhere; requests-compatible API |
| `pyyaml` | 6.x | YAML config parsing | Standard YAML library for Python; safe_load for untrusted data; LibYAML bindings for speed |
| `pytest` | 9.x | Testing framework | Auto-discovery; powerful fixtures; detailed assertion introspection; 1300+ plugins |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiolimiter` | 1.2.1+ | Async rate limiting (leaky bucket) | When implementing async API clients with rate limits |
| `uv` | Latest | Python package/project management | Faster than pip/poetry; universal lockfiles; recommended for new projects |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| sqlite-utils | SQLAlchemy | Overkill for this use case; sqlite-utils is purpose-built for data pipelines, not ORM work |
| sqlite-utils | Raw sqlite3 | More boilerplate; manual connection management; no bulk insert helpers; easy to get wrong |
| httpx | requests | httpx has async support, HTTP/2, better timeout handling; requests is sync-only |
| pydantic | attrs + cattrs | pydantic has better ecosystem integration, JSON Schema support, faster validation |
| aiolimiter | Custom rate limiting | Rate limiting has edge cases (burst handling, concurrent coroutines); aiolimiter is battle-tested |

**Installation:**
```bash
# Using uv (recommended)
uv init polymarket-analytics
uv add sqlite-utils click pydantic httpx pyyaml pytest aiolimiter

# Or using pip
pip install sqlite-utils click pydantic[email] httpx pyyaml pytest aiolimiter
```

## Architecture Patterns

### Recommended Project Structure
```
polymarketv2/
├── pyproject.toml        # Project metadata, dependencies
├── uv.lock               # Universal lockfile (if using uv)
├── niches/
│   ├── esports.yaml      # Niche config: tag_id, slug, min_positions, etc.
│   └── politics.yaml     # Future niches
├── src/
│   └── polymarket_analytics/
│       ├── __init__.py
│       ├── cli.py        # Click CLI entry point
│       ├── commands/     # CLI command modules
│       │   ├── __init__.py
│       │   ├── build_token_catalog.py
│       │   ├── backfill.py
│       │   └── ...
│       ├── db/
│       │   ├── __init__.py
│       │   ├── schema.py   # Table definitions, indexes
│       │   └── connection.py  # DB connection factory
│       ├── gamma/
│       │   ├── __init__.py
│       │   ├── client.py   # Gamma API client
│       │   └── types.py    # Pydantic models for API responses
│       ├── token_catalog/
│       │   ├── __init__.py
│       │   └── builder.py  # Token catalog ingestion logic
│       └── config/
│           ├── __init__.py
│           └── loader.py   # YAML config loading + validation
├── tests/
│   ├── __init__.py
│   ├── conftest.py       # Pytest fixtures
│   ├── test_schema.py
│   ├── test_token_catalog.py
│   ├── test_integration.py  # Integration tests with fixture data
│   └── fixtures/
│       └── gamma_responses/  # Sample API responses
└── .planning/
    └── phases/
        └── 01-foundation/
            ├── 01-RESEARCH.md
            └── ...
```

### Pattern 1: Database Schema Module with sqlite-utils
**What:** Define all 9 tables in a single schema module using sqlite-utils `Database` class
**When to use:** For all database setup, migration, and introspection tasks
**Example:**
```python
# src/polymarket_analytics/db/schema.py
import sqlite_utils
from pathlib import Path

SCHEMA_VERSION = 1

def init_database(db_path: Path) -> sqlite_utils.Database:
    """Initialize database with WAL mode and all tables."""
    db = sqlite_utils.Database(str(db_path))

    # Enable WAL mode for read concurrency (SCHM-02)
    db.enable_wal()

    # Create tables in dependency order
    create_core_tables(db)
    create_indexes(db)

    return db

def create_core_tables(db: sqlite_utils.Database):
    """Create all 9 core tables with correct types and foreign keys."""

    # Token catalog must exist before trades (TCAT-01 dependency)
    db["token_catalog"].create(
        {
            "token_id": str,
            "condition_id": str,
            "question": str,
            "niche_slug": str,
            "node_path": str,
            "created_at": str,  # ISO 8601 timestamp
        },
        pk="token_id",
        foreign_keys=[
            ("condition_id", "markets", "condition_id")  # If markets table exists
        ],
        if_not_exists=True
    )

db["trades"].create(
    {
        "trade_id": str,
        "token_id": str,
        "timestamp": str,
        "side": str,  # "YES" or "NO"
        "price": float,
        "size": float,
        "market_id": str,
    },
    pk="trade_id",
    foreign_keys=[("token_id", "token_catalog", "token_id")],
    if_not_exists=True
)

# ... repeat for all 9 tables: traders, markets, market_entities,
# gamma_events, token_catalog, trades, positions, lift_scores, signals

def create_indexes(db: sqlite_utils.Database):
    """Create indexes for common query patterns."""
    # Token catalog lookups
    db["token_catalog"].create_index(["condition_id"], if_not_exists=True)
    db["token_catalog"].create_index(["niche_slug"], if_not_exists=True)

    # Trade queries
    db["trades"].create_index(["token_id"], if_not_exists=True)
    db["trades"].create_index(["market_id"], if_not_exists=True)
    db["trades"].create_index(["timestamp"], if_not_exists=True)

# Source: sqlite-utils documentation - https://sqlite-utils.datasette.io/en/stable/python-api.html
```

### Pattern 2: Click CLI with --niche Flag
**What:** All CLI commands accept `--niche` flag for YAML config lookup
**When to use:** For all user-facing commands
**Example:**
```python
# src/polymarket_analytics/cli.py
import click
from pathlib import Path

@click.group()
@click.option(
    "--niche",
    default="esports",
    help="Niche slug for config lookup (default: esports)",
)
@click.pass_context
def cli(ctx, niche: str):
    """Polymarket trader analytics pipeline."""
    ctx.ensure_object(dict)
    ctx.obj["niche"] = niche

    # Load niche config
    config_path = Path(__file__).parent.parent.parent / "niches" / f"{niche}.yaml"
    if not config_path.exists():
        raise click.ClickException(f"Niche config not found: {config_path}")

    import yaml
    with open(config_path) as f:
        ctx.obj["config"] = yaml.safe_load(f)

@click.command()
@click.option("--db-path", default="data/analytics.db")
@click.pass_context
def build_token_catalog(ctx, db_path: str):
    """Build token catalog from Gamma API before trade ingestion."""
    config = ctx.obj["config"]
    # ... implementation

# Source: Click documentation - https://click.palletsprojects.com/en/stable/
```

### Pattern 3: Pydantic Config Validation
**What:** Validate YAML config structure with pydantic models
**When to use:** For all configuration loading
**Example:**
```python
# src/polymarket_analytics/config/loader.py
from pydantic import BaseModel, Field
from pathlib import Path
import yaml

class NicheConfig(BaseModel):
    """Validated niche configuration."""
    tag_id: str = Field(..., description="Polymarket tag ID")
    slug: str = Field(..., description="Niche slug for file naming")
    min_positions: int = Field(default=10, ge=1)
    scoring_window_days: int = Field(default=30, ge=1)
    entity_fields: list[str] = Field(default_factory=list)

def load_niche_config(config_path: Path) -> NicheConfig:
    """Load and validate niche config."""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return NicheConfig(**data)

# Source: Pydantic documentation - https://docs.pydantic.dev/latest/
```

### Anti-Patterns to Avoid
- **Don't use raw sqlite3 for schema management** - Too much boilerplate for table creation, foreign keys, indexes. sqlite-utils handles this cleanly.
- **Don't enable WAL mode per-connection** - Enable it once at database creation time; it's persistent across connections.
- **Don't validate config manually** - Use pydantic; manual validation misses edge cases and produces worse error messages.
- **Don't create CLI commands without --niche flag** - All commands must support niche-scoped operation per requirements.

## Gamma API Notes

**Status:** Official Gamma API documentation not found via web search. Research based on project context and Polymarket ecosystem knowledge.

**Known from project context:**
- Gamma API provides token/condition metadata for building token catalog
- Token catalog must be built BEFORE trade ingestion (TCAT-01)
- Each token_id maps to: condition_id, question, niche_slug, node_path (TCAT-02)
- API responses need validation with pydantic models

**Recommended approach:**
1. Start with fixture data for initial development
2. Create pydantic models based on actual API responses once available
3. Implement token catalog builder with mock data first, then swap in real API client

**Open question:** Gamma API endpoint structure and authentication method needs verification from Polymarket documentation or API discovery.

## Schema Design Considerations

### 9 Core Tables (SCHM-01)
Based on requirements, the 9 tables are:

1. **traders** - User accounts, wallet addresses, metadata
2. **markets** - Market definitions, outcomes, resolution status
3. **market_entities** - Extracted entities (teams, players, games) per niche
4. **gamma_events** - Raw Gamma API event log
5. **token_catalog** - Token → condition mapping (built before trades)
6. **trades** - Individual trade records
7. **positions** - Aggregated trader positions
8. **lift_scores** - Computed lift scores for signal detection
9. **signals** - Generated trading signals/alerts

### Key Design Decisions

**Foreign Keys:**
- Enable foreign keys at connection time: `PRAGMA foreign_keys = ON`
- Define foreign keys in table creation for referential integrity
- Create indexes on foreign key columns for JOIN performance

**Primary Keys:**
- Use string IDs (not integers) for all tables - Polymarket uses string IDs
- Consider hash-based IDs for deduplication (sqlite-utils `hash_id` option)

**Timestamps:**
- Store as ISO 8601 strings (sqlite-utils default for datetime)
- Enables sorting and range queries without conversion

**WAL Mode (SCHM-02):**
- Enable once at database creation: `db.enable_wal()`
- Provides read concurrency (readers don't block writers)
- Persistent setting - survives connection closes
- Creates `-wal` and `-shm` files alongside main database
- **Important:** All processes must be on same host (WAL doesn't work over network filesystems)

**Source:** SQLite WAL documentation - https://www.sqlite.org/wal.html

## Testing Approach

### Fixture Data Strategy
**What:** Use static fixture files for Gamma API responses and expected database state
**When to use:** For all unit and integration tests
**Structure:**
```
tests/fixtures/
├─ gamma_responses/
│  ├─ token_catalog_esports.json
│  └─ trades_page_1.json
├─ expected_db/
│  └─ after_token_catalog.sql  # SQL dump of expected state
└─ niche_configs/
   └─ esports_test.yaml
```

### Integration Test Pattern (TCAT-03)
**What:** Test that fixture data ingestion produces zero synthetic market_ids
**Example:**
```python
# tests/test_integration.py
import pytest
import sqlite_utils
from pathlib import Path

@pytest.fixture
def test_db(tmp_path: Path) -> sqlite_utils.Database:
    """Create in-memory test database with schema."""
    db_path = tmp_path / "test.db"
    db = sqlite_utils.Database(str(db_path))
    db.enable_wal()
    # ... create tables
    return db

def test_zero_synthetic_market_ids(test_db: sqlite_utils.Database):
    """TCAT-03: Assert zero synthetic market_ids in trades table."""
    # Ingest fixture data
    ingest_fixture_trades(test_db, "tests/fixtures/gamma_responses/trades_fixture.json")

    # Count synthetic IDs (market_ids not in token_catalog)
    result = test_db.execute("""
        SELECT COUNT(*) FROM trades t
        LEFT JOIN token_catalog tc ON t.token_id = tc.token_id
        WHERE tc.token_id IS NULL
    """).fetchone()[0]

    assert result == 0, f"Found {result} trades with synthetic market_ids"

# Source: pytest documentation - https://docs.pytest.org/en/stable/
```

### pytest Fixtures
**Key fixtures to implement:**
- `test_db` - Fresh database per test with schema applied
- `niche_config` - Loaded and validated test config
- `gamma_client_mock` - Mocked HTTP client returning fixture data
- `sample_token_catalog` - Pre-populated token catalog for trade tests

## Common Pitfalls to Avoid

### Pitfall 1: SQLite Foreign Keys Not Enforced
**What goes wrong:** Foreign keys defined but not enforced, allowing orphaned records
**Why it happens:** SQLite requires `PRAGMA foreign_keys = ON` per connection
**How to avoid:** Enable in connection factory:
```python
def get_connection(db_path: Path) -> sqlite_utils.Database:
    db = sqlite_utils.Database(str(db_path))
    db.execute("PRAGMA foreign_keys = ON")
    return db
```
**Warning signs:** Tests pass but production data has integrity issues

### Pitfall 2: WAL Mode Not Persistent
**What goes wrong:** WAL mode disabled after application restart
**Why it happens:** Assuming WAL mode is per-connection instead of per-database
**How to avoid:** Call `db.enable_wal()` once at database creation; it persists
**Warning signs:** `-wal` file disappears after restart; concurrent reads block

### Pitfall 3: Synthetic Market ID Poisoning
**What goes wrong:** Trades table contains market_ids not in token_catalog
**Why it happens:** Ingesting trades before building complete token catalog
**How to avoid:**
1. Build token_catalog BEFORE any trade ingestion (TCAT-01)
2. Add foreign key from trades.token_id → token_catalog.token_id
3. Integration test asserts zero synthetic IDs (TCAT-03)
**Warning signs:** `SELECT COUNT(*) FROM trades WHERE token_id NOT IN (SELECT token_id FROM token_catalog)` returns > 0

### Pitfall 4: YAML Config Silent Failures
**What goes wrong:** Missing config fields use wrong defaults or cause runtime errors
**Why it happens:** Manual config loading without validation
**How to avoid:** Use pydantic models with required fields
**Warning signs:** `KeyError` at runtime; wrong niche data loaded

### Pitfall 5: CLI Commands Without Context
**What goes wrong:** Commands can't access niche config or database connection
**Why it happens:** Not using Click's `@click.pass_context`
**How to avoid:** Use context object for shared state
**Warning signs:** Commands reinvent config loading; inconsistent behavior

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|-------|------|-------|-----|
| Table creation with foreign keys | Raw `CREATE TABLE` SQL strings | sqlite-utils `.create()` with `foreign_keys` param | Handles quoting, type mapping, `if_not_exists`, index creation |
| Bulk inserts from JSON | Manual `executemany` loops | sqlite-utils `.insert_all()` or `.upsert_all()` | Handles type detection, batching, progress reporting |
| WAL mode setup | Manual `PRAGMA journal_mode=WAL` | sqlite-utils `db.enable_wal()` | Checks success, handles edge cases |
| YAML config validation | Manual `dict` key checks | pydantic `BaseModel` validation | Better error messages, type coercion, nested validation |
| HTTP client with retries | Manual `requests.get` with retry loops | httpx with `RetryTransport` or custom middleware | Proper backoff, connection pooling, timeout handling |
| Rate limiting | Custom time-based counters | aiolimiter `AsyncLimiter` | Leaky bucket algorithm, handles concurrent coroutines correctly |
| CLI help pages | Manual `--help` implementation | Click decorators | Auto-generated, consistent formatting, shell completion |

**Key insight:** Foundation work has many "easy" tasks that have subtle edge cases. Using battle-tested libraries prevents wasting time on problems that are already solved.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|-------|------|-------|-----|
| SQLAlchemy for all DB work | sqlite-utils for data pipelines | ~2019 | Simpler code, faster development, no ORM overhead |
| argparse for CLI | Click | ~2015 | Composable commands, better UX, automatic help |
| Manual config validation | pydantic | ~2020 | Type-safe configs, better error messages |
| requests for HTTP | httpx | ~2020 | Async support, HTTP/2, better timeouts |
| pytest fixtures as functions | pytest fixtures with scopes | ~2018 | Better resource management, test isolation |

**Deprecated/outdated:**
- `yaml.load()` without `Loader=SafeLoader` - Security risk; use `yaml.safe_load()`
- Raw sqlite3 without connection pooling - sqlite-utils manages connections
- Manual transaction management - Use sqlite-utils context managers or explicit `db.commit()`

## Open Questions

1. **Gamma API Endpoint Structure**
   - What we know: Gamma API provides token/condition data for token catalog
   - What's unclear: Exact endpoints, authentication method, rate limits, response format
   - Recommendation: Start with fixture data; implement adapter pattern to swap in real API client later

2. **Polymarket Tag IDs**
   - What we know: eSports is first niche; needs `tag_id` in config
   - What's unclear: Complete list of known tag IDs for documentation
   - Recommendation: Document tag IDs as discovered; make config extensible for new tags

3. **Sync vs Async for Phase 1**
   - What we know: aiolimiter is async; httpx supports both
   - What's unclear: Whether Phase 1 needs async at all (may be overkill for initial implementation)
   - Recommendation: Start sync for simplicity; design interfaces to support async later if needed

## Sources

### Primary (HIGH confidence)
- **sqlite-utils 3.39** - https://sqlite-utils.datasette.io/en/stable/ - Table creation, WAL mode, foreign keys, bulk inserts
- **Click 8.3.x** - https://click.palletsprojects.com/en/stable/ - CLI patterns, context passing, option decorators
- **Pydantic 2.12.5** - https://docs.pydantic.dev/latest/ - Config validation, BaseModel patterns
- **httpx** - https://www.python-httpx.org/ - HTTP client patterns, async support
- **PyYAML** - https://www.pyyaml.org/wiki/PyYAMLDocumentation - safe_load, config parsing
- **pytest 9.x** - https://docs.pytest.org/en/stable/ - Fixtures, integration test patterns
- **SQLite WAL mode** - https://www.sqlite.org/wal.html - WAL behavior, checkpointing, concurrency
- **Python sqlite3 module** - https://docs.python.org/3/library/sqlite3.html - DB-API 2.0 reference
- **aiolimiter 1.2.1** - https://pypi.org/project/aiolimiter/ - Rate limiting patterns

### Secondary (MEDIUM confidence)
- **uv package manager** - https://docs.astral.sh/uv/ - Python project management (alternative to pip/poetry)

### Tertiary (LOW confidence)
- **Gamma API structure** - No official documentation found; based on project context and Polymarket ecosystem knowledge. **Needs verification.**

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** - All libraries verified via official documentation
- Architecture: **HIGH** - Patterns from official docs and established best practices
- Pitfalls: **HIGH** - Based on documented SQLite behavior and library characteristics
- Gamma API: **LOW** - No official documentation found; based on project context only

**Research date:** 2026-03-29
**Valid until:** 2026-06-29 (90 days for stable libraries; Gamma API details may change)
