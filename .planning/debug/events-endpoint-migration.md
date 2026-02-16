---
status: resolved
trigger: "Gamma API /markets endpoint ignores all filters - switched to /events endpoint"
created: 2026-02-15T00:00:00Z
updated: 2026-02-15T13:00:00Z
---

## Current Focus
hypothesis: "Investigation complete - /events endpoint migration applied"
test: "discover --niche esports --closing-within 12h found 258 markets and 1016 traders in 131s"
expecting: "Only niche-matching markets within timeframe are returned"
next_action: "Resolved"

## Symptoms
expected: "Gamma API /markets endpoint should filter by tag, closed status, and end date"
actual: "/markets returns identical results regardless of tag parameter (always Trump/politics markets)"
errors: "No errors - just wrong data returned"
reproduction: |
  curl "https://gamma-api.polymarket.com/markets?closed=false&tag=esports&limit=5"
  curl "https://gamma-api.polymarket.com/markets?closed=false&tag=crypto&limit=5"
  # Both return identical Trump deportation markets
started: "Discovered during sweep debugging after client-side filtering was added"

## Eliminated

- hypothesis: "Filters not being passed correctly to API"
  evidence: "Verified via direct curl - same results with any tag value"
  timestamp: "2026-02-15T00:00:00Z"

- hypothesis: "Need different parameter names for /markets"
  evidence: "Tried tag, tag_id, category - none work on /markets"
  timestamp: "2026-02-15T00:00:00Z"

## Evidence

- timestamp: "2026-02-15T00:00:00Z"
  checked: "/markets endpoint with various tag values"
  found: "Returns identical results for tag=esports, tag=crypto, tag=politics, tag=science"
  implication: "/markets endpoint server-side filtering is completely broken"

- timestamp: "2026-02-15T00:00:00Z"
  checked: "/events endpoint with tag_id parameter"
  found: "/events?tag_id=64 correctly returns only esports events with real game times"
  implication: "/events endpoint works correctly and is the right replacement"

- timestamp: "2026-02-15T00:00:00Z"
  checked: "/events endpoint date filtering"
  found: "end_date_max and end_date_min parameters work correctly on /events"
  implication: "Can use /events for both niche and time-based filtering"

- timestamp: "2026-02-15T00:00:00Z"
  checked: "/events response structure"
  found: "Events contain nested 'markets' array - need to extract and flatten"
  implication: "Need _convert_events_to_markets() to transform response"

## Resolution

root_cause: "Gamma API /markets endpoint ignores all query filters (tag, closed, end_date). This is a server-side bug. The /events endpoint works correctly with tag_id and date filters."

fix: |
  1. Added get_events() to GammaMarketClient with tag_id, end_date_max, end_date_min params
  2. Added NICHE_TAG_IDS mapping (esports=64, sports=1, politics=100, crypto=100630)
  3. Added _convert_events_to_markets() to extract markets from event responses
  4. Changed ingest_targeted_markets() to call get_events() instead of get_markets()
  5. Events provide real game startDate/endDate (not midnight UTC defaults from /markets)

verification: "discover --niche esports --closing-within 12h: 258 markets, 1016 traders, 131s"

files_changed:
  - src/api/gamma_client.py (added get_events method)
  - src/pipeline/ingest.py (NICHE_TAG_IDS, _convert_events_to_markets, updated ingest_targeted_markets)

---

## Related Fix: Discover Command SQLAlchemy Detached Instance

### Symptom
Running `discover --niche esports` crashed with SQLAlchemy DetachedInstanceError when iterating over markets to discover traders.

### Root Cause
The trader discovery loop was outside the `with get_session()` block. After the session closed, ORM objects were detached and accessing `market.condition_id` raised DetachedInstanceError.

### Fix
Moved the `for market in detail_markets` loop inside the `with get_session()` context manager in `src/cli/commands.py`, ensuring all ORM attribute access happens within an active session.

files_changed:
  - src/cli/commands.py (indented trader discovery loop into session block)
