# Claude Debug Guide

This guide explains how Claude (AI assistant) can follow along and debug with you using the CLI logging system.

## Overview

The Polymarket CLI now automatically logs all command executions to `logs/cli_session.log`. This allows Claude to:

1. **See what you ran** - Full command with arguments
2. **Understand the flow** - Command lifecycle and data processing
3. **Identify issues** - Errors, warnings, and unexpected behavior
4. **Provide context-aware help** - Debug based on actual execution logs

## How It Works

### Automatic Logging

Every CLI command logs:
- Session start timestamp
- Full command invocation
- Command lifecycle events (started, completed)
- Data summaries (counts, results)
- API interactions
- Database operations
- Errors and warnings

### Log Format

```
TIMESTAMP | LEVEL | MESSAGE
```

Example:
```
2026-02-11 12:44:53 | INFO | Command invoked: polymarket sweep
2026-02-11 12:44:53 | INFO | SWEEP command started (window=24h, verbose=False)
2026-02-11 12:44:55 | INFO | Sweep completed: 45 markets, 3 signals, 1 alerts in 2.34s
```

## Workflow: Debugging Together

### Step 1: You Run a Command

```bash
source .venv/bin/activate
polymarket sweep
```

### Step 2: Share Logs with Claude

**Option A: Paste recent logs**
```bash
./view_logs.sh last
# Copy and paste output to Claude
```

**Option B: Ask Claude to read the log file**
Just say: "Check the CLI logs" or "What do the logs show?"

Claude will read `logs/cli_session.log` directly and analyze:
- What command you ran
- What happened during execution
- Any errors or warnings
- Data summaries and results

### Step 3: Claude Analyzes

Claude can:
- Identify the root cause of errors
- Suggest fixes based on actual execution flow
- Compare expected vs actual behavior
- Recommend next debugging steps

### Step 4: Iterate

Run suggested fixes, Claude reviews new logs, repeat until resolved.

## Examples

### Example 1: No Signals Found

**You run:**
```bash
polymarket signals
```

**You say to Claude:**
"No signals showing up. Check the logs."

**Claude reads logs/cli_session.log:**
```
2026-02-11 12:45:50 | INFO | SIGNALS command started (window=24h, min_confidence=None, verbose=False)
2026-02-11 12:45:50 | INFO | Found 0 signals
2026-02-11 12:45:50 | INFO | SIGNALS command completed
```

**Claude responds:**
"The logs show 0 signals were found in the 24-hour window. This could mean:
1. No expert consensus exists yet
2. Database is empty (need to run `polymarket sweep` first)
3. Window is too narrow

Let me check if you have markets in the database..."

### Example 2: API Rate Limit

**You run:**
```bash
polymarket sweep
```

**Logs show:**
```
2026-02-11 13:00:15 | WARNING | Rate limit exceeded, retrying in 2.0s (attempt 1/5)
2026-02-11 13:00:17 | WARNING | Rate limit exceeded, retrying in 4.0s (attempt 2/5)
2026-02-11 13:00:21 | INFO | Sweep completed: 45 markets, 3 signals, 1 alerts in 12.34s
```

**Claude responds:**
"The logs show rate limiting occurred during the sweep (attempts 1-2), but it succeeded with automatic retry. The processing time (12s) is normal given the retries. If this happens frequently, consider lowering MAX_REQUESTS_PER_SECOND from 50 to 30."

### Example 3: Database Error

**You run:**
```bash
polymarket trader 0xAbc123
```

**Logs show:**
```
2026-02-11 14:30:00 | INFO | TRADER command started (address=0xAbc123, verbose=False)
2026-02-11 14:30:00 | ERROR | Database error: no such table: trader
2026-02-11 14:30:00 | ERROR | TRADER command failed
```

**Claude responds:**
"The database is missing the 'trader' table. This means the database hasn't been initialized. Run:
```bash
polymarket sweep
```
This will create all tables and populate initial data."

## Advanced: Real-Time Debugging

### Terminal 1: Run Commands
```bash
source .venv/bin/activate
polymarket poll --interval 60
```

### Terminal 2: Monitor Logs
```bash
./view_logs.sh tail
```

### Claude: Analyzes Live

You can copy/paste log snippets to Claude as the polling runs, and Claude can spot issues in real-time.

## What Claude Can See

✅ **Claude CAN see:**
- Full command invocation
- Command parameters
- Data counts and summaries
- Error messages and stack traces
- API interactions
- Database query patterns
- Processing times

❌ **Claude CANNOT see (without logs):**
- Your terminal output (unless you paste it)
- Commands you ran outside this project
- Environment variables (unless you share them)
- File contents (unless Claude reads them)

## Tips for Effective Debugging

1. **Always share recent logs** - Run `./view_logs.sh last` and paste output
2. **Describe what you expected** - "I expected 5 signals but got 0"
3. **Include error messages** - Even if they seem cryptic
4. **Share environment context** - "Running on macOS", "Using Python 3.13"
5. **Let Claude read the file** - Just say "check the logs" instead of pasting

## Privacy Note

Logs contain:
- Market questions and IDs
- Trader wallet addresses
- API endpoints
- Command history

**Claude (Anthropic) does NOT store or train on your conversations by default.** However, avoid sharing logs publicly without sanitizing.

## Disabling Logging

If you don't want logging:

```bash
export CLI_LOG_FILE="/dev/null"
```

Or delete the log file:
```bash
rm logs/cli_session.log
```

## Troubleshooting the Logger

### Log file not created

Run any command first:
```bash
polymarket markets
```

Then check:
```bash
ls -la logs/
```

### Log file empty

Check if commands are failing before logging starts:
```bash
polymarket --version
```

### Can't find recent execution

Logs are appended, not overwritten. Search by timestamp:
```bash
grep "2026-02-11 15:" logs/cli_session.log
```

## Summary

The logging system creates a **shared context** between you and Claude:

1. You run commands → Logs capture execution
2. You share logs → Claude sees what happened
3. Claude analyzes → Identifies issues
4. You implement fixes → Logs confirm success

This eliminates the "I can't see your screen" problem and enables effective remote debugging.

---

**Quick Reference:**

```bash
# View last 50 lines
./view_logs.sh last

# Follow in real-time
./view_logs.sh tail

# Search for errors
grep ERROR logs/cli_session.log

# Clear logs
./view_logs.sh clear
```

Then just say to Claude: **"Check the logs"** 🤖
