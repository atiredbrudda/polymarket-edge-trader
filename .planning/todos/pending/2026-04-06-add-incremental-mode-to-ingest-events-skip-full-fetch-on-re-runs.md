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

Use the existing `closed` parameter on `GammaAPIClient.fetch_markets()` to branch on first vs subsequent runs:

```python
existing_count = db.execute(
    "SELECT COUNT(*) FROM markets WHERE niche_slug = ?", [niche_slug]
).fetchone()[0]

if existing_count == 0:
    markets = await client.fetch_markets(tag_id)           # full fetch — first run
else:
    markets = await client.fetch_markets(tag_id, closed=False)  # active only — re-run
```

New markets always arrive as `active=True, closed=False`. Already-seen open markets re-upsert harmlessly via `ON CONFLICT DO UPDATE`. Resolution updates (closed markets gaining an outcome) are `resolve-outcomes`' responsibility — `ingest_events` doesn't own that state.

This reduces re-run cost from 96K markets to the small active subset.

**Prerequisite for todo #4** — `classify_tokens` DB-first approach depends on `ingest_events` storing `clobTokenIds`.
