# Pipeline Todo #2 Summary — Timestamp-based Selective Re-fetch

**Completed:** 2026-04-06  
**Branch:** worker/pipeline-todo-02-timestamps  
**Commit:** 2d18fad

---

## What Was Built

Replaced the `backfill_complete` boolean flag with timestamp-based tracking to enable selective re-fetch of active traders.

### Schema Changes

Added two columns to `traders` table:
- `last_backfilled_at TEXT` — when trader was last backfilled
- `last_trade_seen_at TEXT` — timestamp of most recent trade ingested

Migration logic:
```sql
UPDATE traders
SET last_backfilled_at = datetime('now')
WHERE backfill_complete = 1
  AND last_backfilled_at IS NULL
```

This prevents mass re-fetch on first run after migration — existing backfilled traders are marked as "just refreshed".

### backfill.py Changes

**New selection query** (replaces `WHERE backfill_complete = False`):
```sql
SELECT address FROM traders
WHERE
    (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
    AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
```

Parameters:
- `cutoff` = now - 40 days (scoring window + buffer)
- `threshold` = now - 6 hours (refresh interval)

NULL handling:
- `last_trade_seen_at IS NULL` → new trader, never backfilled → include
- `last_backfilled_at IS NULL` → never backfilled (pre-migration) → include
- `last_trade_seen_at >= cutoff` → recent activity → include
- `last_backfilled_at >= threshold` → recently refreshed → skip

**Timestamp update after backfill:**
```python
db["traders"].update(trader_address, {
    "last_backfilled_at": datetime.now(timezone.utc).isoformat(),
    "last_trade_seen_at": max_trade_timestamp,  # from ingested trades
    "backfill_complete": True,
})
```

---

## Key Decisions

1. **Migration strategy:** Set `last_backfilled_at = datetime('now')` for existing complete traders. Without this, all existing traders would have `NULL` and trigger a full re-fetch on first run.

2. **Row count guard:** Migration UPDATE only runs if `traders` table has rows. Prevents issues on fresh test databases.

3. **Refresh interval:** Hardcoded 6 hours initially. Can be made configurable later.

4. **Coverage window:** 40 days (30-day scoring window + 10-day buffer) — matches existing logic for Graph fallback.

---

## Test Results

```
============================== 87 passed in 1.10s ==============================
```

All existing tests pass. No new tests added — behavior is internal optimization, user-facing behavior unchanged.

---

## Known Issues

(None — implementation matches spec in todo file)

---

## Follow-up Items

- Todo #3: Add incremental mode to `ingest_events` (depends on this being merged)
- Todo #4: Store `clobTokenIds` in DB (depends on #3)
