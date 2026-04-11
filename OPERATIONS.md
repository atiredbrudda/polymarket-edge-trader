# Polymarket Pipeline — Operations Guide

## Two-Loop Architecture

```
┌─────────────────────────────────────────────────────┐
│  CRON — runs daily (e.g. 6am)                        │
│                                                      │
│  discover → backfill → retry-incomplete →            │
│  ingest-events → resolve-outcomes → sanity-check →  │
│  build-positions → resolve-positions → score →      │
│  detect → paper-bridge                              │
│                                                      │
│  Purpose: refresh Q5 trader list, rescore,          │
│  catch any signals from closing markets             │
└───────────────────┬─────────────────────────────────┘
                    │ writes Q5 traders + scores to analytics.db
                    ▼
┌─────────────────────────────────────────────────────┐
│  MONITOR — always-on in terminal                    │
│                                                      │
│  polymarket --niche esports monitor --poll 60 --chain│
│                                                      │
│  Every 60 min: poll 530 Q5 wallets for new trades   │
│  → auto-discover new markets                        │
│  → ingest trades                                    │
│  → build-positions + detect (via --chain)           │
│  → new signals surface within ~30s of Q5 entry     │
└─────────────────────────────────────────────────────┘
```

Both processes share `data/analytics.db`. Cron keeps the Q5 list fresh.
Monitor catches entries between cron runs — that's where live alpha is.

---

## Daily Cron — Full Pipeline

Run once a day (recommended: 6am, before esports matches start).

```bash
#!/bin/bash
cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2
source .venv/bin/activate

polymarket --niche esports discover --closing-within 3 && \
polymarket --niche esports backfill && \
polymarket --niche esports retry-incomplete && \
polymarket --niche esports ingest-events && \
polymarket --niche esports resolve-outcomes && \
polymarket --niche esports sanity-check && \
polymarket --niche esports build-positions && \
polymarket --niche esports resolve-positions && \
polymarket --niche esports score && \
polymarket --niche esports detect && \
polymarket --niche esports paper-bridge
```

Backfill is the slow step (~10-15 min for 6,466 traders). Rest is fast.

---

## Always-On Monitor

Run in a dedicated terminal or as a background service. Leave it running permanently.

```bash
cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2
source .venv/bin/activate
polymarket --niche esports monitor --poll 60 --chain
```

- Polls all 530 Q5 traders every 60 minutes
- `--chain` auto-runs build-positions + detect after new trades land
- Ctrl+C exits cleanly (graceful shutdown)
- Restart after daily cron completes to pick up new Q5 list

---

## First-Time Setup (run once)

```bash
source .venv/bin/activate
polymarket --niche esports ingest-events --full
polymarket --niche esports resolve-outcomes
polymarket --niche esports classify-tokens
```

Then run the full daily pipeline above to populate scores.

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
- System `polymarket` at `/opt/homebrew/bin/polymarket` lacks `pm_trader` — don't use it
- `paper-bridge` uses `data/paper_trader/` for its own SQLite (separate from analytics.db)
- Monitor reads `last_monitored_at` per trader — first run after restart uses `--since 24` lookback
