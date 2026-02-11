# Phase 7: CLI Interface - Context

**Gathered:** 2026-02-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Provide command-line tools for market exploration, trader analysis, signal monitoring, and automated hourly polling. This is the user-facing presentation layer — all business logic already exists in Phases 1-6. The CLI wires up existing pipeline functions into Click commands with Rich table output.

</domain>

<decisions>
## Implementation Decisions

### CLI Framework
- **Click** for command-line interface
- Group all commands under a single `polymarket` entry point
- Subcommands: `markets`, `trader`, `signals`, `leaderboard`, `sweep`, `poll`
- Standard Click conventions: `--help` on every command, `--verbose` flag for debug output

### Output Formatting
- **Rich** library for terminal output (tables with borders and structure)
- Colors are fine but not critical — focus is on structured, scannable output
- Rich tables for tabular data (markets, leaderboards, signals)
- Rich panels or grouped output for trader profiles (multi-section display)
- Trader addresses truncated for readability (first 6 + last 4 chars, e.g., `0xAbCd...1234`)

### Command Design
- `markets` — List active eSports markets with taxonomy classification
- `trader <address>` — Full profile: category summaries, positions, expertise scores, score history
- `signals` — Ranked consensus signals with confidence, expert count, direction
- `leaderboard <game>` — Top experts for a game slug (e.g., `esports.cs2`)
- `sweep` — Manual full pipeline run: ingest → score → detect signals → deliver alerts
- `poll` — Automated loop: sweep every N minutes (default 60) with graceful shutdown

### Polling
- Foreground process (not daemon/background)
- Graceful shutdown on Ctrl+C (SIGINT)
- Log each cycle: timestamp, duration, markets found, traders discovered, signals detected, alerts sent
- Configurable interval via `--interval` flag (minutes) or `poll_interval_minutes` setting

### User Experience Decisions

**1. Output & Verbosity**
- **Default Behavior**: Show progress steps during operations (e.g., "Ingesting markets... ✓ 47 markets").
- **Verbose Flag**: `--verbose` adds debug logging on top of standard progress output.
- **Empty States**: Contextual help messages (e.g., "No signals found. Run 'sweep' to refresh.") instead of silence.

**2. Input Handling**
- **Trader Address**: Support partial prefix matching (first 4-6 chars). Error if ambiguous.
- **Game Slugs**: Auto-list available games if `leaderboard` is called without an argument.
- **Errors**: Clean one-line error messages (no stack traces unless --verbose).

**3. Sweep & Polling**
- **Manual Sweep**: Show progress steps as it runs. End with a simple "Done" summary (no big table).
- **Polling Loop**: Print one dense log line per cycle: `[Timestamp] Cycle N: X markets, Y signals (Zs duration)`.

**4. Data Display**
- **Leaderboard**: Focus on Score and Win Rate. Hide PnL to keep it clean.
- **Signals**: Show "First Mover" address — valuable context for users.
- **Markets**: Show only classified eSports markets (hide non-eSports).

</decisions>

<specifics>
## Specific Ideas

- Keep CLI layer thin — commands should be 10-20 lines max, delegating to existing pipeline functions
- Formatters should be pure functions (take data in, return Rich Table out) so they're testable without a terminal
- Sweep command should print a summary of what it found/did, not just "done"
- Leaderboard should show rank, address, score, win rate, trade count — same as LeaderboardEntry dataclass fields

</specifics>

<deferred>
## Deferred Ideas

- `--format json` output for machine consumption — add later if scripting is needed
- Interactive mode / REPL — CLI is batch-only for v1
- Watch mode (auto-refresh signals) — polling covers this use case
- Per-game alert routing (different channels per game) — out of scope per Phase 6 decisions

</deferred>

---

*Phase: 07-cli-interface*
*Context gathered: 2026-02-11*
