# Polymarket Edge Tracker

A category-agnostic intelligence pipeline that identifies edge traders on Polymarket — wallets whose entries consistently beat the market's implied probability — and surfaces consensus signals when multiple edge traders converge on the same position.

**eSports is the first case study** — the architecture generalizes to any Polymarket category via taxonomy configuration.

## What It Does

1. **Discovers traders** from active eSports markets (event-first approach)
2. **Extracts entities** (teams, tournaments, games) from each market via pattern matcher + LLM fallback
3. **Backfills trade history** using a 4-tier cost-optimized hierarchy (JBecker → API → Graph → Blockchain)
4. **Resolves outcomes** — determines win/loss for every position using Gamma Events API data
5. **Scores traders** — z(CLV) + z(ROI) + z(Sharpe) composite lift score, Q5 = top 20% = "smart money"
6. **Detects consensus** — surfaces markets where Q5 traders converge on the same position
7. **Delivers alerts** — Telegram notifications for new/strengthening signals

## Full Pipeline

### First-Time Setup (run once)

These commands download reference data and build the classification layer. Safe to re-run (idempotent).

```bash
# 1. Download ~8,500 closed eSports events from Gamma API (~30s)
polymarket ingest-events

# 2. Populate markets.outcome (YES/NO) for all resolved markets
polymarket resolve-outcomes

# 3. Classify tokens at game/tournament/team depth from Gamma event tags
polymarket classify-tokens

# 4. Fill any token_catalog gaps (local join → API → category-only fallback)
polymarket patch-catalog
```

### Regular Pipeline Run

Run this whenever you want fresh intelligence. Each step feeds the next.

```bash
# 1. Find traders from active markets + extract entities (teams/tournaments)
polymarket discover --niche esports

# 2. Fetch full trade history for all pending traders
polymarket backfill

# 3. Compute win/loss + PnL for each position using resolved outcomes
polymarket resolve-positions

# 4. Compute lift-based scores (z(CLV)+z(ROI)+z(Sharpe)), 30-day rolling window
polymarket score

# 5. Detect Q5 expert consensus on active markets
polymarket detect

# 6. Send Telegram alerts for new/strengthening signals
polymarket alert
```

### Copy-Paste One-Liners

```bash
# First-time setup
polymarket ingest-events && polymarket resolve-outcomes && polymarket classify-tokens && polymarket patch-catalog

# Regular run
polymarket discover --niche esports && polymarket backfill && polymarket resolve-positions && polymarket score && polymarket detect && polymarket alert

# Re-score without re-discovering (after code changes, etc.)
polymarket resolve-positions && polymarket score && polymarket detect
```

## Viewing Results

```bash
# Q5 leaderboard (top quintile traders by lift score)
polymarket analyze

# Q5 consensus signals with price context
polymarket analyze --signals

# Full leaderboard (all quintiles) by category
polymarket leaderboard esports

# Active consensus signals
polymarket signals

# Individual trader profile
polymarket trader 0xAddress

# Per-team win/loss stats for a trader
polymarket team-stats 0xAddress

# Pipeline status (discovery/backfill progress)
polymarket status
```

## All Commands

| Command | Description |
|---------|-------------|
| `discover` | Find traders from active markets, extract entities via LLM |
| `backfill` | Fetch full trade history (4-tier: JBecker → API → Graph → Blockchain) |
| `ingest-events` | Download closed eSports events from Gamma API |
| `resolve-outcomes` | Populate `markets.outcome` from Gamma event data |
| `classify-tokens` | Set token `node_path`/`depth` from Gamma event tags |
| `patch-catalog` | Auto-fix token_catalog gaps (3-tier patcher) |
| `recover-catalog` | Populate `markets.tokens` for null-token eSports markets |
| `resolve-positions` | Compute win/loss + PnL per position |
| `score` | Compute lift-based scores (z(CLV)+z(ROI)+z(Sharpe)) |
| `detect` | Detect Q5 expert consensus signals |
| `alert` | Deliver signals via Telegram |
| `analyze` | Q5 leaderboard or `--signals` for consensus signals |
| `leaderboard` | Full Q1-Q5 ranked traders with CLV/ROI/Sharpe breakdown |
| `signals` | View active consensus signals |
| `trader` | Individual trader profile |
| `team-stats` | Per-team win/loss stats for a trader |
| `expertise` | Trader expertise breakdown across taxonomy depths |
| `specialists` | Find hidden specialists in a game |
| `markets` | List active markets |
| `status` | Pipeline discovery/backfill progress |
| `poll` | Automated polling loop (hourly by default) |
| `research` | Query trader history from JBecker dataset (offline) |
| `batch-analyze` | Bulk ingest from JBecker dataset |
| `catalog-stats` | Token catalog coverage statistics |
| `resolve-profiles` | Map proxy wallets to Polymarket profiles |
| `backfill-classifications` | Classify markets pre-dating ingest-events |
| `reset-backfill` | Clear JBecker trades and reset backfill state |
| `build-index` | Build trader-to-file index for JBecker lookups |

## Installation

### Prerequisites

- Python 3.10+
- SQLite 3.x

### Setup

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it (run this every new terminal session)
source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate     # Windows

# Install the project
pip install -e .

# Verify
polymarket --help
```

### Environment Variables

Create `.env` or export:

```bash
# Optional: Telegram alerts
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"

# Optional: The Graph API (paid, for fast historical queries)
THE_GRAPH_API_KEY="your_key"

# Optional: Anthropic API (for LLM entity extraction during discover)
ANTHROPIC_API_KEY="your_key"

# Optional: JBecker dataset path
JBECKER_DATA_PATH="./data"
```

### JBecker Dataset (Optional)

For offline research and free bulk trader analysis:

```bash
# Download (33.5GB compressed)
wget https://s3.jbecker.dev/data.tar.zst

# Extract (requires zstd)
brew install zstd  # macOS
tar --use-compress-program=unzstd -xvf data.tar.zst

# Configure
export JBECKER_DATA_PATH="./data"

# Verify
polymarket research 0xeffd76b6a4318d50c6f71a16b276c5b279445a86 --limit 10
```

### Telegram Setup (Optional)

1. Create bot via [@BotFather](https://t.me/BotFather)
2. Copy the API token → `TELEGRAM_BOT_TOKEN`
3. Send a message to your bot, then GET `https://api.telegram.org/bot<token>/getUpdates`
4. Find `chat.id` → `TELEGRAM_CHAT_ID`

## Discover Options

```bash
# Filter by category
polymarket discover --niche esports
polymarket discover --niche esports --niche crypto

# Filter by time-to-close
polymarket discover --closing-within 24h
polymarket discover --niche esports --closing-within 48h
```

## Architecture

```
Gamma Events API → gamma_events table
                     ├── resolve-outcomes → markets.outcome (YES/NO)
                     └── classify-tokens  → token_catalog.node_path/depth

Polymarket API → discover → traders + market_entities (LLM extraction)
                    └── backfill → trades (4-tier: JBecker/API/Graph/Blockchain)
                           └── patch-catalog (auto-heal gaps)

                resolve-positions → positions (win/loss/PnL)
                    └── score → lift_scores (z(CLV)+z(ROI)+z(Sharpe))
                        └── detect → signals (Q5 consensus)
                            └── alert → Telegram
```

### Data Sources (4-tier hierarchy)

| Tier | Source | Cost | Speed | Coverage |
|------|--------|------|-------|----------|
| 1 | JBecker Dataset | Free | ~100ms | Complete historical |
| 2 | Polymarket API | Free | ~1s | Recent 100 trades |
| 3 | The Graph | Paid | ~3s | Complete |
| 4 | Polygon Blockchain | Free | ~6-7 hrs | Complete |

JBecker + API covers ~99.9% of traders for free.

### Key Design Decisions

- **Event-first discovery** — start from active events, not the full trader database
- **Lift-based scoring** — z(CLV)+z(ROI)+z(Sharpe), validated through 348-experiment backtest
- **Pattern-match-first entity extraction** — regex before LLM to minimize API costs
- **Category-agnostic** — add categories via YAML taxonomy files
- **Local-first** — SQLite with WAL mode, no external database needed
- **Idempotent commands** — every pipeline step is safe to re-run

## Project Structure

```
src/
├── api/           # Polymarket CLOB + Gamma API clients
├── db/            # SQLAlchemy models and session
├── config/        # Settings
├── pipeline/      # Ingestion, scoring, queries
├── taxonomy/      # YAML loader and classifier
├── signals/       # Consensus detection
├── alerts/        # Telegram delivery
├── cli/           # Click commands and formatters
├── blockchain/    # Polygon RPC client
├── graph/         # The Graph subgraph client
├── datasources/   # JBecker dataset & converters
├── catalog/       # Token catalog builder + patcher
├── gamma/         # Gamma events ingestion, resolution, classification
├── extraction/    # LLM + pattern matcher entity extraction
└── org_mapping/   # TraderTeamStats, team-level queries
```

## Testing

```bash
pytest              # Run all tests
pytest -v           # Verbose
pytest --cov=src    # With coverage
```

## Troubleshooting

**"No module named 'src'"** — Activate venv: `source .venv/bin/activate && pip install -e .`

**"Rate limit exceeded"** — Auto-retries with backoff. Lower rate: `export MAX_REQUESTS_PER_SECOND=30`

**"No signals found"** — Normal if no Q5 consensus exists. Run `polymarket score && polymarket detect`.

**Database locked** — Check for other processes: `fuser polymarket.db`

## Version History

- **v1.2** (2026-03-22) — Gamma events integration, market resolution, deep classification, entity-level intelligence, lift-based scoring v2. 11 phases (15-25).
- **v1.1** (2026-02-21) — Targeted scanning, pipeline decoupling, deep category scoring, JBecker token catalog. 5 phases (10-14).
- **v1.0** (2026-02-13) — Foundation: API client, taxonomy, evaluation, scoring, signals, alerts, CLI, blockchain, JBecker dataset. 9 phases (1-9).

---

**Built with**: Python, SQLAlchemy, Click, Rich, py-clob-client, DuckDB, Anthropic SDK
