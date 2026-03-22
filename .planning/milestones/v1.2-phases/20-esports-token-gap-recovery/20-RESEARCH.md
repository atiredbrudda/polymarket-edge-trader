# Phase 20: eSports Token Gap Recovery - Research

**Researched:** 2026-02-27
**Domain:** SQLite data repair, Gamma Events API, ingest pipeline fix
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Root Cause (Locked)**
- `ingest_trader_history_jbecker` hit markets without `tokens` data in the `markets` table
- The populate-tokens block (~line 1777 in `src/pipeline/ingest.py`) called `GET /markets?conditionId=X` on the Gamma API
- The Gamma API **ignores** the `conditionId` query param and returns random unrelated markets
- No token data was found for those random markets, so `markets.tokens` stayed NULL
- With `tokens=NULL`, Tier 1 patcher (needs token_ids) and Tier 2 patcher (also needs token_ids) both skip the market — it gets only a Tier 3 category-only entry or nothing

**Fix Strategy — Events API (Locked)**
- The Gamma Events API (`GET /events?tag_id=64`) returns events with nested `markets[]`
- Each nested market has both `conditionId` AND `clobTokenIds` — exactly what we need
- Scan all eSports events (tag_id=64 covers all games)
- For each nested market: if `conditionId` matches one of the 156 gap markets — extract `clobTokenIds`
- Store as JSON in `markets.tokens` for that condition_id
- Then re-run the patcher — Tier 1 will now find these markets in `gamma_events` and populate `token_catalog` with correct `node_path`

**What the Recovery Does NOT Need (Locked)**
- Does NOT need to insert into `gamma_events` — we already have eSports events there from Phase 15
- Does NOT need to call CLOB API — `GET /markets/{conditionId}` returned "market not found" for these old markets
- Does NOT need to scan JBecker markets parquet — checked and 0/156 gap markets are in JBecker markets data
- Does NOT need a new API endpoint — the existing events scan pattern from Phase 15 is sufficient

**ingest.py Fix (Locked)**
- The populate-tokens block at ~line 1777 must be replaced with an events-based lookup
- Instead of `GET /markets?conditionId=X`, use: fetch events by tag_id → match conditionId in nested markets → extract clobTokenIds
- This is the same events API used by the recovery step — one reusable function
- The fix prevents any future backfill from creating new null-token gaps for eSports markets

**Re-scoring (Locked)**
- After token_catalog is populated for the 156 markets, the scoring pipeline must be re-run
- Affected traders: up to 1,451 unique traders who had trades on these markets
- Re-scoring is done via the existing `score` CLI command — no new logic needed
- The leaderboard should be re-run after scoring to reflect updated specialization scores

**Token Format (Locked)**
- `markets.tokens` stores a JSON string matching the format used by the existing populate-tokens block: `[{"token_id": "...", "outcome": ""}, ...]`
- Gamma Events API returns `clobTokenIds` as a JSON array — parse and wrap each id in `{"token_id": tid, "outcome": ""}` before storing
- Patcher Tier 1 reads `markets.tokens` via `json.loads()` and calls `token_entry.get("token_id")` — same dict format required

**Scope Boundary (Locked)**
- The 2 remaining non-eSports null-token markets (158 total - 156 eSports = 2 other) are out of scope
- They will be handled by Tier 3 (category-only) as before — no node_path needed

### Claude's Discretion
- Whether recovery logic lives in `src/catalog/patcher.py` as a pre-pass, in `src/ingest.py`, or a new `src/catalog/recovery.py`
- Whether to expose a `recover-catalog` CLI command or run recovery as part of `patch-catalog`
- Exact eSports tag slugs to scan (need to enumerate all: counter-strike, valorant, dota-2, league-of-legends, overwatch, etc.)
- Batch size for events API calls (pagination)
- Whether to re-score inline or instruct user to run `score` manually after
- Test strategy: mock events API responses, assert markets.tokens updated, assert token_catalog populated

### Deferred Ideas (OUT OF SCOPE)
- Generalizing the events-based token recovery to non-eSports categories (Sports, Politics, etc.)
- Making recovery incremental (only scan tags for markets that are missing)
- Adding a monitoring alert when null-token count exceeds a threshold after backfill
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| GAP-01 | All 156 null-token eSports markets have `markets.tokens` populated via Gamma Events API tag-based scan, enabling Tier 1 patcher to classify them | Recovery function fetches events via `tag_id=64`, cross-references 156 gap condition_ids against nested `markets[].conditionId`, writes `[{"token_id": tid, "outcome": ""}]` to `markets.tokens`, then runs existing `patch_missing_catalog_entries()` |
| GAP-02 | `ingest.py` populate-tokens block uses events endpoint (not broken `?conditionId=` param) to prevent recurrence of null-token gap | Lines 1764-1804 in `src/pipeline/ingest.py` replace `GET /markets?conditionId=X` with the same events-based lookup function used by recovery |
| GAP-03 | After recovery, all 3,633 affected trades are classifiable and trader eSports scores reflect the newly attributed activity | After GAP-01 populates `markets.tokens` and patcher fills `token_catalog`, existing `score` CLI command re-computes expertise scores for all 1,451 affected traders |
</phase_requirements>

---

## Summary

Phase 20 is a targeted data-repair phase with zero new infrastructure. The 156 null-token eSports markets are already present in the database as `Market` rows with `tokens=NULL`. The 8,864-row `gamma_events` table already contains the events that have these markets in their nested `markets[]` arrays — but Tier 1 of the patcher cannot use them because `markets.tokens` is NULL (no token_ids to use as the lookup key into `gamma_events.clob_token_ids`).

The recovery strategy is: populate `markets.tokens` with the correct dict-format token list by fetching events from the Gamma API via `tag_id=64`, then iterating nested `markets[]` to match on `conditionId`. Once `markets.tokens` is populated, the existing `patch_missing_catalog_entries()` function handles everything else — Tier 1 will successfully cross-reference token_ids into `gamma_events`, extract tags, call `_extract_classification()`, and write `token_catalog` rows with `node_path` and `depth`. The fix to `ingest.py` replaces the broken `GET /markets?conditionId=X` block with the same events-based lookup, preventing recurrence.

The critical token format detail: `markets.tokens` must be `[{"token_id": "...", "outcome": ""}, ...]` — a list of dicts, not a plain string array. Both the existing `ingest.py` populate-tokens block (line 1794-1796) and Tier 1 of the patcher (`token_entry.get("token_id")`) confirm this format. Getting this wrong would silently leave all 156 markets unresolvable.

**Primary recommendation:** Write a `recover_esports_token_gaps()` function in a new `src/catalog/recovery.py` that fetches events via `tag_id=64`, populates `markets.tokens` for all 156 gap markets, then calls `patch_missing_catalog_entries()`. Expose it as a `recover-catalog` CLI command. Fix `ingest.py` to call the same events-lookup helper instead of the broken conditionId endpoint.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | existing | Gamma API HTTP calls | Already used throughout patcher.py and builder.py |
| sqlalchemy | existing | ORM session + raw text queries | All DB access in this project uses SQLAlchemy |
| loguru | existing | Structured logging | Project-wide logging standard |
| json (stdlib) | stdlib | Parse/write `markets.tokens` and `clobTokenIds` | No new dependency needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| click | existing | CLI command registration | For `recover-catalog` command in `commands.py` |
| rich Console | existing | User-facing output formatting | All CLI commands use Rich for output |

No new dependencies required. All libraries are already installed.

**Installation:** None — use existing virtualenv.

---

## Architecture Patterns

### Recommended Module Structure

The recovery logic should live in a dedicated module rather than growing `patcher.py` or `ingest.py`:

```
src/catalog/
├── builder.py      # TokenCatalogBuilder — unchanged
├── patcher.py      # patch_missing_catalog_entries() — unchanged
└── recovery.py     # NEW: recover_esports_token_gaps() + shared helper
```

The shared helper (`_fetch_esports_events_index`) is the key: a function that fetches all eSports events (tag_id=64) from the Gamma API and returns a dict mapping `conditionId -> [{"token_id": tid, "outcome": ""}]`. Both `recovery.py` and the fixed block in `ingest.py` call this same helper.

### Pattern 1: Events-Based conditionId Lookup

**What:** Fetch all eSports events via `tag_id=64`, iterate nested `markets[]` to build a `conditionId -> tokens` index, then look up gap markets.

**When to use:** Any time you need token_ids for a market and only have its `conditionId`.

**Example:**
```python
# Source: mirrors TokenCatalogBuilder._fetch_all_events() in src/catalog/builder.py
# and GammaMarketClient.get_closed_esports_events() in src/api/gamma_client.py

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
ESPORTS_TAG_ID = 64
PAGE_SIZE = 200  # matches get_closed_esports_events() batch size

def _fetch_esports_events_index() -> dict[str, list[dict]]:
    """Fetch all eSports events and build conditionId -> tokens mapping.

    Returns:
        Dict mapping condition_id -> [{"token_id": tid, "outcome": ""}, ...]
    """
    index: dict[str, list[dict]] = {}
    offset = 0

    while True:
        params = {
            "active": "false",   # gap markets are old/closed
            "tag_id": ESPORTS_TAG_ID,
            "limit": PAGE_SIZE,
            "offset": offset,
            "order": "endDate",
            "ascending": "true",
        }
        resp = httpx.get(f"{GAMMA_BASE_URL}/events", params=params, timeout=60.0)
        resp.raise_for_status()
        events = resp.json()

        if not events:
            break

        for event in events:
            for market in (event.get("markets") or []):
                condition_id = market.get("conditionId")
                clob_token_ids = market.get("clobTokenIds")

                if not condition_id or not clob_token_ids:
                    continue

                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except (json.JSONDecodeError, TypeError):
                        continue

                if not isinstance(clob_token_ids, list):
                    continue

                index[condition_id] = [
                    {"token_id": str(tid), "outcome": ""}
                    for tid in clob_token_ids
                    if tid and str(tid) != "0"
                ]

        if len(events) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return index
```

### Pattern 2: Idempotent markets.tokens Update

**What:** Update `markets.tokens` only where currently NULL, using SQLAlchemy ORM.

**When to use:** Recovery run — must be safe to re-run without overwriting valid data.

**Example:**
```python
# Source: mirrors pattern from ingest.py lines 1787-1796
def recover_esports_token_gaps(session: Session) -> dict[str, int]:
    """Populate markets.tokens for null-token eSports gap markets.

    Returns:
        Dict with keys: found (gap markets found), populated (tokens written),
                        already_done (markets skipped, tokens already present)
    """
    stats = {"found": 0, "populated": 0, "already_done": 0}

    # Find the 156 gap markets: eSports category, tokens=NULL, have trades
    gap_markets = session.execute(text("""
        SELECT DISTINCT m.condition_id
        FROM markets m
        JOIN trades t ON t.market_id = m.condition_id
        WHERE m.tokens IS NULL
          AND LOWER(m.category) = 'esports'
    """)).scalars().all()

    stats["found"] = len(gap_markets)
    if not gap_markets:
        logger.info("RECOVER-CATALOG: No null-token eSports markets found")
        return stats

    logger.info(f"RECOVER-CATALOG: Found {len(gap_markets)} null-token eSports markets")

    # Build conditionId -> tokens index from Gamma Events API
    events_index = _fetch_esports_events_index()
    logger.info(f"RECOVER-CATALOG: Events index built ({len(events_index)} markets)")

    for condition_id in gap_markets:
        tokens = events_index.get(condition_id)
        if not tokens:
            logger.debug(f"  No tokens found in events for {condition_id[:8]}...")
            continue

        market = session.query(Market).filter_by(condition_id=condition_id).first()
        if not market:
            continue

        if market.tokens is not None:
            stats["already_done"] += 1
            continue

        market.tokens = json.dumps(tokens)
        stats["populated"] += 1
        logger.debug(f"  Populated tokens for {condition_id[:8]}... ({len(tokens)} tokens)")

    session.commit()
    logger.info(
        f"RECOVER-CATALOG: populated={stats['populated']}, "
        f"already_done={stats['already_done']}, found={stats['found']}"
    )
    return stats
```

### Pattern 3: Fixed ingest.py populate-tokens Block

**What:** Replace broken `GET /markets?conditionId=X` with events-based lookup using the shared helper.

**When to use:** Inside `ingest_trader_history_jbecker()` at lines 1764-1804 — called once per backfill batch for markets created via catalog-path that have no token data yet.

**Example:**
```python
# Source: replaces lines 1764-1804 in src/pipeline/ingest.py
# Reuses _fetch_esports_events_index() from src/catalog/recovery.py

# Populate tokens for catalog-path markets (created without token data)
if catalog_condition_ids:
    needs_tokens = [
        cid for cid in catalog_condition_ids
        if session.query(Market).filter_by(condition_id=cid).first() is not None
        and session.query(Market).filter_by(condition_id=cid).first().tokens is None
    ]
    if needs_tokens:
        logger.info(f"Fetching tokens for {len(needs_tokens)} catalog-path markets")
        from src.catalog.recovery import _fetch_esports_events_index
        events_index = _fetch_esports_events_index()
        populated = 0
        for cid in needs_tokens:
            tokens = events_index.get(cid)
            if tokens:
                market = session.query(Market).filter_by(condition_id=cid).first()
                if market and market.tokens is None:
                    market.tokens = json.dumps(tokens)
                    populated += 1
        try:
            session.commit()
        except Exception:
            session.rollback()
        logger.info(f"Populated tokens for {populated}/{len(needs_tokens)} catalog-path markets")
```

### Anti-Patterns to Avoid

- **Using plain string array format for markets.tokens:** `json.dumps(["tid1", "tid2"])` — Tier 1 patcher calls `token_entry.get("token_id")` and gets `None` from strings. Must be `[{"token_id": tid, "outcome": ""}, ...]`.
- **Calling `active=true` events only:** Gap markets are old/closed. Use `active=false` (or both active + closed) — mirrors `get_closed_esports_events()`.
- **Using `GET /markets?conditionId=X`:** Confirmed broken — Gamma API ignores this param and returns 20 random unrelated markets.
- **Calling recovery only once and assuming it is complete:** The events API may not cover 100% of the 156 gaps (some very old markets may not be in Gamma events at all). Log and accept a partial recovery — remaining gaps fall through to Tier 3 (category-only, no node_path).
- **Calling `_ensure_catalog_built()` before recovery:** The catalog builder uses `DELETE FROM token_catalog` on every build call — calling it mid-session would wipe freshly-inserted recovery rows.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token classification from tags | Custom tag parser | `_extract_classification(tags)` in `src/gamma/classification.py` | Already handles eSports tag hierarchy (game/tournament/team depth) |
| Inserting token_catalog rows | Custom INSERT | `patch_missing_catalog_entries()` in `src/catalog/patcher.py` | Already idempotent (INSERT OR IGNORE), handles all 3 tiers |
| Gamma API pagination | Custom while loop | Mirror `get_closed_esports_events()` from `src/api/gamma_client.py` | Correct offset logic and page-size already validated |
| CLI output formatting | Custom print | `Console()` from Rich | Project-wide standard, already used in every CLI command |
| Re-scoring traders | Custom score calculation | `polymarket score` CLI command | Calls `compute_all_game_scores()` + `refresh_all_positions()` correctly |

**Key insight:** Every building block already exists. The recovery is wiring, not invention.

---

## Common Pitfalls

### Pitfall 1: Wrong markets.tokens Format
**What goes wrong:** Recovery writes `json.dumps(["tid1", "tid2"])` (plain string list). Tier 1 patcher calls `token_entry.get("token_id")` — strings have no `.get()` and return None. Zero markets get classified even though `markets.tokens` is now populated.
**Why it happens:** CONTEXT.md says `["token_id_1", "token_id_2"]` but the actual patcher code and ingest.py both use the dict format `[{"token_id": tid, "outcome": ""}]`.
**How to avoid:** Copy the exact format from `ingest.py` line 1794-1796: `[{"token_id": tid, "outcome": ""} for tid in token_ids]`.
**Warning signs:** `patch_missing_catalog_entries()` returns `local=0` for all gap markets even after `markets.tokens` is populated.

### Pitfall 2: Active Events Filter Missing Closed Markets
**What goes wrong:** Calling `active=true` only — the 156 gap markets are old closed events. They will not appear in active events and the events index will be empty for them.
**Why it happens:** The `get_events()` method defaults to `active=True`. Phase 15's `get_closed_esports_events()` correctly uses `active=false`.
**How to avoid:** Use `active=false` when building the events index. If thoroughness is needed, fetch both active and closed (adds ~30s extra but covers all markets).
**Warning signs:** `events_index` is populated but none of the 156 gap condition_ids are found in it.

### Pitfall 3: Recovery Not Calling Patcher After Population
**What goes wrong:** Recovery populates `markets.tokens` but never calls `patch_missing_catalog_entries()`. `token_catalog` stays empty for the 156 markets — trades remain unclassifiable.
**Why it happens:** Recovery and patching are two separate steps that must be chained.
**How to avoid:** The `recover_esports_token_gaps()` function must call `patch_missing_catalog_entries(session, gamma_client)` after the tokens commit.
**Warning signs:** `markets.tokens` is populated but `SELECT COUNT(*) FROM token_catalog WHERE condition_id IN (gap_ids)` returns 0.

### Pitfall 4: 100% Recovery Rate Not Guaranteed
**What goes wrong:** Test asserts all 156 gap markets are recovered; test fails because some very old markets have no Gamma Events entry at all.
**Why it happens:** The Gamma Events API may not have full historical coverage. Some markets may have been created directly without a parent event.
**How to avoid:** Accept partial recovery in tests — assert `populated >= 0` (not `== 156`). Log how many were found vs. not found. Remaining unresolved markets fall to Tier 3 (category-only).
**Warning signs:** Test hardcodes `assert stats["populated"] == 156`.

### Pitfall 5: Double-Fetching Events Index in ingest.py
**What goes wrong:** The fixed ingest.py populate-tokens block calls `_fetch_esports_events_index()` once per trader backfill. If 1,000 traders are backfilled, this makes 1,000 x N API calls.
**Why it happens:** The block is inside `ingest_trader_history_jbecker()` which is called per trader.
**How to avoid:** Cache the events index at the batch level. The caller of `ingest_trader_history_jbecker()` should pre-fetch and pass the index as an optional parameter, similar to the existing `token_cache` parameter pattern.
**Warning signs:** Slow backfill; rate limiter hits; Gamma API returning 429 errors during bulk backfill.

---

## Code Examples

Verified patterns from codebase inspection:

### How Tier 1 Patcher Reads markets.tokens
```python
# Source: src/catalog/patcher.py lines 136-179 (_try_tier1_local)
if not market.tokens:
    return False

tokens_data = json.loads(market.tokens)  # must be a list
if not isinstance(tokens_data, list):
    return False

for token_entry in tokens_data:
    token_id = token_entry.get("token_id")  # DICT format required
    if not token_id or token_id == "0":
        continue
    event = gamma_index.get(token_id)  # lookup in gamma_events index
    # ...
```

### How gamma_events Index is Built (Tier 1 Lookup Key)
```python
# Source: src/catalog/patcher.py lines 113-127 (_build_gamma_event_index)
# gamma_events.clob_token_ids stores ALL token_ids for an event as JSON list
for event in session.query(GammaEvent).all():
    token_ids = json.loads(event.clob_token_ids)  # ["tid1", "tid2", ...]
    for tid in token_ids:
        index[tid] = event  # token_id -> GammaEvent lookup
```

**Key insight:** For Tier 1 to work, the token_id from `markets.tokens[n]["token_id"]` must be present in the `gamma_events.clob_token_ids` array of some gamma_events row. Since the 8,864 existing `gamma_events` rows were fetched from the same API source, the same token_ids that appear in `events[].markets[].clobTokenIds` should also be in the stored `gamma_events.clob_token_ids`.

### How Existing ingest.py Stores tokens (Reference Format)
```python
# Source: src/pipeline/ingest.py lines 1794-1796
market.tokens = json.dumps(
    [{"token_id": tid, "outcome": ""} for tid in token_ids]
)
```

### How TokenCatalogBuilder Iterates Nested Markets (Reuse Pattern)
```python
# Source: src/catalog/builder.py lines 134-173 (TokenCatalogBuilder.build)
for event in all_events:
    markets = event.get("markets") or []
    for market in markets:
        condition_id = market.get("conditionId") or market.get("condition_id")
        clob_token_ids = market.get("clobTokenIds")
        # parse clobTokenIds (may be JSON string or list)...
        # then process each token_id
```

### CLI Command Registration Pattern
```python
# Source: src/cli/commands.py lines 1431-1470 (patch_catalog_cmd — mirror this)
@cli.command("recover-catalog")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def recover_catalog_cmd(verbose):
    """Populate markets.tokens for null-token eSports gap markets, then re-patch."""
    # ... setup logger, console, session_factory, gamma_client ...
    with get_session(session_factory) as session:
        recovery_stats = recover_esports_token_gaps(session)
        patch_stats = patch_missing_catalog_entries(session, gamma_client)
    # ... print results ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `GET /markets?conditionId=X` for token lookup | `GET /events?tag_id=64` + nested markets iteration | Phase 20 (this phase) | Gamma API ignores conditionId param — events API is the only reliable path for old markets |
| Single `patch_missing_catalog_entries()` call | Recovery pre-pass + patcher call | Phase 20 (this phase) | Enables Tier 1 to handle markets that were previously permanently stuck in Tier 3 |

**Deprecated/outdated:**
- `GET /markets?conditionId=X` at ingest.py line 1779: confirmed broken — returns random unrelated markets. Remove and replace.

---

## Open Questions

1. **Will 100% of the 156 gap markets be found in the Gamma Events API?**
   - What we know: 8,864 gamma_events rows exist from Phase 15, fetched via `tag_id=64`. The 156 gap markets are eSports markets. If they had parent events, those events should be in the stored data.
   - What's unclear: Some very old eSports markets (2020-2021) may have been created directly without a parent event in the Gamma system. The events-index may cover 130-155 of 156, not all 156.
   - Recommendation: Accept partial recovery. Log "found X of 156 in events index" and let unresolved fall to Tier 3. Do not fail if coverage is < 100%.

2. **Should the events index be fetched live or read from the existing gamma_events table?**
   - What we know: The existing `gamma_events` table has 8,864 rows already stored from Phase 15. The `_build_gamma_event_index()` in patcher.py reads from that table (not from API).
   - What's unclear: Does the stored `gamma_events.clob_token_ids` correspond to events-level aggregated token_ids, or does it store market-level token_ids? Looking at `_extract_tokens_and_prices()` in `gamma/persist.py` — it aggregates ALL token_ids from ALL nested markets of an event into one flat list per event row. The patcher's `gamma_index` maps individual token_id -> GammaEvent.
   - Recommendation: For recovering `markets.tokens`, we need the nested `markets[].conditionId -> clobTokenIds` mapping — which is NOT stored per-market in `gamma_events` (only per-event aggregated). Therefore fetch from API (live), not from the stored table. OR: if the 8,864 events were stored with their full `markets[]` JSON (they aren't — only aggregated token_ids are stored), we'd need API.
   - **Resolution:** Fetch from API live. The stored `gamma_events` table does not have a conditionId -> tokens mapping per market — that information is only available via the API's nested `markets[]` field.

3. **Does the events index need both `active=false` and `active=true` calls?**
   - What we know: `get_closed_esports_events()` uses `active=false`. Gap markets are closed (old). The builder uses both active + closed for the token_catalog.
   - What's unclear: Could any of the 156 gaps be active markets? Unlikely given they have trades and are old, but not impossible.
   - Recommendation: Use `active=false` (matches `get_closed_esports_events()` which covers the ~8,500 closed events). If partial recovery after first attempt, optionally add `active=true` as a second pass.

---

## Sources

### Primary (HIGH confidence)
- `src/catalog/patcher.py` — full code inspection of Tier 1 `_try_tier1_local()` confirms dict-format requirement for `markets.tokens`; confirms `_build_gamma_event_index()` maps token_id -> GammaEvent
- `src/catalog/builder.py` — `TokenCatalogBuilder._fetch_all_events()` and `build()` confirm exact API call pattern (tag_id=64, offset pagination, nested markets iteration)
- `src/api/gamma_client.py` — `get_closed_esports_events()` confirms `active=false, tag_id=64` for historical eSports events; `get_events()` confirms `tag_id` param for events endpoint
- `src/pipeline/ingest.py` lines 1764-1804 — exact broken block confirmed: `params=[("conditionId", cid) for cid in batch]`; exact correct token format confirmed: `[{"token_id": tid, "outcome": ""}]`
- `src/gamma/persist.py` — `_extract_tokens_and_prices()` confirms `gamma_events` stores event-level aggregated token_ids (not per-market), so API fetch is needed for conditionId-level mapping
- `src/db/models.py` — `Market.tokens` is `String(1000)` nullable; `GammaEvent.clob_token_ids` is `Text` nullable; `TokenCatalog.token_id` is primary key
- `tests/test_catalog_patcher.py` — test patterns confirm correct testing approach (in-memory SQLite, `@patch("src.catalog.patcher.httpx.get")`, Market ORM insert)

### Secondary (MEDIUM confidence)
- CONTEXT.md Phase 20 — diagnostic investigation results: 156 gaps confirmed, 3,633 trades, 1,451 traders; CLOB API and JBecker parquet confirmed non-viable
- Project MEMORY.md — confirms `ingest.py` broken block at ~line 1777, confirms `GET /markets?conditionId=X` is broken and returns random markets

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already present, code inspection confirms exact patterns
- Architecture: HIGH — all building blocks exist; recovery is wiring existing functions
- Pitfalls: HIGH — token format pitfall discovered directly from code inspection (dict vs string array); other pitfalls from pattern analysis of existing code
- Recovery coverage: MEDIUM — whether all 156 gaps exist in events API is unconfirmed until runtime

**Research date:** 2026-02-27
**Valid until:** Stable — no external APIs or library versions need tracking. Valid indefinitely unless gamma_events schema changes.
