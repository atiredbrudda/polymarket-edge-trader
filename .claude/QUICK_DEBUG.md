# Quick Debug Reference for Claude

## Log File Location
```
logs/cli_session.log
```

## What's Logged
- ✅ Every CLI command invocation
- ✅ Command parameters and lifecycle
- ✅ Data counts and summaries
- ✅ Errors, warnings, API interactions
- ✅ Database operations and results

## Quick Commands

### View Recent Logs
```bash
./view_logs.sh last
```

### Monitor Real-Time
```bash
./view_logs.sh tail
```

### Search Errors
```bash
grep ERROR logs/cli_session.log
grep WARNING logs/cli_session.log
```

### Clear Logs
```bash
./view_logs.sh clear
```

## Debugging Workflow

1. **User runs command** → Logs captured automatically
2. **User shares logs** → "Check the logs" or paste `./view_logs.sh last`
3. **Claude reads** → `logs/cli_session.log`
4. **Claude analyzes** → Root cause, suggestions, next steps
5. **User implements fix** → Repeat

## Log Format
```
TIMESTAMP | LEVEL | MESSAGE
```

Example:
```
2026-02-11 12:44:53 | INFO | Command invoked: polymarket sweep
2026-02-11 12:44:53 | INFO | SWEEP command started (window=24h)
2026-02-11 12:44:55 | INFO | Sweep completed: 45 markets, 3 signals
```

## Common Patterns

### No Data Found
```
INFO | Found 0 markets/signals/traders
```
→ Run `polymarket sweep` to populate database

### API Rate Limit
```
WARNING | Rate limit exceeded, retrying in 2.0s
```
→ Automatic retry, normal behavior

### Database Error
```
ERROR | Database error: no such table
```
→ Database not initialized, run initial sweep

### Trader Not Found
```
WARNING | Trader not found: 0xAbc
```
→ Address doesn't exist or not yet discovered

## Quick Checks

```bash
# Last command executed
grep "Command invoked" logs/cli_session.log | tail -1

# Recent errors
grep ERROR logs/cli_session.log | tail -5

# Sweep statistics
grep "Sweep completed" logs/cli_session.log | tail -1

# Session count
grep "CLI SESSION START" logs/cli_session.log | wc -l
```

## When to Share Logs with Claude

- ❌ **Command failed** → Share logs
- ❌ **Unexpected behavior** → Share logs
- ❌ **No data returned** → Share logs
- ⚠️ **Slow performance** → Share logs
- ✅ **Everything works** → Optional

## Privacy

Logs contain market questions, trader addresses, API endpoints. Safe to share with Claude (not stored/trained on), but sanitize before posting publicly.

---

**Just say:** "Check the logs" or "What do the logs show?"
