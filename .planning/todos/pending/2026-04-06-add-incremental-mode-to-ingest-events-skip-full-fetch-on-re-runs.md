---
created: 2026-04-06T03:22:35.928Z
title: Add incremental mode to ingest_events skip full fetch on re-runs
area: pipeline
files:
  - src/polymarket_analytics/commands/ingest_events.py
  - src/polymarket_analytics/api/gamma.py
---

## Problem

`ingest_events` always fetches the entire Gamma API market catalog from scratch — currently 96K+ markets, ever-growing. The Gamma API uses offset-based pagination with no `since=` timestamp support, so there's no way to ask "what's new." Every run pages through everything, upserts everything, and the cost grows linearly with market count.

## Solution

**1. Branch on first run vs re-run using market count:**

```python
existing_count = db.execute(
    "SELECT COUNT(*) FROM markets WHERE niche_slug = ?", [niche_slug]
).fetchone()[0]

if existing_count == 0:
    markets = await client.fetch_markets(tag_id)            # full — first run
else:
    markets = await client.fetch_markets(tag_id, closed=False)  # active only — re-run
```

New markets always arrive as `active=True, closed=False`. Already-seen open markets re-upsert harmlessly via `ON CONFLICT DO UPDATE`. Resolution updates (closed markets gaining an outcome) are `resolve-outcomes`' responsibility — but `resolve-outcomes` reads from `gamma_events`, so it can only resolve what `ingest_events` has stored. Newly resolved markets won't appear in the `closed=False` fetch and won't get their outcome updated in `gamma_events`. This is an accepted limitation of incremental mode.

**2. Add a `--full` flag as explicit escape hatch:**

```python
@click.option("--full", is_flag=True, default=False,
              help="Force full fetch regardless of existing data (use after failures or for resolution sweep)")
```

When `--full` is passed, always fetch `closed=None` (everything). This handles:
- Partial failure recovery: if a previous run crashed mid-way, `existing_count > 0` but data is incomplete. Without `--full`, incremental mode runs forever and misses the skipped pages.
- Periodic resolution sweep: run `--full` weekly/on-demand to catch markets that resolved since the last full fetch.

Without `--full`, there's no escape from a partial failure — the count check permanently locks the command into incremental mode with a data gap.

**Prerequisite for todo #4** — `classify_tokens` DB-first depends on `ingest_events` storing `clobTokenIds`.
