# CLI Logging System

All CLI commands automatically log their execution to `logs/cli_session.log` for debugging and monitoring purposes.

## Log File Location

```
logs/cli_session.log
```

The log file:
- Auto-creates on first CLI command execution
- Rotates at 10 MB (keeps last 3 files)
- Persists across sessions (appends, doesn't overwrite)
- Thread-safe for concurrent operations

## What Gets Logged

Each CLI command logs:
- **Session start marker** with timestamp
- **Command invocation** (full command with arguments)
- **Command lifecycle** (started, completed)
- **Data summaries** (counts, statistics)
- **Errors and warnings** (with context)
- **API interactions** (rate limiting, retries)
- **Database operations** (queries, results)

### Log Levels

- `DEBUG`: Detailed data (market lists, trader details, etc.)
- `INFO`: Command flow and summaries
- `WARNING`: Non-fatal issues (e.g., Telegram not configured)
- `ERROR`: Failures and exceptions

## Viewing Logs

### Quick View (Last 50 Lines)

```bash
./view_logs.sh last
```

### Real-Time Monitoring

```bash
./view_logs.sh tail
# or
./view_logs.sh
```

Press `Ctrl+C` to stop.

### View Entire Log

```bash
./view_logs.sh view
```

### Clear Logs

```bash
./view_logs.sh clear
```

### Manual Access

```bash
# Last 50 lines
tail -n 50 logs/cli_session.log

# Follow in real-time
tail -f logs/cli_session.log

# Search for errors
grep ERROR logs/cli_session.log

# View specific command
grep "SWEEP command" logs/cli_session.log
```

## Example Log Output

```
2026-02-11 12:44:53 | INFO     | ================================================================================
2026-02-11 12:44:53 | INFO     | CLI SESSION START
2026-02-11 12:44:53 | INFO     | ================================================================================
2026-02-11 12:44:53 | INFO     | Command invoked: polymarket markets
2026-02-11 12:44:53 | INFO     | MARKETS command started (category=None, verbose=False)
2026-02-11 12:44:53 | INFO     | Initialized PolymarketClient with rate limit 50/s
2026-02-11 12:44:53 | INFO     | Found 1 active markets
2026-02-11 12:44:53 | DEBUG    |   - esports.cs2: Will Team Vitality win IEM Katowice 2024?
2026-02-11 12:44:53 | INFO     | MARKETS command completed
```

## Debugging Workflow

1. **Run command** (e.g., `polymarket sweep`)
2. **Open log in separate terminal**:
   ```bash
   ./view_logs.sh tail
   ```
3. **Observe execution** in real-time
4. **Search for issues**:
   ```bash
   grep -i error logs/cli_session.log
   grep -i warning logs/cli_session.log
   ```

## Integration with `--verbose` Flag

The `--verbose` flag enhances **terminal output** (stderr), while the log file captures everything at DEBUG level regardless of the flag.

```bash
# Terminal shows minimal output, logs show everything
polymarket sweep

# Terminal shows DEBUG output, logs show everything (same as above in log file)
polymarket sweep --verbose
```

## Log Rotation

- **Max size**: 10 MB per file
- **Retention**: 3 files (current + 2 rotated)
- **Naming**: `cli_session.log`, `cli_session.log.1`, `cli_session.log.2`
- **Behavior**: Oldest file deleted when limit reached

## Troubleshooting

### Log file not created

Ensure you're running commands from the project root:
```bash
cd /path/to/GSD_Polymarket
source .venv/bin/activate
polymarket markets
```

### Log file too large

Clear it manually:
```bash
./view_logs.sh clear
# or
> logs/cli_session.log
```

### Can't find recent execution

Check timestamp in logs:
```bash
tail -20 logs/cli_session.log
```

## Privacy Note

Logs may contain:
- Market questions and IDs
- Trader wallet addresses
- API endpoints and parameters
- Database query patterns

**Do not share logs publicly** without sanitizing sensitive data.

## Disabling Logging

To disable file logging (terminal output only), set:

```bash
export CLI_LOG_FILE="/dev/null"
```

Or modify `src/config/settings.py`:

```python
cli_log_file: str = "/dev/null"
```
