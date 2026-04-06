# Polymarket Smart Money Tracker

Identifies "smart money" traders on Polymarket and surfaces consensus signals when multiple proven traders converge on the same position.

## Full Pipeline

### First-Time Setup (run once)

```bash
# 1. Download eSports events from Gamma API and populate markets table
polymarket --niche esports ingest-events

# 2. Populate markets.outcome (YES/NO) for resolved markets
polymarket --niche esports resolve-outcomes

# 3. Build token catalog (token_id → condition_id mappings)
polymarket --niche esports classify-tokens
```

### Regular Pipeline Run

```bash
# 1. Find traders from active markets + extract team/tournament entities
polymarket --niche esports discover

# 2. Fetch full trade history (Polymarket API first, Graph fallback)
polymarket --niche esports backfill

# 3. Refresh closed events + backfill market end_dates
polymarket --niche esports ingest-events

# 4. Populate markets.outcome for newly resolved markets
polymarket --niche esports resolve-outcomes

# 5. (Optional) Run sanity checks before scoring
polymarket --niche esports sanity-check

# 6. Aggregate raw trades into positions per (trader, market) pair
polymarket --niche esports build-positions

# 7. Compute win/loss + PnL for resolved positions
polymarket --niche esports resolve-positions

# 8. Compute lift scores (z(CLV) + z(ROI) + z(Sharpe)), assign quintiles
polymarket --niche esports score

# 9. Detect Q5 expert consensus on open markets
polymarket --niche esports detect
```

### Viewing Results

```bash
# Browser: start localhost dashboard (auto-refreshes when DB changes)
polymarket --niche esports serve
# Open http://localhost:8080
# Use --port PORT to change the port

# Terminal: same Q5 traders and signals output, but printed to the terminal
# Use this if you need the data without starting a web server
polymarket --niche esports show-traders
```

### Copy-Paste One-Liners

```bash
# First-time setup
polymarket --niche esports ingest-events && polymarket --niche esports resolve-outcomes && polymarket --niche esports classify-tokens

# Regular run
polymarket --niche esports discover && polymarket --niche esports backfill && polymarket --niche esports ingest-events && polymarket --niche esports resolve-outcomes && polymarket --niche esports build-positions && polymarket --niche esports resolve-positions && polymarket --niche esports score && polymarket --niche esports detect

# Re-score without re-discovering
polymarket --niche esports build-positions && polymarket --niche esports resolve-positions && polymarket --niche esports score && polymarket --niche esports detect
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
polymarket --help
```

## Environment Variables

```bash
ANTHROPIC_API_KEY="your_key"       # Required for LLM entity extraction fallback
THE_GRAPH_API_KEY="your_key"       # Required for Graph backfill fallback
```
