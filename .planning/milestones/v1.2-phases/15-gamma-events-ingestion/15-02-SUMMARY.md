# Plan 15-02: Ingest Events CLI Command

## Implemented

### 1. src/gamma/persist.py

Created persistence layer with `upsert_gamma_events()` function:
- Accepts raw event dicts from `GammaMarketClient.get_closed_esports_events()`
- Extracts fields: event_id, title, slug, outcome_prices, clob_token_ids, tags, start_date, end_date
- Aggregates clob_token_ids from nested markets[] array
- Uses INSERT OR REPLACE for idempotent upserts
- Skips events with empty event_id with warning log

Helper functions:
- `_extract_token_ids(event)` — extracts all clobTokenIds from nested markets
- `_parse_datetime(value)` — parses ISO datetime strings with Z suffix

### 2. ingest-events CLI Command

Added to `src/cli/commands.py`:
- Command: `polymarket ingest-events`
- Downloads all closed eSports events (tag_id=64)
- Persists to gamma_events table
- Idempotent — re-run updates existing rows
- Progress logging per page

## Final Event Count

- Downloaded: 8,545 events
- Persisted: 8,520 events (25 skipped due to empty event_id)
- Re-run produces same count (idempotency confirmed)

## Sample Event Data

```
event_id: 902700
clob_token_ids: ["21742633143463906290569050155826241533067272736397061054153503275463413049434", ...]
outcome_prices: ["0.99", "0.01"]
tags: [{"id": 64, "slug": "esports", "label": "eSports"}, ...]
```

## Edge Cases Found

- Some events have empty `id` field — skipped with warning
- Difference between downloaded (8545) and persisted (8520) due to empty IDs
- clobTokenIds may be JSON string or list — handled both cases

## Verification

1. Command help: `polymarket ingest-events --help` — correct output
2. First run: Downloaded and persisted 8,520 events
3. Data check: All required fields (event_id, outcome_prices, clob_token_ids, tags) populated
4. Idempotency: Second run produces same count (8,520)
5. No new test regressions

## Files Changed

- `src/gamma/__init__.py` (NEW) — package marker
- `src/gamma/persist.py` (NEW) — upsert_gamma_events function (+100 lines)
- `src/cli/commands.py` — ingest-events command (+44 lines)
