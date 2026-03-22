# Plan 15-01: GammaEvent Model and Bulk Download Method

## Implemented

### 1. GammaEvent ORM Model (`src/db/models.py`)

Added `GammaEvent` class with the following fields:
- `event_id: Mapped[str]` — primary key (from API `id` field)
- `title: Mapped[str | None]` — max 500 chars
- `slug: Mapped[str | None]` — max 200 chars (URL-safe identifier)
- `outcome_prices: Mapped[str | None]` — JSON string (list like `["0.99", "0.01"]`)
- `clob_token_ids: Mapped[str | None]` — JSON string (aggregated from nested markets[])
- `tags: Mapped[str | None]` — JSON string (array of tag objects with `slug`, `id`, `label`)
- `start_date: Mapped[datetime | None]` — parsed from API `startDate`
- `end_date: Mapped[datetime | None]` — parsed from API `endDate`
- `created_at: Mapped[datetime]` — auto-set
- `updated_at: Mapped[datetime]` — auto-updated

Table name: `gamma_events`
Index: `ix_gamma_event_end_date` on `end_date`

### 2. get_closed_esports_events() Method (`src/api/gamma_client.py`)

Added to `GammaMarketClient` class:
- Signature: `get_closed_esports_events(self, page_size: int = 200) -> list[dict[str, Any]]`
- Uses offset-based pagination
- Request params: `active=false`, `tag_id=64`, `limit=page_size`, `offset`, `order=endDate`, `ascending=true`
- 60 second timeout (vs 30s for other methods) due to ~10MB download
- Respects `rate_limiter` if set
- Logs progress per page and final count

## API Shape Observations

Tested live API:
```
GET https://gamma-api.polymarket.com/events?active=false&tag_id=64&limit=5
Status: 200
Events returned: 5
```

The API returns event objects with:
- `id` — string event ID
- `title`, `slug` — string metadata
- `outcomePrices` — list of outcome price strings
- `markets[]` — nested array, each with `clobTokenIds` field
- `tags[]` — array of tag objects
- `startDate`, `endDate` — ISO datetime strings

## Verification Results

1. Model import: `GammaEvent.__tablename__` → `gamma_events`
2. Method exists: `hasattr(client, 'get_closed_esports_events')` → `True`
3. API connectivity: Status 200, returns events
4. No new test regressions (pre-existing failure in `test_query_uses_parameterized_sql` is unrelated)

## Files Changed

- `src/db/models.py` — Added `GammaEvent` class (+25 lines)
- `src/api/gamma_client.py` — Added `get_closed_esports_events()` method (+53 lines)
