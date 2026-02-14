# Polymarket Smart Money Tracker

A category-agnostic intelligence pipeline that identifies expert niche traders on Polymarket, scores their specialization depth, and surfaces consensus signals when multiple experts converge on positions.

**eSports is the first case study** — the architecture generalizes to any Polymarket category (politics, crypto, sports) via taxonomy configuration.

## What It Does

The Smart Money Tracker helps you see where informed traders are moving in niche prediction markets by:

1. **Discovering Active Traders** — Event-first approach finds who's trading in active eSports markets
2. **Evaluating Expertise** — Calculates performance metrics (PnL, win rate, consistency) across multiple timeframes
3. **Scoring Specialization** — Identifies game-level specialists vs generalists using concentration metrics
4. **Detecting Consensus** — Surfaces markets where 3+ expert traders (score >70) align on the same position
5. **Delivering Alerts** — Sends Telegram notifications when new signals emerge or strengthen
6. **CLI Interface** — Explore markets, traders, signals, and leaderboards via command-line tools

## Capabilities

### CLI Commands

```bash
# List active eSports markets
polymarket markets

# View trader profile (supports partial address matching)
polymarket trader 0xAbCd

# Show recent consensus signals
polymarket signals --window 6      # 6-hour window
polymarket signals --min-conf 80   # High-confidence signals only

# View game-specific expert leaderboards
polymarket leaderboard esports.cs2
polymarket leaderboard esports.lol

# Research trader history offline (requires JBecker dataset)
polymarket research 0xAbCd         # Table output
polymarket research 0xAbCd --output json --limit 100

# Bulk ingest traders from JBecker dataset
polymarket batch-analyze 0xAddr1 0xAddr2
polymarket batch-analyze --file traders.txt

# Run manual signal detection sweep
polymarket sweep

# Start automated hourly polling
polymarket poll --interval 60      # Poll every 60 minutes
```

### Intelligence Features

- **Expert Consensus Detection**: Identifies when 3+ expert traders take the same position with 75%+ agreement
- **Confidence Scoring**: 0-100 score combining agreement %, sample size, and position uniformity
- **First-Mover Tracking**: Distinguishes early movers from fast-followers (6-hour window)
- **Signal Event Classification**: NEW, STRENGTHENING, WEAKENING, LOST
- **Specialization Metrics**: Game-level concentration (CS2 specialist vs eSports generalist)
- **Consistency Detection**: Cross-timeframe stability analysis (30d, 90d, all-time)
- **Multi-Source Data**: 4-tier cost-optimized ingestion (JBecker → API → Graph → Blockchain)
- **Offline Research**: Query complete trader histories from 33.5GB historical dataset

### Data Sources

The system uses a **4-tier cost-optimized hierarchy** for trader history:

1. **JBecker Dataset** (Primary, FREE)
   - 33.5GB Parquet archive of all Polymarket trades
   - Complete historical coverage
   - Instant DuckDB queries with filter pushdown
   - Requires one-time download (~140GB uncompressed)

2. **Polymarket API** (Gap Fill, FREE)
   - Recent 100 trades per trader
   - Fills gap between JBecker snapshot and current
   - 50 req/s rate limit

3. **The Graph** (If Insufficient, PAID)
   - Polymarket Orderbook subgraph
   - Instant queries (~3 seconds for 2,000+ trades)
   - Costs API units
   - Only called when API maxes out

4. **Polygon Blockchain** (Last Resort, SLOW)
   - Complete history via RPC
   - 6-7 hours per trader (49M blocks)
   - Fallback for maximum completeness

**Cost optimization achieved:** JBecker + API covers ~99.9% of traders for FREE, minimizing Graph API consumption for bulk analysis.

## Installation

### Prerequisites

- Python 3.10+ (virtual environment required for Homebrew Python)
- SQLite 3.x
- Telegram bot (optional, for alerts)

### Setup

1. **Clone and enter directory:**
   ```bash
   cd GSD_Polymarket
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -e .
   ```

4. **Configure environment variables** (create `.env` or export):
   ```bash
   # Optional: Telegram alerts (get from @BotFather)
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"

   # Optional: The Graph API for fast historical queries
   export THE_GRAPH_API_KEY="your_graph_api_key"

   # Optional: Custom settings
   export POLYMARKET_API_HOST="https://clob.polymarket.com"
   export DATABASE_URL="sqlite:///./polymarket.db"
   export TAXONOMY_PATH="./taxonomy/esports.yaml"
   ```

5. **Verify installation:**
   ```bash
   polymarket --help
   ```

## Getting Started

### First Run

The database auto-creates on first use:

```bash
# Run your first sweep (ingests markets, scores traders, detects signals)
polymarket sweep
```

This will:
- Fetch active eSports events from Polymarket
- Discover traders from market order books
- Evaluate their historical performance
- Calculate expertise scores
- Detect consensus signals
- Send Telegram alerts (if configured)

### Exploring Data

```bash
# See active markets
polymarket markets

# Check signals
polymarket signals

# View top CS2 traders
polymarket leaderboard esports.cs2

# Look up a specific trader
polymarket trader 0x1234...
```

### Automated Monitoring

```bash
# Start hourly polling (runs in foreground)
polymarket poll

# Custom interval (every 30 minutes)
polymarket poll --interval 30

# Dry-run mode (no alerts)
polymarket poll --no-alerts
```

Press `Ctrl+C` for graceful shutdown.

## Configuration

### Settings File

All settings have sensible defaults. Override via environment variables:

```bash
# Database
DATABASE_URL="sqlite:///./polymarket.db"

# API
POLYMARKET_API_HOST="https://clob.polymarket.com"
MAX_REQUESTS_PER_SECOND=50

# Taxonomy
TAXONOMY_PATH="./taxonomy/esports.yaml"
DETAIL_CATEGORIES='["eSports"]'

# Polling
POLL_INTERVAL_MINUTES=60

# Alerts
TELEGRAM_BOT_TOKEN=""           # Leave empty to disable alerts
TELEGRAM_CHAT_ID=""
ALERT_RETRY_MAX_ATTEMPTS=5
ALERT_RETRY_MIN_WAIT=2.0
ALERT_RETRY_MAX_WAIT=60.0
ALERT_DEDUP_TTL_MINUTES=60
```

### Telegram Setup (Optional)

1. Create bot via [@BotFather](https://t.me/BotFather)
2. Copy the HTTP API token → `TELEGRAM_BOT_TOKEN`
3. Send a message to your bot
4. GET `https://api.telegram.org/bot<token>/getUpdates`
5. Find `chat.id` in response → `TELEGRAM_CHAT_ID`

### JBecker Historical Dataset (Optional)

For offline research and bulk trader analysis, download Jon Becker's complete Polymarket trade history:

1. **Download dataset** (33.5GB compressed, ~140GB uncompressed):
   ```bash
   wget https://s3.jbecker.dev/data.tar.zst
   ```

2. **Extract** (requires zstd):
   ```bash
   # macOS
   brew install zstd
   tar --use-compress-program=unzstd -xvf data.tar.zst

   # Linux
   sudo apt install zstd
   tar -I zstd -xvf data.tar.zst
   ```

3. **Configure path**:
   ```bash
   export JBECKER_DATA_PATH="./data/polymarket/trades"
   ```

4. **Verify**:
   ```bash
   polymarket research 0xeffd76b6a4318d50c6f71a16b276c5b279445a86 --limit 10
   ```

The dataset enables:
- Complete trader history (no 100-trade API limit)
- Offline research (no API keys needed)
- Cost-free bulk analysis (minimal Graph API consumption)

## Architecture

### Data Flow

```
Data Sources (4-tier fallback)
  JBecker Dataset (primary, free, complete historical)
    ↓ (gap fill)
  Polymarket API (recent 100 trades, free)
    ↓ (if insufficient)
  The Graph (instant queries, costs API units)
    ↓ (last resort)
  Polygon Blockchain (complete, 6-7 hours per trader)
  ↓ (ingest)
SQLite Database
  ↓ (classify)
Taxonomy Matching
  ↓ (evaluate)
Performance Metrics
  ↓ (score)
Expertise Scores
  ↓ (detect)
Consensus Signals
  ↓ (alert)
Telegram
```

### Pipeline Stages

1. **Foundation** (Phase 1): API client, rate limiting, database schema
2. **Classification** (Phase 2): YAML taxonomy, position tracking, trader discovery
3. **Evaluation** (Phase 3): PnL calculation, win rates, consistency detection
4. **Scoring** (Phase 4): Concentration metrics, composite scoring, leaderboards
5. **Signals** (Phase 5): Consensus detection, confidence scoring, first-mover tracking
6. **Alerts** (Phase 6): Event detection, Telegram formatting, delivery orchestration
7. **CLI** (Phase 7): Commands, formatters, polling scheduler
8. **Blockchain History** (Phase 8): Polygon RPC integration, complete trade history (workaround for 100-trade API limit)
9. **JBecker Dataset** (Phase 9): DuckDB query layer, 4-tier cost-optimized ingestion, offline research commands

### Key Design Decisions

- **Event-first discovery**: Start from active events → find traders → backtrack history (avoids scanning entire trader database)
- **Category-agnostic**: eSports is first case study; architecture extends to any Polymarket category via taxonomy YAML
- **4-tier cost optimization**: JBecker (free) → API (free) → Graph (paid) → Blockchain (slow) - minimizes costs while maximizing coverage
- **Local-first storage**: SQLite with WAL mode (no external database required)
- **Token bucket rate limiting**: 50 req/s (80% of 60/s sustained limit)
- **Numeric precision**: Decimal types for all financial calculations (no float errors)
- **TDD approach**: 509 tests (100% passing) across all components

## Testing

```bash
# Run all tests
pytest

# Run specific phase tests
pytest tests/test_formatters.py
pytest tests/test_scheduler.py

# Verbose output
pytest -v

# With coverage
pytest --cov=src --cov-report=term-missing
```

**Test Stats:**
- Total: 509 tests (100% passing)
- Foundation: 62
- Classification: 51
- Evaluation: 121
- Scoring: 73
- Signals: 55
- Alerts: 39
- CLI: 37
- Blockchain: 35
- JBecker Dataset: 53

## Project Structure

```
GSD_Polymarket/
├── src/
│   ├── api/           # Polymarket CLOB client
│   ├── db/            # SQLAlchemy models and session
│   ├── config/        # Settings and configuration
│   ├── pipeline/      # Ingestion, scoring, queries
│   ├── taxonomy/      # YAML loader and classifier
│   ├── signals/       # Consensus detection
│   ├── alerts/        # Telegram delivery
│   ├── cli/           # Click commands and formatters
│   ├── blockchain/    # Polygon RPC client
│   ├── graph/         # The Graph subgraph client
│   └── datasources/   # JBecker dataset & converters
├── tests/             # Comprehensive test suite (509 tests)
├── taxonomy/          # eSports game taxonomy (YAML)
├── data/              # JBecker dataset (optional, 140GB)
├── .planning/         # GSD workflow artifacts
└── pyproject.toml     # Dependencies and entry point
```

## Extending to New Categories

The pipeline is designed to be category-agnostic. To add a new category:

1. **Create taxonomy YAML** (e.g., `taxonomy/politics.yaml`):
   ```yaml
   - slug: politics.us-elections
     keywords: [election, presidential, senate]
     teams: ["Democratic Party", "Republican Party"]
   ```

2. **Update settings**:
   ```bash
   export DETAIL_CATEGORIES='["eSports", "Politics"]'
   ```

3. **Run sweep**:
   ```bash
   polymarket sweep
   ```

The same expertise scoring, consensus detection, and alerting logic applies to any category.

## Performance

- **Average plan execution**: 5.56 minutes
- **Full sweep** (ingest → score → detect → alert): ~2-5 minutes
- **JBecker query**: ~100ms for 2,000+ trades (DuckDB filter pushdown)
- **The Graph query**: ~3 seconds for complete trader history (if dataset unavailable)
- **Blockchain scan**: 6-7 hours per trader for complete history (fallback only)
- **Database size**: ~50-100 MB for 1000 markets, 5000 traders
- **API rate**: 50 req/s with automatic retry on 429
- **Memory footprint**: ~200 MB typical

## Debugging

All CLI commands automatically log to `logs/cli_session.log` for debugging and monitoring.

**View logs in real-time:**
```bash
./view_logs.sh tail
```

**Quick check (last 50 lines):**
```bash
./view_logs.sh last
```

**Search for errors:**
```bash
grep ERROR logs/cli_session.log
```

See [LOGGING.md](LOGGING.md) for complete logging documentation.

## Troubleshooting

### "No module named 'src'"

Ensure you're in the virtual environment:
```bash
source .venv/bin/activate
pip install -e .
```

### "Rate limit exceeded"

The client automatically retries with exponential backoff. If persistent:
```bash
export MAX_REQUESTS_PER_SECOND=30  # Lower rate
```

### "No signals found"

This is normal if no expert consensus exists yet. Run a sweep to refresh:
```bash
polymarket sweep
```

### Database locked

SQLite WAL mode prevents most locks. If persistent, check for other processes:
```bash
fuser polymarket.db  # Linux/Mac
```

## License

MIT License - see LICENSE file for details.

## Contributing

This project was built using the GSD (Get Shit Done) workflow. See `.planning/` for complete planning artifacts, execution history, and verification reports.

## Roadmap

**v1.0 (Current)**: Complete eSports Intelligence Pipeline
- ✅ All 9 phases complete
- ✅ 509 tests passing (100%)
- ✅ 4-tier cost-optimized data ingestion
- ✅ Offline research capability with JBecker dataset
- ✅ Production-ready

**Future enhancements:**
- Additional categories (politics, crypto, sports)
- Web dashboard for visualization
- Historical signal performance tracking
- Multi-channel alert routing (Discord, Slack)
- Advanced herding detection (currently stubbed)
- Real-time WebSocket feeds

---

**Questions?** Check `.planning/PROJECT.md` for design decisions and requirements.

**Built with**: Python, SQLAlchemy, Click, Rich, py-clob-client, python-telegram-bot, DuckDB, web3.py, gql
