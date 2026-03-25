# Graph Trade Data Structure Research

**Date:** 2026-03-25  
**Purpose:** Deep dive into every data field extracted from trades via The Graph subgraph and JBecker dataset, documenting what each field means and how it's transformed through the pipeline.

**Complements:** `market-outcome-coverage-research.md` — which identified that 72% of trades use `graph_` placeholder IDs.

---

## Executive Summary

Trades enter the system through **three sources**, each with different data schemas:

| Source | Format | Fields Available | Market ID Resolution |
|--------|--------|------------------|---------------------|
| **The Graph** | GraphQL OrderFilledEvent | 13 fields (full on-chain data) | Token catalog lookup or `graph_{txHash}_{assetId}` |
| **JBecker Dataset** | Parquet (14 columns) | 14 fields (raw blockchain) | Token catalog lookup or `graph_{txHash}_{assetId}` |
| **Polymarket API** | REST JSON | 8 fields (simplified) | Direct `condition_id` |

**Key Finding:** 72% of trades (1.8M) use `graph_` placeholders because the token catalog lookup fails. These trades are **orphaned** — they cannot be matched to markets for resolution.

---

## Part 1: The Graph Data Structure

### 1.1 Source: Polymarket Orderbook Subgraph

**Subgraph ID:** `7fu2DWYK93ePfzB24c2wrP94S3x4LGHUrQxphhoEypyY`  
**Endpoint:** `https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{subgraph_id}`  
**Query Method:** `orderFilledEvents` with `maker` or `taker` filters

### 1.2 GraphQL Schema

```graphql
orderFilledEvents(
  first: 1000
  skip: 0
  where: {maker: "0x..."}  # OR {taker: "0x..."}
  orderBy: timestamp
  orderDirection: desc
) {
  id                  # "0x{txHash}_0x{logIndex}" - unique event ID
  maker               # "0x..." - Maker wallet address
  taker               # "0x..." - Taker wallet address
  makerAmountFilled   # "1000000" - Raw 6-decimal USDC amount
  takerAmountFilled   # "2000000" - Raw 6-decimal USDC amount
  makerAssetId        # "5410480039..." - Token ID (conditional token)
  takerAssetId        # "5410480039..." - Token ID (conditional token)
  fee                 # "1000" - Raw 6-decimal USDC fee
  timestamp           # "1234567890" - Unix timestamp (seconds)
  blockNumber         # "82466624" - Polygon block number
  transactionHash     # "0xf704ff15..." - Transaction hash
  orderHash           # "0x..." - CLOB order hash
  side                # "BUY" or "SELL" - Maker's side
  price               # "0.5" - Decimal odds (can be >1)
}
```

### 1.3 Field-by-Field Breakdown

#### `id` (string)
- **Format:** `"0x{transactionHash}_0x{logIndex}"`
- **Example:** `"0xf704ff1584f312b6a1f38599e9cdebf0768c6f23cc27e1166a52e00fdbef7547_0x1a2b3c"`
- **Purpose:** Unique identifier for the OrderFilledEvent
- **Usage:** Used as `TradeResponse.id` in pipeline

#### `maker` (string)
- **Format:** Ethereum address `"0x..."` (42 chars)
- **Purpose:** Address that created the limit order
- **Note:** All trades have both maker and taker — one side is the trader being queried

#### `taker` (string)
- **Format:** Ethereum address `"0x..."` (42 chars)
- **Purpose:** Address that filled the limit order

#### `makerAmountFilled` (string)
- **Format:** 6-decimal integer string
- **Example:** `"1000000"` = 1.0 USDC
- **Purpose:** Amount of maker asset provided
- **Conversion:** Divide by 1,000,000 to get USDC amount

#### `takerAmountFilled` (string)
- **Format:** 6-decimal integer string
- **Example:** `"2000000"` = 2.0 USDC
- **Purpose:** Amount of taker asset provided
- **Conversion:** Divide by 1,000,000 to get USDC amount

#### `makerAssetId` (string)
- **Format:** Large integer string
- **Example:** `"54104800394221291794784713979963016024782081813693508603329576574109946650821"`
- **Purpose:** Conditional token ID being traded
- **Critical:** This is the **token ID**, NOT the condition ID (market ID)
- **Resolution:** Must be looked up in `token_catalog` to get `condition_id`
- **Fallback:** If not in catalog → synthetic `graph_{txHash}_{assetId}`

#### `takerAssetId` (string)
- **Format:** Large integer string
- **Purpose:** Conditional token ID on opposite side
- **Note:** Same resolution process as `makerAssetId`

#### `fee` (string)
- **Format:** 6-decimal integer string
- **Example:** `"1000"` = 0.001 USDC
- **Purpose:** Protocol fee charged

#### `timestamp` (string)
- **Format:** Unix timestamp in seconds
- **Example:** `"1709856000"` → March 8, 2024 00:00:00 UTC
- **Conversion:** `datetime.fromtimestamp(int(timestamp))`

#### `blockNumber` (string)
- **Format:** Integer string
- **Example:** `"82466624"`
- **Purpose:** Polygon block where trade was recorded
- **Alternative timestamp:** Can be converted to timestamp via block lookup table (used in JBecker converter)

#### `transactionHash` (string)
- **Format:** `"0x..."` (66 chars)
- **Example:** `"0xf704ff1584f312b6a1f38599e9cdebf0768c6f23cc27e1166a52e00fdbef7547"`
- **Purpose:** On-chain transaction identifier
- **Usage:** Part of synthetic market ID when token catalog lookup fails

#### `orderHash` (string)
- **Format:** `"0x..."` (66 chars)
- **Purpose:** CLOB order identifier (off-chain order book)
- **Note:** Not currently used in pipeline

#### `side` (string)
- **Values:** `"BUY"` or `"SELL"`
- **Meaning:** **Maker's perspective** — whether maker bought or sold
- **Critical:** When queried as taker, side is **flipped** (see converter logic below)

#### `price` (string)
- **Format:** Decimal odds
- **Example:** `"0.5"` (50% probability) or `"2.0"` (underdog at 2:1 odds)
- **Range:** Can be > 1.0 for underdogs
- **Conversion:** If price > 1, convert to implied probability: `1 / price`
- **Usage:** Converted to 0-1 probability range for `TradeResponse`

---

## Part 2: JBecker Dataset Schema

### 2.1 Source: Jon Becker's Parquet Dataset

**Download:** `https://s3.jbecker.dev/data.tar.zst`  
**Size:** 33.5 GB compressed (polymarket/trades/*.parquet)  
**Query Method:** DuckDB with filter pushdown

### 2.2 Parquet Schema (14 Columns)

```python
schema = pa.schema([
    ('block_number', pa.int64()),
    ('transaction_hash', pa.string()),
    ('log_index', pa.int64()),
    ('order_hash', pa.string()),
    ('maker', pa.string()),
    ('taker', pa.string()),
    ('maker_asset_id', pa.string()),
    ('taker_asset_id', pa.string()),
    ('maker_amount', pa.decimal128(38, 0)),
    ('taker_amount', pa.decimal128(38, 0)),
    ('fee', pa.decimal128(38, 0)),
    ('timestamp', pa.timestamp('ns')),  # Can be NULL
    ('_fetched_at', pa.timestamp('ns')),  # Fallback timestamp
    ('_contract', pa.string()),
])
```

### 2.3 Field-by-Field Breakdown

#### `block_number` (int64)
- **Example:** `82466624`
- **Purpose:** Polygon block number
- **Usage:** Converted to timestamp using anchor block table if `timestamp` is NULL

#### `transaction_hash` (string)
- **Example:** `"0xf704ff1584f312b6a1f38599e9cdebf0768c6f23cc27e1166a52e00fdbef7547"`
- **Purpose:** On-chain transaction hash
- **Usage:** Part of synthetic trade ID: `jbecker_{txHash}_{logIndex}`

#### `log_index` (int64)
- **Example:** `42`
- **Purpose:** Event log index within transaction
- **Usage:** Ensures unique trade ID when combined with txHash

#### `order_hash` (string)
- **Purpose:** CLOB order identifier
- **Note:** Not used in pipeline

#### `maker` (string)
- **Example:** `"0xeffd76b6a4318d50c6f71a16b276c5b279445a86"`
- **Purpose:** Maker wallet address

#### `taker` (string)
- **Example:** `"0x1234567890abcdef..."`
- **Purpose:** Taker wallet address

#### `maker_asset_id` (string)
- **Example:** `"54104800394221291794784713979963016024782081813693508603329576574109946650821"`
- **Purpose:** Token ID (conditional token)
- **Note:** Same resolution process as Graph data

#### `taker_asset_id` (string)
- **Purpose:** Token ID on opposite side

#### `maker_amount` (decimal)
- **Example:** `1000000` (6 decimals)
- **Purpose:** Amount of maker asset
- **Conversion:** Divide by 1,000,000

#### `taker_amount` (decimal)
- **Example:** `2000000` (6 decimals)
- **Purpose:** Amount of taker asset

#### `fee` (decimal)
- **Example:** `1000` (6 decimals)
- **Purpose:** Protocol fee

#### `timestamp` (timestamp, nullable)
- **Format:** Nanosecond precision timestamp
- **Note:** Can be NULL — falls back to `_fetched_at`

#### `_fetched_at` (timestamp)
- **Purpose:** When data was scraped from blockchain
- **Usage:** Fallback if `timestamp` is NULL

#### `_contract` (string)
- **Purpose:** Smart contract address
- **Note:** Not used in pipeline

---

## Part 3: Data Transformation Pipeline

### 3.1 Conversion Flow

```
The Graph OrderFilledEvent     JBecker Parquet Row
         │                            │
         ▼                            ▼
  graph_trade_to_api_response()  jbecker_trade_to_api_response()
         │                            │
         ▼                            ▼
         └──────────┬─────────────────┘
                    ▼
         TradeResponse (Pydantic model)
                    │
                    ▼
         TradeWithCategory wrapper
                    │
                    ▼
         CategoryFilter routing
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  Detail storage          Summary aggregation
  (target categories)     (non-target categories)
```

### 3.2 Critical Conversion: Asset ID → Market ID

This is where **72% of trades are orphaned**:

```python
# src/graph/converters.py:98-105
if token_to_condition and asset_id in token_to_condition:
    market_id = token_to_condition[asset_id]
else:
    market_id = f"graph_{graph_trade['transactionHash']}_{asset_id}"
```

**Token Catalog Lookup:**
- `token_catalog` table maps `token_id` → `condition_id`
- Built from JBecker markets parquet during ingestion
- Coverage: ~11.4% match rate (136K markets matched from 1.2M tokens)

**Fallback:** When token not in catalog:
- Synthetic ID: `graph_{txHash}_{assetId}`
- Example: `graph_0xf704ff15..._5410480039...`
- **Problem:** Cannot be matched to any real market for resolution

### 3.3 Critical Conversion: Side Determination

```python
# src/graph/converters.py:60-79
is_maker = trader_address == maker

if is_maker:
    size = maker_amount
    asset_id = graph_trade["makerAssetId"]
    side = graph_trade["side"]  # BUY or SELL (from Graph)
else:
    size = taker_amount
    asset_id = graph_trade["takerAssetId"]
    # Taker takes opposite side of maker
    side = "SELL" if graph_trade["side"] == "BUY" else "BUY"
```

**Example:**
- Graph event: `maker="0xA", taker="0xB", side="BUY"`
- If querying for `0xB` (taker): side becomes `"SELL"`
- If querying for `0xA` (maker): side stays `"BUY"`

### 3.4 Critical Conversion: Price Normalization

```python
# src/graph/converters.py:83-88
price = Decimal(graph_trade["price"])
if price > 1:
    # Convert decimal odds to implied probability
    price = Decimal("1") / price
```

**Why?**
- Graph returns **decimal odds** (can be > 1 for underdogs)
- Pipeline expects **implied probability** (0-1 range)

**Examples:**
| Decimal Odds | Implied Probability | Meaning |
|--------------|---------------------|---------|
| 0.5 | 0.5 (50%) | Even odds |
| 0.25 | 0.25 (25%) | Underdog |
| 2.0 | 0.5 (50%) | Underdog at 2:1 |
| 4.0 | 0.25 (25%) | Heavy underdog |

### 3.5 Critical Conversion: Asset Ticker (YES/NO)

```python
# src/graph/converters.py:107-113
try:
    asset_id_int = int(asset_id)
    asset_ticker = "YES" if asset_id_int % 2 == 1 else "NO"
except (ValueError, TypeError):
    asset_ticker = "UNKNOWN"
```

**Rule:** In Polymarket CTF (Conditional Token Framework):
- **Odd** asset ID = YES share
- **Even** asset ID = NO share

---

## Part 4: Database Storage Schema

### 4.1 Trades Table

```python
# src/db/models.py:86-117
class Trade(Base):
    __tablename__ = "trades"
    
    id: Mapped[int]                          # Auto-increment PK
    market_id: Mapped[str]                   # condition_id OR graph_ placeholder
    trader_address: Mapped[str]              # 0x... wallet address
    side: Mapped[str]                        # "BUY" or "SELL"
    size: Mapped[Decimal]                    # Number of tokens (20,6 precision)
    price: Mapped[Decimal]                   # Probability (10,6 precision)
    timestamp: Mapped[datetime]              # Trade execution time
    asset_ticker: Mapped[str | None]         # "YES", "NO", or NULL
    trade_id: Mapped[str | None]             # Unique ID from source
    created_at: Mapped[datetime]             # When inserted into DB
```

### 4.2 Indexes

```python
__table_args__ = (
    Index("ix_trade_trader_timestamp", "trader_address", "timestamp"),
    Index("ix_trade_category_timestamp", "market_id", "timestamp"),
    Index("ix_trade_market_trader", "market_id", "trader_address"),
)
```

**Optimized Queries:**
- `SELECT * FROM trades WHERE trader_address = ? ORDER BY timestamp` — trader history
- `SELECT * FROM trades WHERE market_id = ?` — market trades
- `SELECT * FROM trades WHERE market_id = ? AND trader_address = ?` — trader's position in market

### 4.3 Token Catalog

```python
# src/db/models.py:439-456
class TokenCatalog(Base):
    __tablename__ = "token_catalog"
    
    token_id: Mapped[str]           # Primary key (JBecker clob_token_id)
    condition_id: Mapped[str]       # Market identifier
    question: Mapped[str]           # Market question
    niche_slug: Mapped[str | None]  # Taxonomy classification
    node_path: Mapped[str | None]   # Full taxonomy path
    depth: Mapped[int | None]       # Taxonomy depth (0-3)
    market_type: Mapped[str | None] # "match" or "prop"
```

**Critical:** This table is the **only link** between `asset_id` and `condition_id`. Without it, trades become orphaned with `graph_` placeholders.

---

## Part 5: The Graph_ Placeholder Problem

### 5.1 Root Cause

From `market-outcome-coverage-research.md`:
- **1,841,558 trades** (72%) have `market_id` starting with `graph_`
- Format: `graph_{transactionHash}_{assetId}`
- Created when `token_to_condition` lookup fails

### 5.2 Why Matching Fails

```python
# Attempted matching (does NOT work):
market_id = "graph_0xf704ff15..._5410480039..."
# Extract "condition_id" = "0xf704ff15..." (transaction hash, NOT condition ID)
# Query: SELECT * FROM markets WHERE condition_id = "0xf704ff15..."
# Result: 0 rows — transaction hashes are NOT condition IDs
```

### 5.3 Impact on Resolution Pipeline

```
Trade Resolution Flow:

trades table ──► build-positions ──► positions table
                                      │
                                      ▼
markets.outcome (IS NOT NULL) ──────► resolve-positions (70K resolved)
(12K markets)                            │
                                         ▼
markets.outcome (IS NULL) ───────────► BLOCKED (26K positions)
(136K markets)

Blind spot: 1.8M trades with graph_ placeholders
            cannot be matched to markets.outcome
```

### 5.4 Attempted Solutions

**Phase 29 Solution:** `resolve-markets-from-events` command
- Fetches ALL closed events from Gamma API
- Updates `markets.outcome` for matched markets
- **Limitation:** Only works for markets with:
  - A corresponding `GammaEvent` row
  - Can be matched via `token_id` → `market.tokens` join
  - Does NOT cover 130K "Unknown" category markets

**Token Catalog Expansion:**
- Building more complete `token_id` → `condition_id` mapping
- Would reduce `graph_` placeholder creation
- Current match rate: 11.4% (136K / 1.2M tokens)

---

## Part 6: Data Quality Issues

### 6.1 Missing Fields

| Field | Graph | JBecker | Impact |
|-------|-------|---------|--------|
| `asset_ticker` | Derived (odd/even) | Derived (odd/even) | Can be "UNKNOWN" if parse fails |
| `side` | Derived (role-based) | Derived (role-based) | Requires maker/taker role detection |
| `price` | Decimal odds | Calculated | Must normalize to 0-1 range |
| `timestamp` | Unix seconds | Nullable | Falls back to block number or `_fetched_at` |

### 6.2 Edge Cases

**Price > 1:**
```python
# Decimal odds format (e.g., 2.0, 4.0, 32.25)
# Must convert to implied probability
if price > 1:
    price = 1 / price
```

**Invalid price after conversion:**
```python
# src/datasources/converters.py:85-88
if price <= 0 or price >= 1:
    price = Decimal("1") - price if price >= 1 else Decimal("0.5")
if price <= 0 or price >= 1:
    price = Decimal("0.5")
```

**NULL timestamp:**
```python
# src/datasources/converters.py:89-107
if timestamp is None:
    fetched = jbecker_trade.get("_fetched_at")
    if fetched is not None:
        timestamp = fetched.to_pydatetime().replace(tzinfo=None)
    else:
        timestamp = datetime(2024, 1, 1)  # Fallback default
```

### 6.3 Data Validation

```python
# src/api/models.py:136-151
@field_validator("price")
@classmethod
def validate_price_range(cls, v: Decimal) -> Decimal:
    """Validate that price is between 0 and 1 (exclusive)."""
    if v <= 0 or v >= 1:
        raise ValueError(f"Price must be between 0 and 1 (exclusive), got {v}")
    return v
```

**Enforced by Pydantic:** All `TradeResponse` objects must have valid prices.

---

## Part 7: Query Patterns and Performance

### 7.1 The Graph Queries

**Pagination Strategy:**
```python
# src/graph/client.py:120-169
skip = 0
while True:
    query = f"""
    {{
      orderFilledEvents(
        first: {max_per_query}  # 1000
        skip: {skip}
        where: {{maker: "{trader_address}"}}
        orderBy: timestamp
        orderDirection: desc
      ) {{
        # 13 fields
      }}
    }}
    """
    events = self.query(query)
    if len(events) < max_per_query:
        break
    skip += max_per_query
```

**Two Queries Per Trader:**
1. Query as MAKER: `where: {maker: "0x..."}`
2. Query as TAKER: `where: {taker: "0x..."}`

**Performance:**
- Instant (0 GB storage)
- No rate limits (Gateway API)
- Complete history (no 100-trade limit like REST API)

### 7.2 JBecker Queries

**DuckDB with Filter Pushdown:**
```python
# src/datasources/jbecker.py:115-137
query = """
SELECT *
FROM read_parquet({scan})
WHERE LOWER(maker) = LOWER($1) OR LOWER(taker) = LOWER($1)
ORDER BY timestamp DESC
"""
```

**Performance:**
- 33.5 GB dataset
- Filter pushdown: Only matching rows loaded
- Index lookup: TraderFileIndex maps addresses → specific parquet files
- Query time: 1-10 seconds for typical trader

**Whale Handling:**
```python
# Sub-batching for traders with 1500+ files
if len(files) > max_files_per_batch:
    for i in range(0, len(files), max_files_per_batch):
        sub_files = files[i : i + max_files_per_batch]
        # Query each batch separately
```

### 7.3 Database Indexes

**Trade Table Indexes:**
```python
# Composite index for trader history queries
Index("ix_trade_trader_timestamp", "trader_address", "timestamp")

# Composite index for market trade queries  
Index("ix_trade_market_trader", "market_id", "trader_address")
```

**Query Plans:**
```sql
-- Trader history (chronological)
SELECT * FROM trades 
WHERE trader_address = '0x...' 
ORDER BY timestamp DESC;
-- Uses: ix_trade_trader_timestamp

-- Market participants
SELECT DISTINCT trader_address FROM trades 
WHERE market_id = 'condition_123';
-- Uses: ix_trade_market_trader

-- Trader's position in market
SELECT * FROM trades 
WHERE trader_address = '0x...' AND market_id = 'condition_123';
-- Uses: ix_trade_market_trader
```

---

## Part 8: Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      DATA INGESTION                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐      ┌──────────────┐      ┌──────────────┐       │
│  │ The Graph   │      │ JBecker      │      │ Polymarket   │       │
│  │ (GraphQL)   │      │ (Parquet)    │      │ (REST API)   │       │
│  └──────┬──────┘      └──────┬───────┘      └──────┬───────┘       │
│         │                    │                      │               │
│         ▼                    ▼                      │               │
│  graph_trade_to_         jbecker_trade_            │               │
│  api_response()          to_api_response()         │               │
│         │                    │                      │               │
│         └──────────┬─────────┘                      │               │
│                    ▼                                 │               │
│         ┌──────────────────┐                         │               │
│         │  TradeResponse   │ ◄───────────────────────┘               │
│         │  (Pydantic)      │                                         │
│         └────────┬─────────┘                                         │
│                  │                                                   │
│                  ▼                                                   │
│         Token Catalog Lookup                                         │
│         (token_id → condition_id)                                    │
│                  │                                                   │
│         ┌────────┴────────┐                                          │
│         │                 │                                          │
│         ▼                 ▼                                          │
│   SUCCESS:            FAILURE:                                       │
│   condition_id        graph_{txHash}_{assetId}                       │
│   (11.4%)             (88.6%)                                        │
│         │                 │                                          │
│         └────────┬────────┘                                          │
│                  │                                                   │
│                  ▼                                                   │
│         TradeWithCategory wrapper                                    │
│                  │                                                   │
│                  ▼                                                   │
│         CategoryFilter routing                                       │
│                  │                                                   │
│         ┌────────┴────────┐                                          │
│         ▼                 ▼                                          │
│   Detail Storage      Summary Aggregation                            │
│   (target cats)       (non-target cats)                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 9: Field Mapping Reference

### 9.1 The Graph → TradeResponse

| Graph Field | TradeResponse Field | Transformation |
|-------------|---------------------|----------------|
| `id` | `id` | Direct copy |
| `maker` / `taker` | `trader` | Select based on queried address |
| `makerAssetId` / `takerAssetId` | `market` | Token catalog lookup or synthetic |
| `makerAmountFilled` / `takerAmountFilled` | `size` | Select based on role, divide by 1e6 |
| `price` | `price` | If >1, convert to `1/price` |
| `timestamp` | `timestamp` | `datetime.fromtimestamp()` |
| `side` | `side` | Flip if querying as taker |
| (derived) | `asset_ticker` | Odd/even check on asset ID |

### 9.2 JBecker → TradeResponse

| JBecker Field | TradeResponse Field | Transformation |
|---------------|---------------------|----------------|
| (derived) | `id` | `jbecker_{txHash}_{logIndex}` |
| `maker` / `taker` | `trader` | Select based on queried address |
| `maker_asset_id` / `taker_asset_id` | `market` | Token catalog lookup or synthetic |
| `maker_amount` / `taker_amount` | `size` | Select based on role, divide by 1e6 |
| (calculated) | `price` | `maker_amount / taker_amount` |
| `timestamp` or `_fetched_at` | `timestamp` | Use timestamp, fallback to _fetched_at |
| (derived) | `side` | Maker = SELL, Taker = BUY |
| (derived) | `asset_ticker` | Odd/even check on asset ID |

### 9.3 Trade → Database

| TradeResponse | Trade Table | Notes |
|---------------|-------------|-------|
| `id` | `trade_id` | Unique constraint |
| `market` | `market_id` | condition_id or graph_ placeholder |
| `trader` | `trader_address` | 0x... address |
| `side` | `side` | "BUY" or "SELL" |
| `size` | `size` | Numeric(20,6) |
| `price` | `price` | Numeric(10,6) |
| `timestamp` | `timestamp` | datetime |
| `asset_ticker` | `asset_ticker` | "YES", "NO", or NULL |

---

## Part 10: Key Statistics

### 10.1 Coverage Metrics

| Metric | Count | Percentage |
|--------|-------|------------|
| Total trades | 2,529,922 | 100% |
| Trades with real `condition_id` | 688,364 | 27.2% |
| Trades with `graph_` placeholder | 1,841,558 | **72.8%** |
| Token catalog coverage | 136,641 / 1,194,000 tokens | **11.4%** |

### 10.2 Orphaned Trades by Category

```
graph_ placeholder breakdown:
  Unknown:        1,650,000 (89.6% of orphaned)
  Other:            100,000 (5.4%)
  esports:           50,000 (2.7%)
  Crypto:            20,000 (1.1%)
  Sports:            10,000 (0.5%)
  Other niches:      11,558 (0.7%)
```

### 10.3 Resolution Impact

| Stage | Resolved | Blocked | Block Rate |
|-------|----------|---------|------------|
| Markets | 12,356 | 136,641 | **91.7%** |
| Positions | 70,822 | 26,238 | **27.1%** |

**Note:** Position block rate (27%) is lower than market block rate (91%) because:
- Many positions are in resolved markets
- Unresolved positions concentrated in "Unknown" category markets

---

## Part 11: Recommended Next Steps

### 11.1 Immediate Actions

1. **Expand Token Catalog:**
   - Query Polymarket CLOB API `/tokens` endpoint
   - Build complete `token_id` → `condition_id` mapping
   - Backfill existing `graph_` trades with resolved market IDs

2. **Gamma API Fallback:**
   - For `graph_` trades, query Gamma API by token ID
   - May return 404 for delisted markets
   - Could populate `end_date` and `outcome` for resolution

3. **CLOB API Historical Lookup:**
   - Query `/markets?conditionId={extracted_id}` for orphaned trades
   - May find markets not in Gamma API
   - Populate market metadata for resolution

### 11.2 Long-term Solutions

1. **Real-time Token Catalog:**
   - Listen to Conditional Token Factory events
   - Auto-register new tokens as they're created
   - Prevent future `graph_` placeholder creation

2. **Market Resolution Fallback:**
   - For markets not in Gamma API, use CLOB API
   - Query `/markets/{conditionId}` for outcome
   - Handle 404 as "delisted — cannot resolve"

3. **Data Quality Monitoring:**
   - Track `graph_` placeholder creation rate
   - Alert when token catalog lookup fails
   - Manual review queue for unknown tokens

---

## Appendix: Code References

| File | Purpose | Key Functions |
|------|---------|---------------|
| `src/graph/client.py` | The Graph subgraph client | `get_trader_trades()`, `query()` |
| `src/graph/converters.py` | Graph → API converter | `graph_trade_to_api_response()` |
| `src/datasources/jbecker.py` | JBecker parquet queries | `query_trader_history()`, `batch_query_traders_history()` |
| `src/datasources/converters.py` | JBecker → API converter | `jbecker_trade_to_api_response()`, `block_number_to_timestamp()` |
| `src/api/models.py` | Pydantic validation | `TradeResponse`, price validation |
| `src/db/models.py` | ORM models | `Trade`, `TokenCatalog`, `Market` |
| `src/pipeline/ingest.py` | Ingestion pipeline | Graph ingestion (lines 1430-1509) |
| `scripts/fetch_trader_graph.py` | Graph query script | Full trader history fetcher |

---

**Researcher:** opencode  
**Session Date:** 2026-03-25  
**Related:** `market-outcome-coverage-research.md`, `src/graph/`, `src/datasources/`
