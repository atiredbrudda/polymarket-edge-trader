# Storage-Light Alternatives for Trader History

You don't want 100GB eating your computer. Here are practical alternatives:

---

## ✅ BEST: The Graph Subgraph (Zero Storage!)

**Polymarket has an official Graph subgraph** - query trades without downloading anything!

### What You Get
- **Zero storage** - all data queried remotely via GraphQL
- **Always up-to-date** - live blockchain data
- **Instant queries** - indexed, optimized lookups
- **Free tier available** - no hosting costs

### Subgraph Details
- **Repository**: https://github.com/Polymarket/polymarket-subgraph
- **Endpoint**: `https://gateway.thegraph.com/api/{api-key}/subgraphs/id/Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp`
- **Multiple subgraphs**:
  - `activity-subgraph` - Trading activity
  - `orderbook-subgraph` - Order book data
  - `pnl-subgraph` - Profit/loss tracking
  - `wallet-subgraph` - Wallet data

### Next Steps
1. **Get API key** from The Graph: https://thegraph.com/studio/
2. **Check schema** to see what queries are available
3. **Build integration** to replace our blockchain scanning

Example query (hypothetical - need to verify schema):
```graphql
query GetTraderHistory($address: String!) {
  trades(
    where: {
      or: [
        { maker: $address },
        { taker: $address }
      ]
    }
    orderBy: blockNumber
    orderDirection: desc
  ) {
    id
    maker
    taker
    makerAmount
    takerAmount
    makerAssetId
    takerAssetId
    blockNumber
    timestamp
  }
}
```

**TODO**: Verify schema supports trader address filtering!

---

## Option 2: Cloud VM (One-Time Setup)

Don't store locally - use a $5-12/month cloud server:

### Providers
- **DigitalOcean Droplet**: $12/mo, 160GB SSD
- **AWS EC2 t3.medium (spot)**: ~$5/mo
- **Hetzner Cloud**: €4.51/mo, 160GB SSD

### Setup
```bash
# On cloud server
cd /tmp
git clone https://github.com/Jon-Becker/prediction-market-analysis.git
cd prediction-market-analysis
make setup  # Downloads 36GB

# Query from your laptop via SSH
ssh myserver "cd /tmp/prediction-market-analysis && python query.py 0x..."
```

**Pros**: Full dataset, unlimited queries
**Cons**: Monthly cost, need to maintain server

---

## Option 3: Download → Query → Delete

Use `/tmp` for temporary storage (auto-cleaned on reboot):

```bash
# Download to /tmp
cd /tmp/prediction-market-analysis
make setup

# Query what you need
python query_jbecker_dataset.py 0xADDRESS > trader_data.csv

# Delete or just reboot (macOS clears /tmp)
rm -rf data/
```

**Pros**: Zero long-term storage
**Cons**: Re-download for each analysis session

---

## Option 4: Lightweight Trader Index (Custom Solution)

Build a tiny index instead of storing full dataset:

### Concept
```
1. One-time: Scan Jon-Becker's parquet files
2. Extract: trader_address → [file_offset, block_number]
3. Store: ~1MB SQLite index with trader → data location mapping
4. Query: Fetch specific trades via HTTP range requests
```

### Implementation
```python
# index_builder.py
# Scans parquet, creates trader index
{
  "0xADDRESS": [
    {"file": "chunk_0042.parquet", "offset": 1234, "block": 35000000},
    {"file": "chunk_0043.parquet", "offset": 5678, "block": 35001000}
  ]
}

# query_trader.py
# Looks up trader in index, fetches only relevant chunks
curl -r OFFSET-OFFSET https://s3.jbecker.dev/... | parse_parquet
```

**Pros**: ~1MB storage, on-demand fetching
**Cons**: Need to build and maintain index

---

## Option 5: Accept API Limits (Pragmatic)

Real question: **Do you need complete history?**

### API Gives You
- **100 most recent trades** per trader
- Usually covers last 30-90 days for active traders
- Sufficient for:
  - Recent performance metrics
  - Current specialization scoring
  - Signal detection (24h activity)

### When Complete History Matters
- Long-term win rate analysis
- Detecting strategy changes over years
- Historical backtesting

### When It Doesn't
- Real-time signal detection
- Current expert identification
- Recent consensus tracking

**Trade-off**: Zero storage, but miss old trades

---

## Option 6: DuckDB Streaming (Partial Download)

Download one parquet file at a time, query, discard:

```python
import duckdb
import requests

parquet_files = [...]  # List from Jon-Becker's dataset
trader_address = "0x..."

all_trades = []
for url in parquet_files:
    # Download to temp
    r = requests.get(url, stream=True)
    with open('/tmp/temp.parquet', 'wb') as f:
        f.write(r.content)

    # Query
    trades = duckdb.sql(f"""
        SELECT * FROM '/tmp/temp.parquet'
        WHERE maker = '{trader_address}' OR taker = '{trader_address}'
    """).df()

    all_trades.append(trades)

    # Discard
    os.remove('/tmp/temp.parquet')
```

**Pros**: Max ~500MB storage at once
**Cons**: Slower (serial processing), still downloads full dataset

---

## Recommendation Matrix

| Your Priority | Best Option | Storage | Cost | Speed |
|---------------|-------------|---------|------|-------|
| Zero storage | **The Graph** | 0 GB | Free* | Instant |
| Complete history | **Cloud VM** | Remote | $5-12/mo | Fast |
| One-time query | **Download → Delete** | Temp | Free | Medium |
| Regular queries | **The Graph** or Cloud | 0 or Remote | Varies | Fast |
| Budget = $0 | **API limits** or Graph | 0 GB | Free | Instant |

*The Graph has free tier, paid for heavy usage

---

## Next Action: Verify The Graph Support

**Critical TODO**: Check if Polymarket's subgraph schema supports trader address filtering!

```bash
# Test query (need API key)
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "{__schema{queryType{fields{name}}}}"}' \
  https://gateway.thegraph.com/api/YOUR_KEY/subgraphs/id/Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp

# Look for: trades, user, maker, taker entities
```

If The Graph supports it → **Build integration, problem solved!**
If not → **Cloud VM or accept API limits**

---

## Sources
- [Polymarket Subgraph](https://github.com/Polymarket/polymarket-subgraph)
- [Polymarket Docs - Subgraph Overview](https://docs.polymarket.com/developers/subgraph/overview)
- [The Graph Explorer - Polymarket](https://thegraph.com/explorer/subgraphs/Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp)
- [Querying Polymarket with Subgraphs Guide](https://thegraph.com/docs/en/subgraphs/guides/polymarket/)
