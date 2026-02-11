---
phase: 07-cli-interface
plan: 01
subsystem: cli
tags: [tdd, pure-functions, rich, click, formatters, commands]
completed: 2026-02-11T02:35:28Z
duration_minutes: 4.78

dependency_graph:
  requires:
    - src/pipeline/queries.py (get_active_markets, get_trader_summary, get_positions_by_timeframe, get_trader_score_history, get_game_leaderboard)
    - src/signals/pipeline.py (get_ranked_signals, refresh_all_signals)
    - src/db/models.py (Trader, TaxonomyNode, Market, MarketClassification)
    - src/db/session.py (get_session)
  provides:
    - src/cli/formatters.py (6 pure formatter functions)
    - src/cli/commands.py (CLI group + 5 subcommands)
    - tests/test_formatters.py (17 formatter tests)
    - tests/test_cli.py (11 CLI command tests)
  affects:
    - pyproject.toml (added click>=8.1, rich>=13.0, pytest-mock, [project.scripts] entry point)

tech_stack:
  added:
    - click>=8.1 (CLI framework)
    - rich>=13.0 (terminal UI library)
    - pytest-mock (testing mocking support)
  patterns:
    - Pure functions for formatters (no side effects)
    - Command-query separation (commands delegate to formatters)
    - Rich renderables (Table, Panel, Group, Text)
    - CliRunner for testing Click commands
    - Partial address matching with normalization

key_files:
  created:
    - src/cli/__init__.py (module initialization)
    - src/cli/formatters.py (6 pure formatters returning Rich renderables)
    - src/cli/commands.py (Click group + 5 subcommands + find_trader_by_prefix helper)
    - tests/test_formatters.py (17 unit tests for formatters)
    - tests/test_cli.py (11 tests for CLI commands)
  modified:
    - pyproject.toml (dependencies + entry point)

decisions:
  - Pure formatters for testability: All format_* functions are pure (data in → Rich renderable out), no database access or side effects
  - Address truncation: first 6 + last 4 chars for long addresses (>10 chars), preserves 0x prefix
  - Markets filter classified only: format_markets_table excludes markets without taxonomy slug
  - Partial address matching: find_trader_by_prefix normalizes input (lowercase, strip, add 0x), handles 0/1/multiple matches with clear errors
  - Game slug validation: leaderboard command validates slug exists, shows available games on error
  - Console per command: Each command creates Console() instance (not shared globally) for isolation
  - Verbose flag wires to loguru: --verbose removes default logger and adds stderr with DEBUG level
  - Sweep command doesn't alert: alerts_sent=0 placeholder, actual alerting lives in delivery pipeline
  - Color hints for confidence: Green >=80, yellow 60-79, white <60 for visual scanning
  - Win rate as percentage: Displayed as percentage (85.5%) rather than decimal (0.855) for UX

metrics:
  tests_added: 28
  total_tests: 429 (401 existing + 28 new)
  test_pass_rate: 100%
  files_created: 5
  lines_of_code:
    - src/cli/formatters.py: 274 lines
    - src/cli/commands.py: 372 lines
    - tests/test_formatters.py: 248 lines
    - tests/test_cli.py: 145 lines
  commits: 5
---

# Phase 7 Plan 1: CLI Formatters and Commands Summary

**One-liner:** Pure Rich formatters + Click commands with partial address matching, game validation, and time-windowed signal queries

## What Was Built

Implemented CLI presentation layer with two modules:

**1. src/cli/formatters.py (Pure Functions)**
- `truncate_address`: Shorten wallet addresses to first 6 + last 4 chars
- `format_markets_table`: Display markets with question, game slug, status
- `format_trader_profile`: Multi-section Group with header, category summaries, positions, expertise scores
- `format_signals_table`: Display signals with confidence percentages and color hints (green ≥80, yellow 60-79)
- `format_leaderboard_table`: Display rank, trader, score, win rate
- `format_sweep_summary`: Panel with processing stats (time, markets, signals, alerts)

All formatters are pure functions: data objects in → Rich renderables out. No database access or side effects.

**2. src/cli/commands.py (Click Commands)**
- `cli` group: Top-level entry point for `polymarket` command
- `markets`: List active markets with optional category filter, joins MarketClassification for taxonomy slugs
- `trader`: Display profile with partial address matching via `find_trader_by_prefix`
- `signals`: Show ranked signals with time window (1/6/24h) and confidence filters
- `leaderboard`: Display game rankings with slug validation (shows available games on error)
- `sweep`: Run signal detection sweep with processing stats

**3. Helper Functions**
- `find_trader_by_prefix`: Normalizes input (lowercase, strip, add 0x prefix), queries with LIKE pattern, handles 0/1/multiple matches with clear error messages

## Deviations from Plan

None - plan executed exactly as written.

## Tests Added

**Formatter Tests (17 tests):**
- `truncate_address`: short/long/exactly-10-char addresses
- `format_markets_table`: empty/single/multiple markets, filters unclassified
- `format_trader_profile`: renders all sections, handles empty data
- `format_signals_table`: empty/single/multiple signals, confidence display, first mover truncation
- `format_leaderboard_table`: renders rank/scores, empty leaderboard
- `format_sweep_summary`: all stats, minimal stats

**CLI Command Tests (11 tests):**
- CLI group: --help shows all 5 subcommands
- Each subcommand: --help shows correct arguments/options
- `find_trader_by_prefix`: 0 matches, 1 match, multiple matches, normalization, 0x prefix handling

All tests use pytest fixtures and mocking (pytest-mock) for database isolation.

## Verification Results

```bash
$ .venv/bin/python -m pytest tests/test_formatters.py tests/test_cli.py -v
# 28 tests passed

$ .venv/bin/python -m pytest --tb=short -q
# 429 tests passed (401 existing + 28 new)

$ .venv/bin/python -m src.cli.commands --help
# Shows command group with all 5 subcommands
```

## Technical Decisions

**Pure Functions for Formatters:**
All `format_*` functions are pure: no database access, no side effects, deterministic output. This enables unit testing without mocking and makes formatters composable.

**Address Truncation Strategy:**
Preserves 0x prefix and shows first 6 + last 4 chars for addresses > 10 chars. Balances readability with enough uniqueness for visual scanning. Applied consistently across all formatters.

**Partial Address Matching:**
`find_trader_by_prefix` normalizes input (lowercase, strip whitespace, add 0x prefix if missing) and uses LIKE query. Clear error messages for 0 matches ("No trader found") and multiple matches ("Ambiguous address, provide more characters").

**Game Slug Validation:**
`leaderboard` command validates slug exists in taxonomy before querying. On error, displays available games list for user convenience. Prevents SQL errors and improves UX.

**Console Per Command:**
Each command creates its own Console() instance (not shared globally). Enables isolation and prevents state leakage between commands in test environments.

**Verbose Flag Implementation:**
`--verbose` flag calls `logger.remove()` then `logger.add(sys.stderr, level="DEBUG")` to wire loguru to stderr with debug level. All pipeline functions using loguru will output debug logs after setup.

**Confidence Color Hints:**
Green for ≥80, yellow for 60-79, white for <60. Visual scanning aid for high-confidence signals. Uses Rich Text.from_markup() for inline color formatting.

**Sweep Command Design:**
`sweep` command runs `refresh_all_signals()` but doesn't send alerts (alerts_sent=0 placeholder). Actual alerting lives in `src/alerts/delivery.py` pipeline. Keeps CLI command thin and focused on signal detection only.

## Integration Points

**Queries Used:**
- `get_active_markets`: Fetch markets for display
- `get_trader_summary`: Fetch category summaries for trader profile
- `get_positions_by_timeframe`: Fetch current positions
- `get_trader_score_history`: Fetch expertise scores
- `get_game_leaderboard`: Fetch game rankings
- `get_ranked_signals`: Fetch signals with time window filtering
- `refresh_all_signals`: Run full signal detection sweep

**Models Accessed:**
- Trader: Address lookup and validation
- TaxonomyNode: Game slug validation
- Market: Join for question display
- MarketClassification: Join for taxonomy slug retrieval

## Self-Check: PASSED

**Created files exist:**
```bash
$ [ -f "src/cli/__init__.py" ] && echo "FOUND: src/cli/__init__.py"
FOUND: src/cli/__init__.py
$ [ -f "src/cli/formatters.py" ] && echo "FOUND: src/cli/formatters.py"
FOUND: src/cli/formatters.py
$ [ -f "src/cli/commands.py" ] && echo "FOUND: src/cli/commands.py"
FOUND: src/cli/commands.py
$ [ -f "tests/test_formatters.py" ] && echo "FOUND: tests/test_formatters.py"
FOUND: tests/test_formatters.py
$ [ -f "tests/test_cli.py" ] && echo "FOUND: tests/test_cli.py"
FOUND: tests/test_cli.py
```

**Commits exist:**
```bash
$ git log --oneline --all | grep -q "aed97da" && echo "FOUND: aed97da"
FOUND: aed97da
$ git log --oneline --all | grep -q "f51ce5c" && echo "FOUND: f51ce5c"
FOUND: f51ce5c
$ git log --oneline --all | grep -q "eb40efd" && echo "FOUND: eb40efd"
FOUND: eb40efd
$ git log --oneline --all | grep -q "feb9416" && echo "FOUND: feb9416"
FOUND: feb9416
$ git log --oneline --all | grep -q "5f17618" && echo "FOUND: 5f17618"
FOUND: 5f17618
```

All files and commits verified.

## Next Steps

Ready for Phase 7 Plan 2: Scheduled polling with APScheduler for automated signal detection sweeps.
