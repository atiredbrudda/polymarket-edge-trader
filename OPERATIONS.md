# Polymarket Pipeline -- Operations Guide

## Two-Loop Architecture

```
+---------------------------------------------------------+
|  CRON -- runs every 4 hours                             |
|                                                         |
|  health-check --tier cron (pre-flight gate)             |
|  discover --closing-within 4 -> backfill [--new-only] ->|
|  retry-incomplete -> ingest-events -> resolve-outcomes ->|
|  sanity-check -> build-positions -> resolve-positions -> |
|  score -> detect -> paper-bridge                        |
|  health-check --tier daily (post-run summary)           |
|                                                         |
|  Purpose: refresh Q5 trader list, rescore,              |
|  catch any signals from closing markets                 |
+-----------+---------------------------------------------+
            | writes Q5 traders + scores to analytics.db
            v
+---------------------------------------------------------+
|  MONITOR -- always-on in terminal                       |
|                                                         |
|  polymarket --niche esports monitor --poll 60 --chain   |
|                                                         |
|  Every 60 min: poll Q5 wallets for new trades           |
|  -> check pipeline lock (skip if cron is running)       |
|  -> auto-discover new markets                           |
|  -> ingest trades (batched in single transaction)       |
|  -> build-positions + detect (via --chain)              |
|  -> new signals surface within ~30s of Q5 entry         |
+---------------------------------------------------------+
```

Both processes share `data/analytics.db`. The lock file `data/.pipeline.lock`
prevents them from stepping on each other. Cron keeps the Q5 list fresh.
Monitor catches entries between cron runs -- that's where live alpha is.

---

## 4-Hour Cron Pipeline

Runs every 4 hours via `scripts/cron_pipeline.sh`. Two backfill modes:

- **Lean (Mon-Sat):** `backfill --new-only` -- only never-backfilled traders (~20 min)
- **Full (Sunday):** `backfill` -- all ~6,000 active traders (~3h)
- **Missed-Sunday fallback:** auto-upgrades to full if >8 days since last full

### Install cron

```bash
crontab -e
# Add:
0 */4 * * * /Users/macbookair/Documents/project/test/rerun7/polymarketv2/scripts/cron_pipeline.sh >> /tmp/polymarket-cron.log 2>&1
```

### Manual run

```bash
cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2
source .venv/bin/activate
./scripts/cron_pipeline.sh
```

### What the cron script does

1. Pre-flight health check (lock, memory, disk) -- aborts if any fail
2. Determines backfill mode (lean vs full based on day + marker file)
3. Runs the 11-stage pipeline
4. Updates full backfill marker if full mode ran
5. Runs daily health summary (alerts via Telegram + macOS)

---

## Always-On Monitor

Run in a dedicated terminal or as a background service. Leave it running permanently.

```bash
cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2
source .venv/bin/activate
polymarket --niche esports monitor --poll 60 --chain
```

- Polls all Q5 traders every 60 minutes
- `--chain` auto-runs build-positions + detect after new trades land
- Checks pipeline lock before each pass -- skips if cron is running
- Warns at startup if lift_scores are stale (>5h old)
- Ctrl+C exits cleanly (graceful shutdown)
- No need to restart after cron -- monitor reads fresh Q5 list each pass

---

## Pipeline Lock Protocol

A lock file at `data/.pipeline.lock` prevents overlap:

| Scenario | Behavior |
|----------|----------|
| Cron starts, no lock | Acquires lock, runs pipeline |
| Cron starts, cron lock held | Pre-flight fails, aborts |
| Cron starts, monitor lock held | Acquires lock (monitor is lightweight) |
| Monitor polls, cron lock held | Skips this pass, tries next hour |
| Monitor polls, no lock | Acquires lock, runs pass |
| Stale lock (PID dead) | Auto-cleaned, new process acquires |

---

## Health Check Tiers

```bash
# Pre-flight gate (run by cron script automatically)
polymarket --niche esports health-check --tier cron

# Daily summary (run by cron script after pipeline)
polymarket --niche esports health-check --tier daily

# Weekly report (run manually or add to Sunday cron)
polymarket --niche esports health-check --tier weekly
```

| Tier | Checks | Behavior |
|------|--------|----------|
| cron | Lock, memory (500MB), disk (10GB), score freshness (5h) | Blocks on lock/memory/disk fail |
| daily | New signals, trader counts, errors | Alert via Telegram + macOS |
| weekly | Q5 diff, scoring drift (20%), data completeness, quiet canary | Alert with snapshot for next week |

---

## First-Time Setup (run once)

```bash
source .venv/bin/activate
polymarket --niche esports ingest-events --full
polymarket --niche esports resolve-outcomes
polymarket --niche esports classify-tokens
```

Then run the cron pipeline to populate scores.

---

## Key Stats (2026-04-11 baseline)

| Metric | Value |
|--------|-------|
| Q5 traders | 530 |
| Total traders scored | 3,797 |
| Markets in DB | 105,021 |
| Positions | 1,024,593 |
| Resolved positions | 1,143,840 |
| Active signals | 72 |
| Paper trades (first run) | 11 buys, $760.49 deployed |

---

## Important Notes

- Always use the **venv** binary: `source .venv/bin/activate` before running any command
- System `polymarket` at `/opt/homebrew/bin/polymarket` lacks `pm_trader` -- don't use it
- `paper-bridge` uses `data/paper_trader/` for its own SQLite (separate from analytics.db)
- Monitor reads `last_monitored_at` per trader -- first run after restart uses `--since 24` lookback
- `--closing-within 4` matches the 4-hour cron interval -- tiles perfectly to cover 24h
