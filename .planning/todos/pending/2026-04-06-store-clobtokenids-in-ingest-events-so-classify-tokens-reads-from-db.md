---
created: 2026-04-06T03:22:35.928Z
title: Store clobTokenIds in ingest_events so classify_tokens reads from DB
area: pipeline
files:
  - src/polymarket_analytics/commands/ingest_events.py
  - src/polymarket_analytics/commands/classify_tokens.py
  - src/polymarket_analytics/db/schema.py
---

## Problem

`classify_tokens` makes a completely redundant full Gamma API call (96K+ markets) on every run. It does this because the one field it needs — `clobTokenIds` — is not stored by `ingest_events`. Both commands independently page through the entire Gamma catalog, doubling the API cost and run time.

## Solution

Two-part fix:

**Part 1 — store `clobTokenIds` during `ingest_events`:**
Add a `clob_token_ids` TEXT column (JSON) to `gamma_events` (or `markets`) and populate it during `ingest_events` from `market.get("clobTokenIds", [])`. Schema migration needed in `schema.py`.

**Part 2 — `classify_tokens` reads from DB:**
```python
uncataloged = db.execute("""
    SELECT g.condition_id, g.clob_token_ids, m.question, m.category
    FROM gamma_events g
    JOIN markets m ON m.condition_id = g.condition_id
    WHERE g.niche_slug = ?
      AND g.condition_id NOT IN (SELECT DISTINCT condition_id FROM token_catalog)
""", [niche_slug]).fetchall()
```
If `uncataloged` is empty → done, zero API calls. If not → process only the missing entries from DB data. Only fall back to Gamma API if `clob_token_ids` is missing for a specific condition_id.

**Depends on todo #3** — `ingest_events` must be storing `clobTokenIds` before this can work.
