# Phase 7: CLI Interface - Research

**Gathered:** 2026-02-11
**Status:** Completed
**Context:** 07-CONTEXT.md

## Research Objective

Determine the optimal architecture for the CLI interface (Phase 7), map existing pipeline functions to user commands, and select libraries for command parsing and terminal output formatting.

## Existing Capabilities (Codebase Audit)

The project already contains all business logic required for the CLI. The CLI is strictly a presentation layer.

### 1. Market Data
- **Function:** `src.pipeline.queries.get_active_markets`
- **Capability:** Fetches active markets from DB.
- **Filters:** Accepts optional `category` filter (e.g., "eSports").
- **Mapping:** `polymarket markets` command.

### 2. Trader Profiles
- **Functions:**
  - `src.pipeline.queries.get_trader_summary` (Category stats)
  - `src.pipeline.queries.get_positions_by_timeframe` (Current/recent positions)
  - `src.pipeline.queries.get_trader_score_history` (Expertise scores)
- **Capability:** Full 360-view of a trader's activity and performance.
- **Mapping:** `polymarket trader <address>` command.

### 3. Consensus Signals
- **Function:** `src.signals.pipeline.get_ranked_signals`
- **Capability:** Returns `SignalResult` objects ranked by confidence score.
- **Filters:** Accepts `window_hours` and `min_confidence` filters.
- **Mapping:** `polymarket signals` command.

### 4. Leaderboards
- **Function:** `src.pipeline.queries.get_game_leaderboard`
- **Capability:** Returns `LeaderboardEntry` objects sorted by rank.
- **Filters:** Accepts `game_slug`, `top_n`, and `min_score`.
- **Mapping:** `polymarket leaderboard <game>` command.

### 5. Orchestration
- **Functions:**
  - `src.pipeline.ingest.IngestionPipeline.run_full_sweep`
  - `src.pipeline.scoring_pipeline.compute_all_game_scores`
  - `src.signals.pipeline.refresh_all_signals`
  - `src.alerts.delivery.deliver_signal_alerts`
- **Capability:** Full end-to-end pipeline execution.
- **Mapping:** `polymarket sweep` and `polymarket poll` commands.

## Architecture Decisions

### CLI Framework: Click
Selected **Click** over Typer/Argparse for stability and standard convention in Python tooling.
- **Structure:** Single `click.group()` entry point with nested `click.command()` functions.
- **Context:** `ctx.obj` used to pass configuration (Settings) down to commands.

### Output Formatting: Rich
Selected **Rich** for terminal output.
- **Tables:** `rich.table.Table` for structured data (markets, signals, leaderboard).
- **Panels:** `rich.panel.Panel` for summaries and sections (trader profile).
- **Live:** `rich.live.Live` or `rich.status.Status` for polling/sweep progress.
- **Pure Functions:** Formatters decoupled from API/DB logic to enable testing.

### Polling Mechanism
- **Process:** Foreground blocking process (simplest for v1).
- **Signal Handling:** `signal.signal(signal.SIGINT, handler)` for graceful shutdown.
- **Logging:** Dense one-line logs per cycle using `loguru`.

## Implementation Strategy

1. **Layer 1: Pure Formatters (Plan 07-01)**
   - Transform data objects (dicts/DTOs) into Rich Renderables.
   - Fully testable without DB or API.

2. **Layer 2: CLI Commands (Plan 07-01)**
   - Click definitions handling arguments/options.
   - Delegate to Pipeline functions for data.
   - Delegate to Formatters for output.

3. **Layer 3: Scheduler (Plan 07-02)**
   - `run_sweep` function chaining the 4 pipeline stages.
   - `run_polling_loop` handling interval and shutdown.

4. **Layer 4: Wiring (Plan 07-03)**
   - Entry point configuration (`pyproject.toml`).
   - Dependency injection (Session, Client, Settings).

## Dependencies

- `click >= 8.1`
- `rich >= 13.0`
- Existing project modules (`src.*`)

## Risk Assessment

- **Database Locks:** SQLite WAL mode is enabled (from Phase 1), so reading (CLI commands) while writing (Polling sweep) should be safe.
- **API Rate Limits:** `PolymarketClient` has internal rate limiting (token bucket). Running interactive CLI commands during a sweep might hit limits, but client handles retries.
- **Terminal Width:** Rich handles auto-resizing, but complex tables (Signals) might wrap on narrow screens. Formatters should be prioritized for standard 80-col width where possible.
