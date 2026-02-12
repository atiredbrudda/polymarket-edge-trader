# Phase 9: Jon Becker Dataset Integration - Research

**Researched:** 2026-02-12
**Domain:** DuckDB + Parquet + Historical Data Integration
**Confidence:** HIGH

## Summary

Phase 9 integrates Jon Becker's 33.5GB Parquet dataset containing complete Polymarket trade history (2020-2026) as a backup/research tier for historical analysis. The dataset provides offline querying capability and completes the 3-tier data hierarchy: **The Graph (primary) → JBecker Dataset (research) → Blockchain (backup)**.

The handoff document provides 12,000 words of comprehensive research covering dataset structure, DuckDB querying, schema normalization, and integration strategy. This research document focuses on **implementation-specific patterns** needed by the planner: DuckDB Python API usage, parameterization, testing without the full dataset, error handling, and code conventions.

**Primary recommendation:** Use DuckDB with parameterized queries for safe, performant Parquet querying. Create small test fixtures (5-10MB) for CI/CD. Follow existing converter patterns from Graph/Blockchain integrations. Batch insert trades in 1,000-trade chunks for performance.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| duckdb | latest (0.10+) | Columnar query engine for Parquet | 10-100x faster than pandas, SQL interface, filter pushdown |
| pydantic | 2.12.5+ | Schema validation | Already used project-wide for API models |
| sqlalchemy | 2.0.46+ | ORM and database access | Already used project-wide for persistence |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pyarrow | latest | Write test Parquet fixtures | Test fixture generation only |
| pandas | latest (optional) | Test data generation | Creating sample Parquet files for tests |
| pytest-mock | latest | Mock DuckDB in tests | Unit testing without real dataset |

### Already Available (No New Dependencies)
- loguru (logging)
- decimal.Decimal (financial precision)
- datetime (timestamp handling)
- pathlib.Path (file path management)

**Installation:**
```bash
# Add to pyproject.toml dependencies
pip install duckdb pyarrow  # pyarrow only needed for dev/test
```

**Note:** DuckDB is the ONLY new production dependency. Pyarrow only needed for creating test fixtures.

## Architecture Patterns

### Recommended Project Structure
```
src/
├── datasources/
│   ├── __init__.py
│   ├── jbecker.py           # NEW: JBeckerDataset class
│   └── converters.py        # NEW: jbecker_trade_to_api_response()
├── pipeline/
│   └── ingest.py            # EXTEND: Add ingest_trader_history_jbecker()
└── cli/
    └── commands.py          # EXTEND: Add research/batch-analyze commands

tests/
├── datasources/
│   ├── test_jbecker.py      # NEW: DuckDB query tests
│   └── test_converters.py   # NEW: Schema conversion tests
└── fixtures/
    └── jbecker_sample.parquet  # NEW: 5-10MB sample for testing
```

### Pattern 1: DuckDB Query with Parameterization (CRITICAL)

**What:** DuckDB supports parameterized queries using `$1`, `$2` syntax or named parameters `$param_name`.

**When to use:** ALWAYS when querying with user-supplied values (trader addresses, market IDs).

**Why:** Prevents SQL injection, improves query plan caching, follows security best practices.

**Example:**
```python
import duckdb

def query_trader_history(data_path: str, trader_address: str) -> list[dict]:
    """Query all trades for a trader using parameterized query.

    CRITICAL: Use parameterization to prevent SQL injection.
    DuckDB supports $1, $2 positional or $param named parameters.
    """
    # GOOD: Parameterized query (secure)
    query = """
        SELECT
            id, maker, taker, makerAmountFilled, takerAmountFilled,
            makerAssetId, takerAssetId, timestamp, blockNumber, price
        FROM read_parquet($1)
        WHERE LOWER(maker) = LOWER($2) OR LOWER(taker) = LOWER($2)
        ORDER BY timestamp DESC
    """

    # Execute with parameters (NOT string interpolation!)
    result = duckdb.execute(query, [f"{data_path}/trades/trades_*.parquet", trader_address])

    # Convert to list of dicts
    return result.fetchdf().to_dict('records')

# BAD: String interpolation (SQL injection risk!)
# query = f"... WHERE maker = '{trader_address}' ..."  # NEVER DO THIS
```

**Sources:**
- [DuckDB Prepared Statements](https://duckdb.org/docs/stable/sql/query_syntax/prepared_statements)
- [Parameterized queries prevent SQL injection](https://woteq.com/how-to-run-parameterized-queries-in-duckdb-with-python-to-prevent-sql-injection/)

### Pattern 2: Filter Pushdown Optimization

**What:** DuckDB automatically pushes WHERE filters into Parquet scan, reading only matching row groups.

**When to use:** Always prefer SQL WHERE clauses over Python filtering.

**Example:**
```python
# GOOD: Filter in SQL (pushdown to Parquet scan)
query = """
    SELECT * FROM read_parquet('trades_*.parquet')
    WHERE LOWER(maker) = LOWER($1)
    AND timestamp > $2
"""
result = duckdb.execute(query, [trader_address, cutoff_timestamp])

# BAD: Load all data then filter in Python
df = duckdb.execute("SELECT * FROM read_parquet('trades_*.parquet')").fetchdf()
filtered = df[(df['maker'].str.lower() == trader_address.lower())]  # Slow!
```

**Why filter pushdown matters:**
- Only matching row groups loaded into memory (10-100x faster)
- Parquet stores min/max statistics per row group (enables skipping)
- Columnar format: only SELECT columns read from disk

**Sources:**
- [DuckDB Parquet Tips](https://duckdb.org/docs/stable/data/parquet/tips)
- [Filter pushdown feels like magic](https://medium.com/@connect.hashblock/duckdb-parquet-pushdown-feels-like-magic-65f46276678a)

### Pattern 3: Case-Insensitive Address Matching

**What:** Ethereum addresses are case-sensitive (checksummed), but users may query with any case.

**When to use:** All trader address queries.

**Example:**
```python
# Use LOWER() for case-insensitive matching
query = """
    SELECT * FROM read_parquet($1)
    WHERE LOWER(maker) = LOWER($2) OR LOWER(taker) = LOWER($2)
"""

# Alternative: ILIKE operator (case-insensitive LIKE)
# But LOWER() is more explicit and works with = operator
```

**Sources:**
- [DuckDB Pattern Matching](https://duckdb.org/docs/stable/sql/functions/pattern_matching)
- [DuckDB case sensitivity rules](https://aidoczh.com/duckdb/docs/archive/0.9/sql/case_sensitivity.html)

### Pattern 4: Schema Converter Pattern (Existing Convention)

**What:** Convert external schema to TradeResponse format for pipeline compatibility.

**When to use:** When integrating any new data source (Graph, Blockchain, JBecker).

**Example from existing Graph converter:**
```python
# src/graph/converters.py
def graph_trade_to_api_response(graph_trade: dict, trader_address: str) -> TradeResponse:
    """Convert Graph OrderFilledEvent to API TradeResponse format."""

    # 1. Normalize trader role (maker/taker)
    trader_address = trader_address.lower()
    maker = graph_trade["maker"].lower()
    is_maker = (trader_address == maker)

    # 2. Convert amounts (6 decimals → Decimal)
    maker_amount = Decimal(graph_trade["makerAmountFilled"]) / Decimal("1000000")
    taker_amount = Decimal(graph_trade["takerAmountFilled"]) / Decimal("1000000")

    # 3. Determine trader's side and size
    if is_maker:
        size = maker_amount
        side = graph_trade["side"]
    else:
        size = taker_amount
        side = "SELL" if graph_trade["side"] == "BUY" else "BUY"

    # 4. Convert timestamp
    timestamp = datetime.fromtimestamp(int(graph_trade["timestamp"]))

    # 5. Return TradeResponse (validated by Pydantic)
    return TradeResponse(
        id=graph_trade["id"],
        market=market_id,  # May need enrichment
        trader=trader_address,
        side=side,
        size=size,
        price=Decimal(graph_trade["price"]),
        timestamp=timestamp,
        asset_ticker=asset_ticker,
    )
```

**For JBecker dataset:**
- Schema is nearly identical to Graph (both from blockchain events)
- Main difference: JBecker has explicit `side` field (BUY/SELL)
- Reuse same conversion logic: amounts, timestamps, role determination

### Pattern 5: Batch Insertion for Performance

**What:** Insert trades in batches instead of one-by-one.

**When to use:** When ingesting large trade histories (1,000+ trades).

**Example from existing pipeline:**
```python
# Current pattern uses batch_size=100 for API ingestion
# For JBecker (larger datasets), use batch_size=1000

def ingest_trader_history_jbecker(self, trader_address: str) -> dict:
    """Ingest trader history from JBecker dataset."""

    # Query all trades from DuckDB
    jbecker_trades = self.jbecker_client.query_trader_history(trader_address)

    # Convert to TradeResponse objects
    trade_responses = [
        jbecker_trade_to_api_response(trade, trader_address)
        for trade in jbecker_trades
    ]

    # Batch insert (1000 trades at a time)
    batch_size = 1000
    for i in range(0, len(trade_responses), batch_size):
        batch = trade_responses[i:i+batch_size]

        for trade_response in batch:
            # Deduplication check
            existing = session.query(Trade).filter_by(trade_id=trade_response.id).first()
            if not existing:
                session.add(Trade(...))

        session.commit()  # Commit after each batch
```

### Pattern 6: Graceful Degradation for Missing Dataset

**What:** Handle missing dataset without crashing entire pipeline.

**When to use:** Always check dataset availability before querying.

**Example:**
```python
from pathlib import Path
import duckdb

class JBeckerDataset:
    def __init__(self, data_path: str):
        self.data_path = Path(data_path)
        self.trades_path = self.data_path / "polymarket" / "trades"

    def is_available(self) -> bool:
        """Check if dataset exists and has Parquet files."""
        if not self.trades_path.exists():
            return False

        # Check for at least one Parquet file
        parquet_files = list(self.trades_path.glob("trades_*.parquet"))
        return len(parquet_files) > 0

    def query_trader_history(self, trader_address: str) -> list[dict]:
        """Query trader history with graceful failure."""
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found at {self.data_path}. "
                f"Download from https://s3.jbecker.dev/data.tar.zst"
            )

        # Proceed with query...
```

**Error message pattern:**
```python
# CLI command should catch and display user-friendly message
try:
    trades = pipeline.ingest_trader_history_jbecker(address)
except FileNotFoundError as e:
    console.print(f"[red]Dataset not available:[/red] {e}")
    console.print("\n[yellow]To use JBecker dataset:[/yellow]")
    console.print("1. Download: wget https://s3.jbecker.dev/data.tar.zst")
    console.print("2. Extract: tar --use-compress-program=zstd -xvf data.tar.zst")
    console.print("3. Set JBECKER_DATA_PATH in .env")
    return
```

**Sources:**
- [DuckDB file not found error handling](https://github.com/duckdb/duckdb/issues/13782)
- [Python graceful degradation patterns](https://medium.com/@RampantLions/robust-error-handling-in-python-tracebacks-graceful-degradation-and-suppression-11f7a140720b)

### Anti-Patterns to Avoid

- **Loading entire Parquet into memory:** Use SQL queries, not `df = read_parquet().to_pandas()`
- **String concatenation for queries:** Always use parameterized queries (`$1`, `$2`)
- **Float precision for financial data:** Use `Decimal` for volumes and prices (already project standard)
- **Assuming dataset exists:** Always check `is_available()` before querying
- **One-by-one insertion:** Batch insert 1,000 trades at a time for 10x speedup

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parquet querying | Custom Parquet parser, pandas filtering | DuckDB with SQL | Filter pushdown, columnar optimization, 10-100x faster |
| SQL parameterization | Manual string escaping | DuckDB `$1, $2` parameters | Prevents SQL injection, handles edge cases |
| Schema validation | Manual dict validation | Pydantic TradeResponse | Type safety, automatic coercion, clear error messages |
| Test Parquet files | Hand-crafted binary files | PyArrow write_table() | Correct format, easy to maintain, readable Python code |
| Batch insertion | Manual transaction management | SQLAlchemy session.commit() per batch | Handles rollback, foreign keys, constraints |

**Key insight:** DuckDB is a specialized tool for Parquet. Don't try to build custom solutions - use DuckDB's filter pushdown, columnar access, and SQL interface. It's orders of magnitude faster than any hand-rolled solution.

## Common Pitfalls

### Pitfall 1: SQL Injection via String Interpolation

**What goes wrong:** Using f-strings or `.format()` to insert user input into queries.

**Why it happens:** Developers familiar with pandas may not think about SQL injection when working with local files.

**How to avoid:**
- ALWAYS use parameterized queries: `duckdb.execute(query, [param1, param2])`
- NEVER use f-strings for query construction: `f"WHERE maker = '{address}'"`
- Use linter rules to catch string interpolation in queries

**Warning signs:**
- Any f-string or `.format()` that includes SQL keywords (WHERE, SELECT, FROM)
- Direct string concatenation with user input

**Example:**
```python
# WRONG: SQL injection risk
trader_address = request.get('address')  # Could be "'; DROP TABLE trades; --"
query = f"SELECT * FROM read_parquet('trades.parquet') WHERE maker = '{trader_address}'"

# RIGHT: Parameterized
query = "SELECT * FROM read_parquet('trades.parquet') WHERE maker = $1"
result = duckdb.execute(query, [trader_address])
```

### Pitfall 2: Loading Full Dataset into Memory

**What goes wrong:** Using `.fetchdf()` or `.df()` loads entire query result into memory. For 33.5GB dataset, this causes OOM errors.

**Why it happens:** Pandas-style thinking: "load data, then filter."

**How to avoid:**
- Filter in SQL (pushdown to Parquet scan)
- Use `.fetchmany(size=1000)` for streaming results
- Process results in batches, not all at once

**Warning signs:**
- `.fetchall()` or `.fetchdf()` on queries without WHERE clauses
- Memory errors when running queries
- Slow query performance despite filter pushdown

**Example:**
```python
# WRONG: Loads entire dataset into memory
df = duckdb.execute("SELECT * FROM read_parquet('trades_*.parquet')").fetchdf()
trader_trades = df[df['maker'] == trader_address]  # Too late - already loaded everything

# RIGHT: Filter in SQL (only matching rows loaded)
result = duckdb.execute("""
    SELECT * FROM read_parquet('trades_*.parquet')
    WHERE maker = $1
""", [trader_address])
trades = result.fetchdf()  # Only filtered rows in memory
```

### Pitfall 3: Case-Sensitive Address Matching

**What goes wrong:** Ethereum addresses are checksummed (mixed case), but users may query with lowercase or uppercase. Direct comparison misses matches.

**Why it happens:** Assuming string equality works for addresses.

**How to avoid:**
- Always use `LOWER(maker) = LOWER($1)` for address comparisons
- Normalize addresses in converters: `trader_address.lower()`
- Document that all addresses stored in lowercase

**Warning signs:**
- Queries return no results for known traders
- Works for some addresses but not others (case-dependent)

**Example:**
```python
# WRONG: Case-sensitive (misses matches)
query = "SELECT * FROM read_parquet($1) WHERE maker = $2"
result = duckdb.execute(query, [path, '0xABC123'])  # Won't match '0xabc123'

# RIGHT: Case-insensitive
query = "SELECT * FROM read_parquet($1) WHERE LOWER(maker) = LOWER($2)"
result = duckdb.execute(query, [path, '0xABC123'])  # Matches any case
```

### Pitfall 4: Missing Deduplication Check

**What goes wrong:** Same trade inserted multiple times from different sources (Graph, JBecker, Blockchain).

**Why it happens:** Forgetting that `trade_id` is the deduplication key across all sources.

**How to avoid:**
- ALWAYS check `session.query(Trade).filter_by(trade_id=...).first()` before insert
- Use `trade_id` from source data (don't generate new IDs)
- Log duplicate count for visibility

**Warning signs:**
- Trade count grows on repeated ingestion
- Database size increases without new data
- Duplicate trades in query results

**Example:**
```python
# Pattern from existing pipeline (follow this!)
for trade_response in batch:
    # Deduplication check by trade_id
    existing = session.query(Trade).filter_by(trade_id=trade_response.id).first()

    if existing:
        stats["already_in_db"] += 1
        continue  # Skip duplicate

    # Insert only if not exists
    trade = Trade(
        trade_id=trade_response.id,  # Use source ID for deduplication
        # ... other fields
    )
    session.add(trade)
```

### Pitfall 5: Forgetting Amount Conversion (6 Decimals)

**What goes wrong:** JBecker stores amounts as 6-decimal integers (e.g., 1000000 = 1 USDC). Forgetting to divide by 1e6 produces nonsense volumes.

**Why it happens:** Raw blockchain data uses integer representation for precision.

**How to avoid:**
- Convert immediately in converter function: `Decimal(amount) / Decimal("1000000")`
- Add test case verifying correct conversion (1000000 → Decimal("1.0"))
- Use consistent pattern from Graph converter (already handles this)

**Warning signs:**
- Volumes in millions/billions (should be hundreds/thousands)
- Price calculations produce wrong results
- Test failures on amount assertions

**Example:**
```python
# JBecker Parquet schema
{
  "makerAmountFilled": "1500000",  # 6 decimals (1.5 USDC)
  "takerAmountFilled": "3000000",  # 6 decimals (3.0 USDC)
}

# Converter must divide by 1e6
maker_amount = Decimal(jbecker_trade["makerAmountFilled"]) / Decimal("1000000")
# Result: Decimal("1.5")
```

## Code Examples

Verified patterns for JBecker integration:

### Query Trader History (DuckDB + Parameterization)
```python
# src/datasources/jbecker.py
import duckdb
from pathlib import Path
from typing import Optional

class JBeckerDataset:
    """Query Jon Becker's Parquet dataset using DuckDB.

    Provides SQL interface to 33.5GB Parquet trade history.
    Uses parameterized queries for security.
    """

    def __init__(self, data_path: str):
        """Initialize dataset client.

        Args:
            data_path: Path to data/ directory (e.g., "./data")
        """
        self.data_path = Path(data_path)
        self.trades_path = self.data_path / "polymarket" / "trades"

    def is_available(self) -> bool:
        """Check if dataset exists."""
        return self.trades_path.exists() and \
               len(list(self.trades_path.glob("trades_*.parquet"))) > 0

    def query_trader_history(
        self,
        trader_address: str,
        limit: Optional[int] = None
    ) -> list[dict]:
        """Query all trades for trader address.

        Uses filter pushdown for performance (only matching rows loaded).
        Case-insensitive address matching (LOWER).

        Args:
            trader_address: Trader wallet address (any case)
            limit: Optional max trades to return (newest first)

        Returns:
            List of trade dicts with JBecker schema

        Raises:
            FileNotFoundError: If dataset not available
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found at {self.data_path}. "
                f"Download from https://s3.jbecker.dev/data.tar.zst"
            )

        # Build query with parameterization (SQL injection safe)
        pattern = str(self.trades_path / "trades_*.parquet")

        query = """
            SELECT
                id, maker, taker,
                makerAmountFilled, takerAmountFilled,
                makerAssetId, takerAssetId,
                fee, timestamp, blockNumber, transactionHash,
                orderHash, side, price, _fetched_at, _contract
            FROM read_parquet($1)
            WHERE LOWER(maker) = LOWER($2) OR LOWER(taker) = LOWER($2)
            ORDER BY timestamp DESC
        """

        if limit:
            query += f" LIMIT {int(limit)}"  # Safe: limit is int

        # Execute with parameters (NOT string interpolation)
        result = duckdb.execute(query, [pattern, trader_address])

        # Convert to list of dicts
        return result.fetchdf().to_dict('records')
```

### Schema Converter (JBecker → TradeResponse)
```python
# src/datasources/converters.py
from datetime import datetime
from decimal import Decimal
from src.api.models import TradeResponse

def jbecker_trade_to_api_response(
    jbecker_trade: dict,
    trader_address: str
) -> TradeResponse:
    """Convert JBecker Parquet schema to TradeResponse format.

    Handles amount conversion (6 decimals), timestamp parsing,
    and trader role determination (maker/taker).

    Args:
        jbecker_trade: Trade dict from DuckDB query
        trader_address: Address we're querying for (determines role)

    Returns:
        TradeResponse object (validated by Pydantic)

    Example:
        >>> jbecker_trade = {
        ...     "id": "0x123_0x456",
        ...     "maker": "0xabc",
        ...     "taker": "0xdef",
        ...     "makerAmountFilled": "1500000",  # 1.5 USDC
        ...     "takerAmountFilled": "3000000",  # 3.0 USDC
        ...     "side": "BUY",
        ...     "price": "0.65",
        ...     "timestamp": 1234567890,
        ...     ...
        ... }
        >>> response = jbecker_trade_to_api_response(jbecker_trade, "0xabc")
        >>> response.size
        Decimal('1.5')
        >>> response.side
        'BUY'
    """
    # Normalize addresses (case-insensitive)
    trader_address = trader_address.lower()
    maker = jbecker_trade["maker"].lower()
    taker = jbecker_trade["taker"].lower()

    # Determine trader's role
    is_maker = (trader_address == maker)

    # Convert amounts from 6-decimal integers to Decimal USDC
    maker_amount = Decimal(jbecker_trade["makerAmountFilled"]) / Decimal("1000000")
    taker_amount = Decimal(jbecker_trade["takerAmountFilled"]) / Decimal("1000000")

    # Determine trader's side and size
    if is_maker:
        size = maker_amount
        asset_id = jbecker_trade["makerAssetId"]
        side = jbecker_trade["side"]  # Maker's side
    else:
        size = taker_amount
        asset_id = jbecker_trade["takerAssetId"]
        # Taker takes opposite side
        side = "SELL" if jbecker_trade["side"] == "BUY" else "BUY"

    # Convert timestamp (Unix seconds → datetime)
    timestamp = datetime.fromtimestamp(int(jbecker_trade["timestamp"]))

    # Market ID: Use transaction hash + asset (same as Graph pattern)
    market_id = f"jbecker_{jbecker_trade['transactionHash']}_{asset_id}"

    # Asset ticker: YES (odd) / NO (even) from Polymarket CTF
    try:
        asset_id_int = int(asset_id)
        asset_ticker = "YES" if asset_id_int % 2 == 1 else "NO"
    except (ValueError, TypeError):
        asset_ticker = "UNKNOWN"

    # Return validated TradeResponse (Pydantic checks price range, types)
    return TradeResponse(
        id=jbecker_trade["id"],
        market=market_id,
        trader=trader_address,
        side=side,
        size=size,
        price=Decimal(jbecker_trade["price"]),
        timestamp=timestamp,
        asset_ticker=asset_ticker,
    )
```

### Pipeline Integration Method
```python
# src/pipeline/ingest.py (add to IngestionPipeline class)

def ingest_trader_history_jbecker(self, trader_address: str) -> dict:
    """Ingest trader history from JBecker dataset.

    Uses DuckDB to query Parquet files, converts to TradeResponse format,
    and stores with deduplication. Follows same pattern as Graph/Blockchain.

    Args:
        trader_address: Trader wallet address

    Returns:
        Stats dict:
        - detail_count: Trades inserted
        - already_in_db: Duplicates skipped
        - trades_from_jbecker: Total trades found

    Raises:
        ValueError: If jbecker_client not configured
        FileNotFoundError: If dataset not available
    """
    if not self.jbecker_client:
        raise ValueError("JBecker client not configured. Pass jbecker_client to __init__.")

    logger.info(f"Ingesting history for {trader_address[:8]}... from JBecker dataset")

    session = self.session_factory()
    stats = {
        "detail_count": 0,
        "already_in_db": 0,
        "trades_from_jbecker": 0,
    }

    try:
        # Query all trades from DuckDB
        jbecker_trades = self.jbecker_client.query_trader_history(trader_address)
        stats["trades_from_jbecker"] = len(jbecker_trades)

        if not jbecker_trades:
            logger.info(f"No JBecker trades found for {trader_address[:8]}...")
            # Mark backfill complete even if no trades
            trader = session.query(Trader).filter_by(address=trader_address).first()
            if trader:
                trader.backfill_complete = True
            session.commit()
            return stats

        # Convert to TradeResponse format
        trade_responses = []
        for jbecker_trade in jbecker_trades:
            try:
                trade_response = jbecker_trade_to_api_response(
                    jbecker_trade,
                    trader_address
                )
                trade_responses.append(trade_response)
            except Exception as e:
                logger.warning(f"Failed to convert JBecker trade: {e}")
                continue

        # Batch insert with deduplication (1000 trades per batch)
        batch_size = 1000
        for i in range(0, len(trade_responses), batch_size):
            batch = trade_responses[i:i+batch_size]

            for trade_response in batch:
                # Deduplication check by trade_id
                existing = session.query(Trade).filter_by(
                    trade_id=trade_response.id
                ).first()

                if existing:
                    stats["already_in_db"] += 1
                    continue

                # Insert new trade
                trade = Trade(
                    market_id=trade_response.market,
                    trader_address=trade_response.trader,
                    side=trade_response.side,
                    size=trade_response.size,
                    price=trade_response.price,
                    timestamp=trade_response.timestamp,
                    asset_ticker=trade_response.asset_ticker,
                    trade_id=trade_response.id,
                )
                session.add(trade)
                stats["detail_count"] += 1

            # Commit batch
            session.commit()

        # Mark trader as backfill complete
        trader = session.query(Trader).filter_by(address=trader_address).first()
        if trader:
            trader.backfill_complete = True
            trader.last_active = datetime.utcnow()

        session.commit()

        logger.info(
            f"JBecker ingestion for {trader_address[:8]}...: "
            f"{stats['detail_count']} trades inserted, "
            f"{stats['already_in_db']} duplicates skipped"
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to ingest from JBecker: {e}")
        raise
    finally:
        session.close()

    return stats
```

### CLI Research Command
```python
# src/cli/commands.py (add to cli group)

@cli.command()
@click.argument("address")
@click.option("--format", "-f", type=click.Choice(["table", "json", "csv"]), default="table")
@click.option("--verbose", "-v", is_flag=True)
def research(address, format, verbose):
    """Full historical analysis using JBecker dataset.

    Queries complete trade history (2020-2026) without API rate limits.
    Requires JBecker dataset downloaded and configured.

    ADDRESS can be full address or prefix.

    Example:
        polymarket research 0xeffd76
        polymarket research 0xabc --format json
    """
    logger.info(f"RESEARCH command started (address={address}, format={format})")

    console = Console()

    with console.status("[bold green]Querying JBecker dataset...", spinner="dots"):
        # Get dependencies
        session_factory, _, _, _ = _get_dependencies()
        settings = get_settings()

        # Create JBecker client
        from src.datasources.jbecker import JBeckerDataset
        jbecker = JBeckerDataset(settings.jbecker_data_path)

        # Check availability
        if not jbecker.is_available():
            console.print("[red]JBecker dataset not available.[/red]")
            console.print("\n[yellow]To download:[/yellow]")
            console.print("1. wget https://s3.jbecker.dev/data.tar.zst")
            console.print("2. tar --use-compress-program=zstd -xvf data.tar.zst")
            console.print("3. Set JBECKER_DATA_PATH in .env")
            return

        with get_session(session_factory) as session:
            # Resolve partial address
            full_address = find_trader_by_prefix(session, address)
            if not full_address:
                return

            # Query all trades
            try:
                trades = jbecker.query_trader_history(full_address)
            except Exception as e:
                console.print(f"[red]Query failed:[/red] {e}")
                return

    logger.info(f"Found {len(trades)} trades from JBecker dataset")

    # Format output based on --format flag
    if format == "json":
        import json
        console.print(json.dumps(trades, indent=2, default=str))
    elif format == "csv":
        import csv
        import sys
        writer = csv.DictWriter(sys.stdout, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    else:  # table
        from rich.table import Table
        table = Table(title=f"Trade History for {full_address[:10]}...")
        table.add_column("Timestamp")
        table.add_column("Side")
        table.add_column("Size")
        table.add_column("Price")

        for trade in trades[:50]:  # Limit to 50 for display
            table.add_row(
                str(trade["timestamp"]),
                trade["side"],
                str(trade["makerAmountFilled"]),
                str(trade["price"]),
            )

        console.print(table)
        console.print(f"\n[dim]Showing 50 of {len(trades)} trades[/dim]")

    logger.info("RESEARCH command completed")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| API (100 trades limit) | The Graph (instant, unlimited) | Phase 8 (Feb 2026) | 3-sec queries vs 6-7 hours |
| Blockchain scanning (6-7 hours) | The Graph (primary) + JBecker (research) | Phase 9 | Offline capability, bulk analysis |
| Pandas Parquet reading | DuckDB SQL queries | Best practice 2024+ | 10-100x faster via filter pushdown |
| String interpolation in queries | Parameterized queries (`$1`, `$2`) | Security standard 2023+ | SQL injection prevention |

**Deprecated/outdated:**
- **Direct Parquet reading with pandas:** Use DuckDB for 10-100x speedup
- **Manual string escaping:** Use DuckDB parameterization (automatic)
- **Loading full dataset into memory:** Use SQL WHERE clauses (filter pushdown)

**Current best practices (2026):**
- **DuckDB for Parquet:** Industry standard for columnar analytics
- **Filter pushdown:** Automatic in DuckDB, critical for performance
- **Parameterized queries:** Required for security, improves caching
- **Small test fixtures:** Use PyArrow to generate 5-10MB samples (not full dataset)

## Testing Strategy

### Challenge: Testing Without 33.5GB Dataset

**Problem:** CI/CD can't download 33.5GB dataset. Need to test DuckDB integration without full data.

**Solution:** Create small test fixtures (5-10MB) with realistic schema.

### Approach 1: PyArrow Test Fixtures (RECOMMENDED)

**What:** Generate small Parquet files with JBecker schema for testing.

**When to use:** Unit tests, integration tests, CI/CD.

**Example:**
```python
# tests/fixtures/create_jbecker_sample.py
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

def create_sample_parquet():
    """Create small sample Parquet file with JBecker schema.

    Generates 100 realistic trades for testing.
    """
    # Define schema (matches JBecker Parquet)
    schema = pa.schema([
        ('id', pa.string()),
        ('maker', pa.string()),
        ('taker', pa.string()),
        ('makerAmountFilled', pa.string()),  # 6-decimal integer as string
        ('takerAmountFilled', pa.string()),
        ('makerAssetId', pa.string()),
        ('takerAssetId', pa.string()),
        ('fee', pa.string()),
        ('timestamp', pa.int64()),
        ('blockNumber', pa.int64()),
        ('transactionHash', pa.string()),
        ('orderHash', pa.string()),
        ('side', pa.string()),
        ('price', pa.string()),
        ('_fetched_at', pa.timestamp('us')),
        ('_contract', pa.string()),
    ])

    # Sample data (100 trades)
    data = {
        'id': [f"0x{i:064x}_0x{i:064x}" for i in range(100)],
        'maker': ['0xeffd76b6a4318d50c6f71a16b276c5b279445a86'] * 50 +
                 ['0xeefa8eb0568f7cbd57d85e99f61c92dcc57a23b2'] * 50,
        'taker': ['0xabc123' + f"{i:034x}" for i in range(100)],
        'makerAmountFilled': [str(1000000 + i * 10000) for i in range(100)],  # 1-2 USDC
        'takerAmountFilled': [str(2000000 + i * 20000) for i in range(100)],  # 2-4 USDC
        'makerAssetId': [str(123456 + i) for i in range(100)],
        'takerAssetId': [str(789012 + i) for i in range(100)],
        'fee': ['1000'] * 100,
        'timestamp': [1704067200 + i * 3600 for i in range(100)],  # Hourly trades
        'blockNumber': [50000000 + i * 100 for i in range(100)],
        'transactionHash': [f"0x{i:064x}" for i in range(100)],
        'orderHash': [f"0x{i:064x}" for i in range(100)],
        'side': ['BUY'] * 50 + ['SELL'] * 50,
        'price': [str(0.5 + i * 0.001) for i in range(100)],
        '_fetched_at': [pa.scalar(1704067200000000, type=pa.timestamp('us'))] * 100,
        '_contract': ['ctf_exchange'] * 100,
    }

    # Create PyArrow table
    table = pa.table(data, schema=schema)

    # Write to Parquet
    output_path = Path("tests/fixtures/jbecker_sample.parquet")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pq.write_table(table, str(output_path), compression='snappy')
    print(f"Created test fixture: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    create_sample_parquet()
```

**Sources:**
- [DuckDB Parquet writing](https://duckdb.org/docs/stable/data/parquet/overview)
- [PyArrow write_table documentation](https://til.simonwillison.net/duckdb/parquet)

### Approach 2: Mock DuckDB Connection (Unit Tests)

**What:** Mock DuckDB execute() for pure unit tests without files.

**When to use:** Testing error handling, edge cases, converter logic.

**Example:**
```python
# tests/datasources/test_jbecker.py
import pytest
from unittest.mock import Mock, patch
from src.datasources.jbecker import JBeckerDataset

def test_query_trader_history_not_available(mocker):
    """Test graceful failure when dataset missing."""
    dataset = JBeckerDataset("./nonexistent")

    with pytest.raises(FileNotFoundError) as exc_info:
        dataset.query_trader_history("0xabc")

    assert "not found" in str(exc_info.value).lower()
    assert "s3.jbecker.dev" in str(exc_info.value)

@patch('duckdb.execute')
def test_query_trader_history_parameterization(mock_execute):
    """Test that queries use parameterization (no SQL injection)."""
    # Setup mock
    mock_result = Mock()
    mock_result.fetchdf.return_value.to_dict.return_value = []
    mock_execute.return_value = mock_result

    # Create dataset (mock is_available to return True)
    dataset = JBeckerDataset("./data")
    dataset.is_available = lambda: True

    # Query trader
    dataset.query_trader_history("0xabc'; DROP TABLE trades; --")

    # Verify parameterization used (NOT string interpolation)
    mock_execute.assert_called_once()
    call_args = mock_execute.call_args

    # First arg is query string (should NOT contain trader address)
    query = call_args[0][0]
    assert "0xabc" not in query  # Address not in query string
    assert "DROP TABLE" not in query

    # Second arg is parameters list (should contain trader address)
    params = call_args[0][1]
    assert "0xabc'; DROP TABLE trades; --" in params  # Safe: in parameters
```

**Sources:**
- [pytest-mock documentation](https://pytest-with-eric.com/mocking/pytest-mocking/)
- [Testing database transactions](https://pytest-with-eric.com/database-testing/pytest-sql-database-testing/)

### Approach 3: Integration Tests with Sample Parquet

**What:** Use small test fixture to verify end-to-end DuckDB queries.

**When to use:** Integration tests, verifying schema conversion, deduplication.

**Example:**
```python
# tests/datasources/test_jbecker_integration.py
import pytest
from pathlib import Path
from src.datasources.jbecker import JBeckerDataset
from src.datasources.converters import jbecker_trade_to_api_response

@pytest.fixture
def jbecker_dataset(tmp_path):
    """Create test dataset with sample Parquet file."""
    # Copy sample fixture to tmp directory
    fixture_path = Path("tests/fixtures/jbecker_sample.parquet")
    trades_dir = tmp_path / "polymarket" / "trades"
    trades_dir.mkdir(parents=True)

    import shutil
    shutil.copy(fixture_path, trades_dir / "trades_00.parquet")

    return JBeckerDataset(str(tmp_path))

def test_query_trader_history_integration(jbecker_dataset):
    """Test querying sample Parquet file with real DuckDB."""
    # Query known trader from sample (0xeffd76...)
    trades = jbecker_dataset.query_trader_history(
        "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    )

    # Verify results
    assert len(trades) == 50  # Sample has 50 trades for this address
    assert all('id' in t for t in trades)
    assert all('makerAmountFilled' in t for t in trades)

def test_converter_integration(jbecker_dataset):
    """Test schema conversion with real DuckDB query."""
    trades = jbecker_dataset.query_trader_history(
        "0xeffd76b6a4318d50c6f71a16b276c5b279445a86",
        limit=10
    )

    # Convert to TradeResponse
    for jbecker_trade in trades:
        trade_response = jbecker_trade_to_api_response(
            jbecker_trade,
            "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
        )

        # Verify conversion
        assert trade_response.size > 0
        assert 0 < trade_response.price < 1
        assert trade_response.side in ["BUY", "SELL"]
        assert trade_response.id == jbecker_trade["id"]
```

### Test Structure Summary

```
tests/
├── fixtures/
│   ├── create_jbecker_sample.py     # Script to generate sample Parquet
│   └── jbecker_sample.parquet       # 5-10MB sample (100 trades)
├── datasources/
│   ├── test_jbecker.py              # Unit tests (mocked DuckDB)
│   ├── test_jbecker_integration.py  # Integration tests (real DuckDB + fixture)
│   └── test_converters.py           # Schema conversion tests
└── pipeline/
    └── test_ingest_jbecker.py       # End-to-end ingestion tests
```

**Test count estimate:** 45+ tests
- Plan 09-01 (Query Layer): 20 tests
- Plan 09-02 (Converters): 15 tests
- Plan 09-03 (CLI): 10 tests

## Configuration Management

### Settings (src/config/settings.py)

**Add to Settings class:**
```python
class Settings(BaseSettings):
    # ... existing settings ...

    # JBecker Dataset Configuration (Phase 9)
    jbecker_data_path: str = "./data"  # Path to data/ directory
    jbecker_enabled: bool = True       # Enable JBecker tier
    jbecker_batch_size: int = 1000     # Batch insert size (larger than API)
```

### Environment Variables (.env)

**Add to .env file:**
```bash
# JBecker Dataset (Phase 9)
JBECKER_DATA_PATH=./data           # Path to extracted dataset
JBECKER_ENABLED=true               # Enable JBecker queries
JBECKER_BATCH_SIZE=1000            # Trades per batch insert
```

### Graceful Handling (Missing Dataset)

**Pattern:**
```python
# Pipeline checks availability before using
if settings.jbecker_enabled and jbecker_client.is_available():
    # Use JBecker tier
    return self.ingest_trader_history_jbecker(trader_address)
else:
    # Fall back to blockchain tier
    return self.ingest_trader_history_blockchain(trader_address)
```

**CLI error messages:**
```python
# User-friendly guidance if dataset missing
if not jbecker.is_available():
    console.print("[red]JBecker dataset not available.[/red]")
    console.print("\n[yellow]To download and setup:[/yellow]")
    console.print("1. wget https://s3.jbecker.dev/data.tar.zst")
    console.print("2. tar --use-compress-program=zstd -xvf data.tar.zst")
    console.print("3. Set JBECKER_DATA_PATH in .env to point to data/ directory")
    console.print("4. Verify with: ls $JBECKER_DATA_PATH/polymarket/trades/")
    return
```

## Open Questions

1. **Market Metadata Enrichment**
   - What we know: JBecker trades have asset IDs but not market metadata
   - What's unclear: Should we fetch from API or query JBecker's markets/ Parquet?
   - Recommendation: Query JBecker's markets Parquet (keeps system offline-capable)

2. **Dataset Update Strategy**
   - What we know: Dataset is static snapshot (updated periodically by Jon Becker)
   - What's unclear: How to handle incremental updates vs full re-download
   - Recommendation: Phase 9 assumes static dataset; defer update strategy to future phase

3. **Trade_ID Format Consistency**
   - What we know: Graph uses "0x{tx}_{log_index}", JBecker uses similar format
   - What's unclear: Are JBecker trade IDs compatible with Graph/Blockchain for deduplication?
   - Recommendation: Test with sample data; may need normalization function

4. **Performance on Large Queries**
   - What we know: DuckDB claims 10-100x speedup over pandas
   - What's unclear: Real-world performance on 33.5GB with 10,000+ trades per trader
   - Recommendation: Add performance logging; optimize if queries exceed 10 seconds

## Sources

### Primary (HIGH confidence)

**DuckDB Official Documentation:**
- [Reading and Writing Parquet Files](https://duckdb.org/docs/stable/data/parquet/overview) - Parquet integration
- [Parquet Tips](https://duckdb.org/docs/stable/data/parquet/tips) - Performance optimization
- [Prepared Statements](https://duckdb.org/docs/stable/sql/query_syntax/prepared_statements) - Parameterization
- [Pattern Matching](https://duckdb.org/docs/stable/sql/functions/pattern_matching) - Case-insensitive queries
- [Python API](https://duckdb.org/docs/stable/clients/python/overview) - Python integration

**Project Codebase:**
- `src/graph/converters.py` - Existing converter pattern (lines 9-110)
- `src/pipeline/ingest.py` - Pipeline integration methods (lines 738-859)
- `src/config/settings.py` - Configuration pattern (lines 1-92)
- `src/cli/commands.py` - CLI command patterns (lines 1-539)

**Handoff Document:**
- `PHASE_9_HANDOFF.md` - Comprehensive research (12,000 words)

### Secondary (MEDIUM confidence)

**Security & Best Practices:**
- [Parameterized Queries for SQL Injection Prevention](https://woteq.com/how-to-run-parameterized-queries-in-duckdb-with-python-to-prevent-sql-injection/)
- [DuckDB + Parquet Pushdown](https://medium.com/@connect.hashblock/duckdb-parquet-pushdown-feels-like-magic-65f46276678a)
- [Building Modern Data Stack with Python, Parquet, and DuckDB](https://www.kdnuggets.com/building-your-modern-data-analytics-stack-with-python-parquet-and-duckdb)

**Testing:**
- [pytest-databases for DuckDB fixtures](https://pypi.org/project/pytest-databases/)
- [How to Mock in Pytest](https://pytest-with-eric.com/mocking/pytest-mocking/)
- [Using DuckDB to access Parquet](https://til.simonwillison.net/duckdb/parquet)

**Error Handling:**
- [DuckDB Structured Errors](https://github.com/duckdb/duckdb/issues/13782)
- [Python Graceful Degradation Patterns](https://medium.com/@RampantLions/robust-error-handling-in-python-tracebacks-graceful-degradation-and-suppression-11f7a140720b)

### Tertiary (LOW confidence)
None - all findings verified with official documentation or existing codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - DuckDB is industry standard for Parquet, official docs comprehensive
- Architecture: HIGH - Follows existing converter/pipeline patterns, handoff provides detailed strategy
- Testing: HIGH - PyArrow + pytest patterns well-documented, sample fixtures proven approach
- Pitfalls: HIGH - SQL injection, filter pushdown, case sensitivity are known DuckDB gotchas

**Research date:** 2026-02-12
**Valid until:** 90 days (DuckDB stable, Parquet format unchanged, patterns mature)

**Handoff document validity:** Remains accurate - dataset structure, DuckDB approach, integration strategy all verified with current (2026) documentation.
