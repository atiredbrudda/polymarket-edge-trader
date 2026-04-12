# Polymarket Cron Pipeline — Operations Guide

## Shortcuts

| Alias | What it does |
|-------|-------------|
| `pm-log` | Live tail of cron log |
| `pm-log-last` | Last 100 lines of cron log |
| `pm-cron-stop` | Remove the crontab (stops all scheduled runs) |
| `pm-cron-status` | Show current crontab entry |

Run `source ~/.zshrc` to load these in your current shell.

## Schedule

Runs every 4 hours: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00.

- **Mon-Sat:** Lean backfill (`--new-only`) — only never-backfilled traders (~20 min)
- **Sunday:** Full backfill — all ~7,000 traders (~3h)
- **Missed-Sunday fallback:** If >8 days since last full, auto-upgrades to full

## What runs each cycle

1. Pre-flight health check (lock, memory, disk, staleness)
2. discover (--closing-within 4)
3. backfill (--new-only or full)
4. retry-incomplete
5. ingest-events
6. resolve-outcomes
7. sanity-check
8. build-positions
9. resolve-positions
10. score
11. detect
12. paper-bridge
13. Daily health summary + Telegram alert

## Logs

- **Location:** `/tmp/polymarket-cron.log`
- **Note:** `/tmp` is cleared on reboot. If you need persistent logs, change the path in both the crontab and the `pm-log` alias.

## What to look out for

### In the log

- `PRE-FLIGHT FAILED` — pipeline skipped this cycle. Check memory/disk/lock.
- `FAILED:` — a stage failed. Pipeline aborts on first failure (`set -e`).
- `too many SQL variables` — should be fixed now, but if it recurs, a query is exceeding SQLite's 999-variable limit.
- `database is locked` — another process (monitor?) is holding the DB. The lock protocol should prevent this, but if it happens, check `ps aux | grep polymarket`.
- `Traceback` — unhandled Python exception. Read the traceback.

### Alerts (Telegram + macOS)

- Daily summary arrives after each successful run
- If you stop getting alerts, check `pm-log-last` for errors

### Database growth

The DB (`data/analytics.db`) grows with each backfill. Currently ~500MB. Monitor with:
```
ls -lh data/analytics.db
```

## How to stop

### Temporarily (skip next run)
```bash
launchctl unload ~/Library/LaunchAgents/com.polymarket.cron-pipeline.plist
```

### Restart after stopping
```bash
launchctl load ~/Library/LaunchAgents/com.polymarket.cron-pipeline.plist
```

### Kill a running pipeline mid-execution
```bash
ps aux | grep cron_pipeline | grep -v grep
kill <PID>
# Also kill the child Python process if still running:
ps aux | grep polymarket | grep -v grep
kill <PID>
```

## Manual run

To trigger a run outside the schedule:
```bash
cd /Users/macbookair/polymarketv2
bash scripts/cron_pipeline.sh
```

Or force a full backfill on a non-Sunday:
```bash
rm data/.last_full_backfill
bash scripts/cron_pipeline.sh
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No logs appearing | `pm-cron-status` to check crontab exists. Check if Mac went to sleep during scheduled time. |
| "database is locked" | Kill any stale polymarket processes: `ps aux \| grep polymarket` |
| Pipeline takes too long | Check if it auto-upgraded to full backfill (missed-Sunday). Normal full run is ~3h. |
| Telegram alerts stopped | Check `.env` has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Test with: `.venv/bin/python -c "from polymarket_analytics.health.notify import send_alert; send_alert('test', 'test')"` |
| Cron not running after reboot | macOS may require Terminal to have Full Disk Access in System Settings > Privacy. |
