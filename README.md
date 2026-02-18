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

# Deep Niche Scoring - Leaderboard at any taxonomy depth
polymarket leaderboard esports.cs2.iem-katowice --depth tournament
polymarket leaderboard esports.cs2.iem-katowice.navi --depth team

# Show trader's expertise breakdown across all taxonomy depths
polymarket expertise 0xTrader123

# Discover hidden specialists in a game
polymarket specialists esports.cs2
polymarket specialists esports.cs2 --game-threshold 50 --deep-threshold 80

# Pipeline Decoupling - Run discovery and backfill independently
polymarket discover                    # Find traders without backfilling
polymarket backfill                    # Backfill discovered traders
polymarket status                      # Show discovery/backfill status

# Targeted Market Scanning - Filter by niche and time
polymarket sweep --niche esports --niche crypto                    # Scan specific niches
polymarket sweep --closing-within 48h   # Only markets closing within 48 hours
polymarket sweep --niche esports --closing-within 24h             # Combined filters

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

# Resolve trader profiles (proxy wallet → real Polymarket profiles)
polymarket resolve-profiles                    # Resolve all pending
polymarket resolve-profiles --limit 50         # Limit to 50 traders
```

### Intelligence Features

- **Expert Consensus Detection**: Identifies when 3+ expert traders take the same position with 75%+ agreement
- **Confidence Scoring**: 0-100 score combining agreement %, sample size, and position uniformity
- **First-Mover Tracking**: Distinguishes early movers from fast-followers (6-hour window)
- **Signal Event Classification**: NEW, STRENGTHENING, WEAKENING, LOST
- **Specialization Metrics**: Game-level concentration (CS2 specialist vs eSports generalist)
- **Deep Niche Scoring**: Tournament and team-level expertise scoring beyond game level
- **Hidden Specialist Detection**: Finds traders with average game scores but high tournament/team scores
- **Targeted Market Scanning**: Filter by niche category and time-to-close window
- **Consistency Detection**: Cross-timeframe stability analysis (30d, 90d, all-time)
- **Multi-Source Data**: 4-tier cost-optimized ingestion (JBecker → API → Graph → Blockchain)
- **Offline Research**: Query complete trader histories from 33.5GB historical dataset
- **Profile Resolution**: Map proxy wallets to real Polymarket user profiles

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

## Targeted Market Scanning (v1.1)

Instead of scanning all markets, you can filter by niche category and time-to-close:

### Filters

**--niche / -n**: Filter by category (repeatable)
- `esports` — eSports markets only
- `crypto` — Cryptocurrency markets
- Can combine: `--niche esports --niche crypto`

**--closing-within**: Only scan markets closing within time window
- `24h` — Markets closing within 24 hours
- `48h` — Markets closing within 48 hours
- `7d` — Markets closing within 7 days

### Examples

```bash
# Scan only eSports markets
polymarket sweep --niche esports

# Scan multiple niches
polymarket sweep --niche esports --niche crypto

# Scan markets closing soon
polymarket sweep --closing-within 48h

# Combined: eSports closing within 24 hours
polymarket sweep --niche esports --closing-within 24h

# Run signal detection on targeted markets
polymarket signals --niche esports
```

### How It Works

The Gamma API client sends niche and time filters directly to the API, avoiding client-side filtering. This reduces:
- API calls (fewer markets fetched)
- Processing time (less data to filter)
- Database writes (only relevant markets stored)

## Deep Niche Scoring (v1.1)

The system now scores expertise at three taxonomy depths:

| Depth | Level | Example | Description |
|-------|-------|---------|-------------|
| 1 | Game | `esports.cs2` | CS2 specialists |
| 2 | Tournament | `esports.cs2.iem-katowice` | IEM Katowice specialists |
| 3 | Team | `esports.cs2.iem-katowice.navi` | NaVi specialists |

### Key Concepts

**Tournament Concentration**: Fraction of game volume in a specific tournament
- `tournament_volume / game_volume` — High values = focused on specific tournaments

**Team Concentration**: Fraction of tournament volume for a specific team
- `team_volume / tournament_volume` — High values = team specialists

**Hidden Specialists**: Traders with average game scores but exceptional tournament/team scores
- Example: Trader with 55 game score but 85 tournament score in IEM Katowice
- These are "Chelsea traders" — experts in specific niches

### Commands

```bash
# Game leaderboard (default, depth=1)
polymarket leaderboard esports.cs2

# Tournament leaderboard (depth=2)
polymarket leaderboard esports.cs2.iem-katowice --depth tournament

# Team leaderboard (depth=3)
polymarket leaderboard esports.cs2.iem-katowice.navi --depth team

# Show trader's expertise breakdown
polymarket expertise 0xTrader123

# Discover hidden specialists
polymarket specialists esports.cs2

# Custom thresholds
polymarket specialists esports.cs2 --game-threshold 50 --deep-threshold 80
```

## Profile Resolution (v1.2)

Many trader addresses in the database are proxy wallets (smart contracts deployed by Polymarket), not actual user accounts. When you search these on polymarket.com, they show no profile. Profile resolution maps proxy addresses to real Polymarket profiles.

### What It Does

1. **Resolves proxy wallets** — Maps trading addresses to real user profiles
2. **Identifies real traders** — Filters out bots/contracts without profiles
3. **Stores profile metadata** — Captures display names, avatars, bio

### How It Works

The system queries the Polymarket public profile API:

```
GET https://gamma-api.polymarket.com/public-profile?address={address}
```

Returns:
- `proxyWallet` — The proxy contract address (on-chain trading address)
- `name` — Display name
- `pseudonym` — Auto-generated pseudonym
- `bio` — User bio
- `profileImage` — Avatar URL
- `createdAt` — Profile creation timestamp

### Commands

```bash
# Resolve profiles for all pending traders
polymarket resolve-profiles

# Limit to 50 traders
polymarket resolve-profiles --limit 50

# Show progress and summary
# Output:
# Resolving profiles... 200 traders pending
# [################] 200/200
# Found 45 profiles, 155 no profile
```

### Database Columns

The `traders` table gets new columns:

| Column | Type | Description |
|--------|------|-------------|
| `proxy_wallet` | VARCHAR(42) | Proxy contract address from API |
| `display_name` | VARCHAR(100) | Human-readable name or pseudonym |
| `profile_resolved` | BOOLEAN | Whether we've attempted resolution |
| `has_profile` | BOOLEAN | Whether profile exists on Polymarket |

The system automatically migrates existing databases by adding these columns.

### Integration

Profile resolution runs after trader discovery to enrich trader data:

```bash
# Discover new traders
polymarket discover

# Resolve their profiles
polymarket resolve-profiles

# Then backfill history
polymarket backfill
```

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
8. **Blockchain History** (Phase 8): Polygon RPC integration, complete trade history
9. **JBecker Dataset** (Phase 9): DuckDB query layer, 4-tier cost-optimized ingestion
10. **Targeted Market Scanning** (Phase 10): Niche filters, time-to-close filters
11. **Pipeline Decoupling** (Phase 11): Independent discover/backfill commands
12. **Deep Niche Scoring** (Phase 12): Tournament/team-level expertise, hidden specialists
13. **Profile Resolution** (Phase 13): Proxy wallet → real Polymarket profile mapping

### Key Design Decisions

- **Event-first discovery**: Start from active events → find traders → backtrack history
- **Category-agnostic**: eSports is first case study; architecture extends to any category via taxonomy YAML
- **4-tier cost optimization**: JBecker (free) → API (free) → Graph (paid) → Blockchain (slow)
- **Multi-depth scoring**: Game (depth 1), tournament (depth 2), team (depth 3) for granular expertise
- **Hidden specialist detection**: Find niche experts that game-level scoring misses
- **Local-first storage**: SQLite with WAL mode (no external database required)
- **Token bucket rate limiting**: 50 req/s (80% of 60/s sustained limit)
- **Numeric precision**: Decimal types for all financial calculations (no float errors)
- **TDD approach**: 576 tests (100% passing) across all components

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
- Total: 576 tests (100% passing)
- Foundation: 62
- Classification: 51
- Evaluation: 121
- Scoring: 73
- Signals: 55
- Alerts: 39
- CLI: 46
- Blockchain: 35
- JBecker Dataset: 53
- Deep Scoring: 29

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

**v1.2 (Current)**: Profile Resolution
- ✅ Phase 13: Proxy wallet → real Polymarket profile mapping
- ✅ Profile resolution CLI command
- ✅ Automatic database migration for existing databases
- ✅ Production-ready

---

**v1.1 (Previous)**: Targeted Scanning & Deep Niche Scoring
- ✅ Phase 10: Targeted Market Scanning (niche + time filters)
- ✅ Phase 11: Pipeline Decoupling (independent discover/backfill)
- ✅ Phase 12: Deep Niche Scoring (tournament/team levels, hidden specialists)
- ✅ 576 tests passing (100%)
- ✅ Production-ready

---

**Questions?** Check `.planning/PROJECT.md` for design decisions and requirements.

**Built with**: Python, SQLAlchemy, Click, Rich, py-clob-client, python-telegram-bot, DuckDB, web3.py, gql
