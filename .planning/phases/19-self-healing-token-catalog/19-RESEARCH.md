# Phase 19: Self-Healing Token Catalog - Research

**Researched:** 2026-02-27
**Domain:** SQLite data patching, Gamma API integration, token catalog enrichment
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Root Cause (Locked)**
- `token_catalog` is built exclusively from JBecker's markets parquet
- 401 condition_ids in `trades` have no matching `token_catalog` entry
- These are markets JBecker never indexed (scattered across all dates — not a simple cutoff issue)
- 177 are eSports markets (actively affect classification/scoring)
- 206 are other categories (Sports, Politics, etc. — traders legitimately bet on anything)
- 18 are other categories (Sports, Politics, Crypto, AI, etc.)

**Detection Strategy (Locked)**
- After backfill completes, query: `SELECT DISTINCT t.market_id FROM trades t LEFT JOIN token_catalog tc ON t.market_id = tc.condition_id WHERE tc.condition_id IS NULL`
- This finds all condition_ids with trades but no catalog entry
- Must run after every backfill, not just once

**Patch Strategy — 3-tier lookup (Locked)**
- Tier 1 (local, free): Join `markets` table → extract token IDs from `markets.tokens` JSON → look up those token IDs in `gamma_events.clob_token_ids` → extract tags for node_path/depth
- Tier 2 (API, for markets not in gamma_events): Call Gamma API `/events` endpoint with condition_id or token_id lookup to get tags
- Tier 3 (fallback): Insert into token_catalog with category from `markets.category` but `node_path=NULL` — at minimum the market is known and categorized

**What Goes into token_catalog (Locked)**
- ALL categories (not just eSports) — traders bet on anything, all should be known
- eSports markets: full node_path from gamma_events tags if available
- Non-eSports markets: category populated, node_path=NULL is acceptable
- Idempotent: `INSERT OR IGNORE` or `ON CONFLICT DO NOTHING` — re-runs safe

**Integration Point (Locked)**
- Runs automatically at the END of the `backfill` CLI command
- Also available as standalone `patch-catalog` CLI command for manual runs
- Silent when nothing to patch (zero gaps = zero output)
- Reports count of markets patched and source used (local/api/fallback)

**Backlog Fix (Locked)**
- First run patches the existing 401-market / 10,850-trade backlog
- No separate one-time script needed — the automatic step handles it on first execution

### Claude's Discretion
- Whether patch logic lives in `src/catalog/` or `src/pipeline/` or a new `src/catalog/patcher.py`
- Exact batch size for Gamma API calls (to avoid rate limiting)
- Whether to log individual markets patched or just summary counts
- Test strategy (unit tests for the patch logic, integration test for the auto-trigger)

### Deferred Ideas (OUT OF SCOPE)
- Proactive catalog pre-population for new markets before trades arrive — out of scope, reactive is sufficient
- Enriching existing NULL node_path entries not linked to trades — out of scope
- Changing how token_catalog is built from JBecker — out of scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAT-01 | After `backfill` completes, any `trades.market_id` with no matching `token_catalog.condition_id` is detected automatically | Detection query confirmed; integration point is end of `backfill` CLI command in `commands.py` around line 1412 |
| CAT-02 | eSports markets get `node_path` via local `gamma_events` join; non-gamma markets get API lookup; all get at least a category | 3-tier patch logic fully mapped to real data; Gamma `/markets?conditionId=` already used in codebase (ingest.py:1779); `_extract_classification()` is reusable |
| CAT-03 | 401-market backlog patched on first run; re-runs are idempotent | `INSERT OR IGNORE` pattern verified in existing code; detection query returns 0 when catalog is complete |
</phase_requirements>

---

## Summary

Phase 19 patches a concrete, quantified data gap: 401 condition_ids present in `trades` have no matching row in `token_catalog`, making 10,850 trades permanently unclassifiable. The root cause is JBecker's dataset never indexed these markets. The solution is a 3-tier self-healing step that runs automatically after every `backfill` command.

The key technical finding is that the three tiers map differently across the 401 missing markets. Of the 156 lowercase `esports` category markets, ALL have `markets.tokens = NULL` — the local join cannot work for them, so they require a Gamma API call to fetch token IDs first. The 21 `eSports` (capital S) category markets DO have tokens and can be resolved entirely locally via the `gamma_events` table. The remaining 224 markets (Unknown/Sports/Politics/etc.) have tokens in `markets.tokens` but those token IDs do not appear in `gamma_events` (which only stores eSports events), so they fall through to the API tier and ultimately the fallback tier.

The Gamma API `/markets?conditionId=X` endpoint is already used in `ingest.py` (line 1779) and works correctly — it returns `clobTokenIds` from which token IDs can be extracted. The tag extraction logic from `gamma/classification.py` (`_extract_classification()`) is directly reusable. The correct module home is `src/catalog/patcher.py` — it belongs in `src/catalog/` alongside `builder.py` as a cohesive catalog management layer.

**Primary recommendation:** Create `src/catalog/patcher.py` with a `patch_missing_catalog_entries(session, gamma_client)` function, call it at the end of the `backfill` CLI command (after the success/error report), and expose it as a standalone `patch-catalog` CLI command.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.46 | ORM + raw SQL via `text()` | Already in use; `INSERT OR IGNORE` pattern established |
| httpx | 0.28.1 | Gamma API calls | Already in use; sync client matches existing pattern |
| loguru | 0.7.3 | Logging | Project standard |
| json | stdlib | Parsing `markets.tokens`, `gamma_events.clob_token_ids`, `gamma_events.tags` | Both fields are JSON strings |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + pytest-mock | 8.0+ | Unit tests with mocked sessions/API | Test tier 1/2/3 logic in isolation |
| click | 8.1 | Standalone `patch-catalog` CLI command | Follows existing command pattern |
| rich.console | 13.0 | Progress output | Matches existing backfill output style |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `src/catalog/patcher.py` | `src/pipeline/ingest.py` inline | Ingest.py is already 2,074 lines; catalog logic belongs with catalog |
| `src/catalog/patcher.py` | `src/gamma/patcher.py` | Gamma module is for gamma-event-specific logic; this is catalog management |

**Installation:** No new dependencies required. All needed libraries are already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

```
src/
├── catalog/
│   ├── __init__.py
│   ├── builder.py          # existing — builds catalog from JBecker
│   └── patcher.py          # NEW — patches missing entries after backfill
├── gamma/
│   ├── classification.py   # reuse _extract_classification() here
│   └── ...
└── cli/
    └── commands.py         # add patch-catalog command + hook into backfill
```

### Pattern 1: 3-Tier Detection and Patch Flow

**What:** Detect gaps, attempt local join (Tier 1), fall back to API (Tier 2), insert with category-only fallback (Tier 3).

**When to use:** After every backfill run. Also callable standalone.

**Example:**

```python
# Source: research of ingest.py:1779 + gamma/classification.py + persist.py patterns

def patch_missing_catalog_entries(session: Session, gamma_client: GammaMarketClient) -> dict:
    """Detect and patch token_catalog gaps. Returns summary dict."""

    # Step 1: Detect gaps
    missing = session.execute(text("""
        SELECT DISTINCT t.market_id
        FROM trades t
        LEFT JOIN token_catalog tc ON t.market_id = tc.condition_id
        WHERE tc.condition_id IS NULL
    """)).scalars().all()

    if not missing:
        return {"patched": 0, "local": 0, "api": 0, "fallback": 0}

    stats = {"patched": 0, "local": 0, "api": 0, "fallback": 0}

    # Step 2: For each missing condition_id, get market metadata
    rows_to_insert = _build_catalog_rows(session, missing, gamma_client, stats)

    # Step 3: Bulk insert with idempotency
    if rows_to_insert:
        session.execute(
            text("""
                INSERT OR IGNORE INTO token_catalog
                  (token_id, condition_id, question, niche_slug, node_path, depth, market_type)
                VALUES
                  (:token_id, :condition_id, :question, :niche_slug, :node_path, :depth, :market_type)
            """),
            rows_to_insert,
        )
        session.commit()

    return stats
```

### Pattern 2: Token ID Lookup Chain

**What:** For a given condition_id, build rows for token_catalog. Try local gamma_events first, then API.

```python
# Source: analysis of actual data + ingest.py:1777-1800 pattern

def _build_catalog_rows(session, condition_ids, gamma_client, stats) -> list[dict]:
    rows = []
    needs_api = []

    for condition_id in condition_ids:
        market = session.query(Market).filter_by(condition_id=condition_id).first()
        if not market:
            continue

        # Tier 1: markets.tokens JSON -> token_id -> gamma_events.clob_token_ids join
        token_ids = _parse_token_ids_from_market(market)
        if token_ids:
            for token_id in token_ids:
                gamma_hit = _lookup_token_in_gamma_events(session, token_id)
                if gamma_hit:
                    node_path, depth = _extract_classification(json.loads(gamma_hit.tags))
                    rows.append(_make_row(token_id, condition_id, market, node_path, depth))
                    stats["local"] += 1
                else:
                    needs_api.append((condition_id, market))
                    break  # Only need to flag the condition once
        else:
            # NULL tokens — must use API
            needs_api.append((condition_id, market))

    # Tier 2: API batch lookup for conditions not resolved locally
    api_rows = _lookup_via_api(session, needs_api, gamma_client, stats)
    rows.extend(api_rows)

    return rows
```

### Pattern 3: Gamma API Lookup — Confirmed Working

**What:** `GET /markets?conditionId=X` returns market JSON with `clobTokenIds` field.

**Already proven in codebase:** `ingest.py` lines 1777-1800 use exactly this pattern.

```python
# Source: ingest.py:1777-1800 (verified in codebase)

BATCH_SIZE = 20  # Matches existing usage

resp = httpx.get(
    "https://gamma-api.polymarket.com/markets",
    params=[("conditionId", cid) for cid in batch],
    timeout=10,
)
if resp.status_code == 200:
    for md in resp.json():
        cid = md.get("conditionId")
        clob_tokens = md.get("clobTokenIds")
        tags = md.get("tags", [])  # tags in /markets response
        # clob_tokens is either a JSON string or list
        token_ids = json.loads(clob_tokens) if isinstance(clob_tokens, str) else clob_tokens
```

**Important:** The `/markets` response includes a `tags` field. This means for Tier 2 API calls, we can extract both token IDs AND classification tags in a single request — no need for a separate gamma_events lookup for API-sourced markets.

### Pattern 4: Integration into backfill CLI Command

**What:** Hook the patch call after backfill completes, before the function returns.

```python
# Source: commands.py:1402-1412 (end of backfill command)

# EXISTING code (lines 1402-1412):
processing_time = time.time() - start_time
console.print(f"\n[bold green]Backfill complete[/bold green] ({processing_time:.1f}s)")
console.print(f"  Successful: [green]{success_count}[/green]")
if error_count:
    console.print(f"  Failed:     [red]{error_count}[/red]")

# ADD AFTER: patch-catalog auto-step
from src.catalog.patcher import patch_missing_catalog_entries
with get_session(session_factory) as session:
    patch_stats = patch_missing_catalog_entries(session, gamma_client)
if patch_stats["patched"] > 0:
    console.print(f"  Catalog patched: [cyan]{patch_stats['patched']} markets[/cyan]"
                  f" (local={patch_stats['local']}, api={patch_stats['api']}, "
                  f"fallback={patch_stats['fallback']})")
```

Also applies to the single-trader path (lines 1248-1255): the hook should run in both code paths.

### Anti-Patterns to Avoid

- **Running the patch PER-TRADER inside `ingest_trader_history_hybrid`:** Each individual trade ingestion completes a session; running 401 API lookups per-trader wastes work and creates redundant calls. Run once at the end of the full `backfill` command instead.
- **Parsing `gamma_events.clob_token_ids` with LIKE queries:** The current LIKE search (`clob_token_ids LIKE '%token_id%'`) is O(n) per token. For 401 markets this is acceptable, but build a proper dict lookup by exploding token IDs in Python if performance is needed.
- **Inserting one token_id per condition_id:** Each condition_id has 2 token IDs (YES and NO outcomes). Both must be inserted. Confirmed by examining `markets.tokens` JSON format — it always contains a list of 2 token objects.
- **Inserting placeholder `token_id` when tokens are completely unknown:** If Tier 2 API call fails AND `markets.tokens` is NULL, there is no token_id to insert. In this case, skip the row entirely and log it rather than inserting a fake token_id.
- **Assuming `markets.category` is always accurate:** 206 of 401 markets have `category='Unknown'` in the database. The Gamma API `/markets` response includes a `tags` field which gives the real category. Use the API response category when available.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tag → node_path extraction | Custom tag parser | `_extract_classification()` from `gamma/classification.py` | Already handles esports/game/tournament/team depth logic, tested |
| Gamma API pagination | Custom pagination loop | `GammaMarketClient.get_events()` or direct `httpx.get()` with batch params | Already handles pagination, rate limiting |
| Idempotent upsert | Custom conflict detection | `INSERT OR IGNORE` (SQLite) | Pattern used in `builder.py:183` and `persist.py:54` |
| Category from API | Text parsing of question | `md.get("tags", [])` from `/markets` response | Gamma provides authoritative tags |

**Key insight:** The codebase already contains all the primitives needed. `patcher.py` is an orchestrator that calls existing functions in the right order.

---

## Critical Data Findings

### Token ID Format Is Consistent (HIGH confidence)

**Verified against actual database:** Both `markets.tokens` and `gamma_events.clob_token_ids` use the same big-integer string format for token IDs.

```
markets.tokens (JSON array of objects):
  [{"token_id": "52573332212624920803134176...", "outcome": ""}, ...]

gamma_events.clob_token_ids (JSON array of strings):
  ["23860123835680951957307901500...", "34273347238667513420824944097...", ...]
```

These are directly comparable. The local join IS feasible when `markets.tokens` is not NULL.

**Confirmed by live test:** Token `4731307515800632610127018...` from an unclassifiable `eSports` market was found in `gamma_events` event 220242 with correct Dota 2 tags.

### markets.tokens NULL Rate by Category (HIGH confidence)

Verified against actual data (401 unclassifiable markets in trades):

| Category | Total Missing | NULL tokens | Has tokens | Tier 1 viable? |
|----------|--------------|-------------|------------|----------------|
| esports (lowercase) | 156 | 156 | 0 | NO — all NULL |
| Unknown | 206 | 0 | 206 | Partially — tokens exist but not in gamma_events |
| eSports (capital S) | 21 | 0 | 21 | YES — tokens found in gamma_events |
| Sports | 9 | 0 | 9 | NO — not in gamma_events |
| Politics | 3 | 0 | 3 | NO — not in gamma_events |
| Crypto | 3 | 0 | 3 | NO — not in gamma_events |
| Culture | 1 | 0 | 1 | NO — not in gamma_events |
| Business | 1 | 0 | 1 | NO — not in gamma_events |
| AI | 1 | 0 | 1 | NO — not in gamma_events |

**Implication:** Tier 1 (local join) only works for the 21 eSports markets with tokens present in `gamma_events`. The 156 lowercase `esports` markets have NULL tokens and require a Tier 2 API call. The 224 non-eSports markets have tokens but those tokens are not in `gamma_events` (we only stored eSports events) — they also need Tier 2 API or fall to Tier 3.

**In practice:** Most of the 401 will flow through Tier 2 (API) or Tier 3 (fallback). Tier 1 handles ~21 markets without API calls.

### Gamma API /markets?conditionId= Confirmed Working (HIGH confidence)

**Source:** `ingest.py` lines 1777-1800 already use this endpoint with batch `conditionId` params. It returns:
- `conditionId` — the hex condition ID
- `clobTokenIds` — JSON string or list of big-int token ID strings
- `tags` — list of tag objects with `slug` field (same format as gamma_events.tags)
- `question` — market question text
- `category` — market category (more reliable than `markets.category`)

**Batch size:** 20 condition IDs per request (matches existing usage). With 401 markets: 21 batches maximum. At 50ms sleep between batches: ~1 second total API time.

### niche_slug Mapping for Non-eSports Markets (MEDIUM confidence)

Current `token_catalog.niche_slug` only contains `'esports'`. For Phase 19 inserts of non-eSports markets:
- Set `niche_slug` to lowercase of `markets.category` (e.g., `'sports'`, `'politics'`, `'crypto'`)
- For `category='Unknown'`: use the Gamma API `tags[0].slug` if available, else `'unknown'`
- `node_path=NULL` is acceptable for all non-eSports inserts per locked decisions

### trades.market_id is Always a condition_id (HIGH confidence)

**Verified:** All `trades.market_id` values are `0x`-prefixed hex strings (condition IDs). No big-integer token IDs appear in `trades.market_id`. The join `trades.market_id = token_catalog.condition_id` is the correct join key.

---

## Common Pitfalls

### Pitfall 1: esports vs eSports Category Mismatch
**What goes wrong:** 156 lowercase `esports` markets exist alongside 21 `eSports` (capital S) markets. Treatment is identical (both eSports), but string comparison `== 'esports'` misses the capital-S variant.
**Why it happens:** Markets come from different data sources with inconsistent casing.
**How to avoid:** Use `market.category.lower() == 'esports'` for category comparisons.
**Warning signs:** Failing to find eSports markets in Tier 1 despite them being present.

### Pitfall 2: NULL tokens.markets Means No Tier 1 Path
**What goes wrong:** 156 esports markets have `markets.tokens = NULL`, making Tier 1 impossible. Attempting to parse NULL as JSON raises an exception.
**Why it happens:** JBecker dataset didn't store token IDs for these markets. The markets table has the market but not its token IDs.
**How to avoid:** Always check `market.tokens is not None` before attempting JSON parse. Skip directly to Tier 2 if NULL.
**Warning signs:** JSON parse errors on market.tokens.

### Pitfall 3: Only One token_id per condition_id
**What goes wrong:** Inserting only the first token_id for each condition_id, leaving the second token unresolvable.
**Why it happens:** Every binary market has 2 outcome tokens (YES and NO). Both have the same condition_id but different token_ids. Both must be in `token_catalog`.
**How to avoid:** Always iterate over the full `clobTokenIds` list from the API or `markets.tokens` JSON list.
**Warning signs:** `token_catalog` has 1 row per condition_id instead of 2.

### Pitfall 4: Re-running Patch Makes Unnecessary API Calls
**What goes wrong:** Every backfill run makes API calls even when catalog is already complete.
**Why it happens:** Not checking the detection query first.
**How to avoid:** Run the detection query first. If result is empty, return immediately with zero-output.
**Warning signs:** API calls on second run when nothing has changed.

### Pitfall 5: API Response Tags Missing vs gamma_events Tags
**What goes wrong:** Expecting `/markets` API response to have the same tag structure as stored `gamma_events.tags`.
**Why it happens:** `gamma_events.tags` is the tags from the `/events` endpoint (event-level). `/markets` endpoint returns market-level tags which may have fewer hierarchical tags.
**How to avoid:** Accept that API-sourced tags may produce shallower `node_path` (e.g., just `esports/dota-2` without tournament). This is acceptable per locked decisions.
**Warning signs:** Zero `node_path` hits from API-sourced tags when eSports markets are present.

### Pitfall 6: session_factory vs session in CLI
**What goes wrong:** Calling `patch_missing_catalog_entries(session_factory, ...)` with wrong type.
**Why it happens:** The backfill command uses `session_factory` to create sessions via `get_session()` context manager.
**How to avoid:** The patch function should accept a `Session` (already opened) or use `session_factory`. Match the pattern of how the backfill command manages sessions (via `get_session(session_factory) as session`).
**Warning signs:** AttributeError on session usage.

---

## Code Examples

Verified patterns from actual codebase:

### Detection Query (condition_id gap detection)
```python
# Source: confirmed against actual data — returns 401 rows currently
missing_condition_ids = session.execute(text("""
    SELECT DISTINCT t.market_id
    FROM trades t
    LEFT JOIN token_catalog tc ON t.market_id = tc.condition_id
    WHERE tc.condition_id IS NULL
""")).scalars().all()
```

### Reuse Existing Tag Extraction (from gamma/classification.py)
```python
# Source: gamma/classification.py:12-28 — directly reusable
from src.gamma.classification import _extract_classification

tags = json.loads(gamma_event.tags)  # or API response tags
node_path, depth = _extract_classification(tags)
# Returns ("esports/dota-2/epl-sea-playoffs", 2) or (None, None)
```

### Local Token Lookup in gamma_events
```python
# Source: verified in actual DB — token IDs ARE in gamma_events.clob_token_ids

def _find_gamma_event_for_token(session: Session, token_id: str) -> GammaEvent | None:
    """Find a GammaEvent that contains this token_id in clob_token_ids."""
    events = session.query(GammaEvent).all()
    for event in events:
        if not event.clob_token_ids:
            continue
        try:
            token_ids = json.loads(event.clob_token_ids)
            if token_id in token_ids:
                return event
        except (json.JSONDecodeError, TypeError):
            continue
    return None

# NOTE: For performance, build a dict {token_id: GammaEvent} once per patch run
# rather than scanning all 8,864 events for each token. Build at start of patch call.
```

### Gamma API Batch Lookup (condition_id -> token_ids + tags)
```python
# Source: ingest.py:1777-1800 — adapted for patch use case

import httpx, time, json

BATCH_SIZE = 20
condition_ids_to_lookup = [...]  # list of 0x hex strings

for i in range(0, len(condition_ids_to_lookup), BATCH_SIZE):
    batch = condition_ids_to_lookup[i:i + BATCH_SIZE]
    try:
        resp = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params=[("conditionId", cid) for cid in batch],
            timeout=10,
        )
        if resp.status_code == 200:
            for md in resp.json():
                condition_id = md.get("conditionId")
                clob_tokens_raw = md.get("clobTokenIds")
                tags_raw = md.get("tags", [])
                question = md.get("question", "")
                category = md.get("groupItemTitle") or _extract_category_from_tags(tags_raw)

                token_ids = (
                    json.loads(clob_tokens_raw)
                    if isinstance(clob_tokens_raw, str)
                    else (clob_tokens_raw or [])
                )
                node_path, depth = _extract_classification(tags_raw)

                # Insert a row per token_id
                for token_id in token_ids:
                    rows.append({
                        "token_id": str(token_id),
                        "condition_id": condition_id,
                        "question": str(question)[:500],
                        "niche_slug": _derive_niche_slug(category, node_path),
                        "node_path": node_path,
                        "depth": depth,
                        "market_type": None,
                    })
    except Exception as e:
        logger.warning(f"Patch API batch failed: {e}")
    time.sleep(0.05)
```

### Idempotent INSERT (INSERT OR IGNORE)
```python
# Source: catalog/builder.py:183-193 — exact same pattern

session.execute(
    text("""
        INSERT OR IGNORE INTO token_catalog
          (token_id, condition_id, question, niche_slug, node_path, depth, market_type)
        VALUES
          (:token_id, :condition_id, :question, :niche_slug, :node_path, :depth, :market_type)
    """),
    rows_to_insert,  # list of dicts
)
session.commit()
```

### Standalone CLI Command Pattern (matches existing commands)
```python
# Source: commands.py pattern for new commands

@cli.command("patch-catalog")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def patch_catalog_cmd(verbose):
    """Detect and patch token_catalog gaps.

    Finds trades.market_id values with no token_catalog entry and patches
    them via local gamma_events join, Gamma API, or category-only fallback.

    Safe to re-run — idempotent (INSERT OR IGNORE).

    \\b
    Examples:
        polymarket patch-catalog
        polymarket patch-catalog --verbose
    """
    from src.catalog.patcher import patch_missing_catalog_entries

    session_factory, _, _, _, gamma_client = _get_dependencies()
    console = Console()

    with get_session(session_factory) as session:
        stats = patch_missing_catalog_entries(session, gamma_client)

    if stats["patched"] == 0:
        console.print("[green]No catalog gaps detected.[/green]")
    else:
        console.print(f"[bold green]Catalog patched:[/bold green] {stats['patched']} markets")
        console.print(f"  Local (gamma_events): {stats['local']}")
        console.print(f"  API lookup: {stats['api']}")
        console.print(f"  Category-only fallback: {stats['fallback']}")
```

---

## Module Location Decision

**Recommendation:** `src/catalog/patcher.py` (Claude's discretion area)

**Rationale:**
1. `src/catalog/` already contains `builder.py` which manages the same `token_catalog` table
2. The patcher is conceptually "catalog management" not "pipeline ingestion"
3. `src/pipeline/ingest.py` is already 2,074 lines; adding more there would make it harder to navigate
4. `src/gamma/` is for Gamma Events-specific operations; the patcher uses Gamma as one of three tiers, not exclusively
5. Precedent: `builder.py` lives in `catalog/` and uses the Gamma API too

**Module interface:**
```python
# src/catalog/patcher.py

def patch_missing_catalog_entries(
    session: Session,
    gamma_client: GammaMarketClient | None = None,
) -> dict[str, int]:
    """
    Returns: {"patched": N, "local": N, "api": N, "fallback": N}
    patched = total markets with rows inserted
    local = resolved via gamma_events (no API call)
    api = resolved via Gamma API /markets
    fallback = category-only insert (no node_path)
    """
```

---

## Test Strategy

**Framework:** pytest 8.0 (already installed)
**Run command:** `python -m pytest tests/test_catalog_patcher.py -x -q`
**Full suite:** `python -m pytest -x -q`

### Test File: `tests/test_catalog_patcher.py`

**Unit tests (mock-based — fast, isolated):**

1. `test_no_gaps_returns_zero` — when detection query returns empty, function returns immediately with zeros
2. `test_tier1_local_hit` — market with tokens present in gamma_events gets correct node_path
3. `test_tier1_null_tokens_falls_to_tier2` — market with NULL tokens bypasses Tier 1, goes to API
4. `test_tier2_api_hit_with_tags` — API response with tags produces node_path in insert rows
5. `test_tier2_api_hit_no_tags` — API response without eSports tags produces NULL node_path
6. `test_tier3_fallback_on_api_failure` — API exception → fallback row with category only
7. `test_idempotent_second_run_inserts_nothing` — running twice with same state inserts 0 new rows
8. `test_both_token_ids_inserted_per_condition` — confirms 2 rows per binary market
9. `test_niche_slug_from_category` — non-eSports market gets correct niche_slug (e.g., 'sports')
10. `test_unknown_category_handled` — 'Unknown' category markets get 'unknown' or API-derived niche_slug

**Integration test (in-memory SQLite):**

11. `test_full_patch_flow_integration` — real SQLite in-memory DB with pre-seeded trades, markets, gamma_events; mocked API; verify correct catalog rows inserted

**CLI test:**

12. `test_patch_catalog_command_cli` — via Click test runner; verify command runs, reports correct output

---

## Batch Size Recommendation

**Claude's discretion area.** Research finding: 20 condition IDs per request (matching existing usage in `ingest.py:1775`).

With 401 markets maximum and batch size 20: 21 API requests. At 50ms sleep per batch: ~1 second. This is fast enough that no progress bar is needed for the auto-trigger (just a single line: "Catalog patched: N markets").

For future runs with zero gaps: 0 API calls, 0 output. Totally silent.

---

## Logging Strategy

**Claude's discretion area.** Recommendation: summary counts only (no per-market logging at INFO level).

```python
# Summary level (always shown via console):
#   "Catalog patched: 401 markets (local=21, api=362, fallback=18)"

# Per-market at DEBUG level only (for --verbose):
logger.debug(f"Patched {condition_id[:10]}... via {source}")

# Summary at INFO level (goes to logfile):
logger.info(f"PATCH-CATALOG: patched={stats['patched']}, local={stats['local']}, "
            f"api={stats['api']}, fallback={stats['fallback']}")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| JBecker-only catalog (all markets) | JBecker + Gamma API patch for missing | Phase 19 | Eliminates silent 10,850-trade classification gap |
| Manual one-time fix script | Automatic post-backfill hook | Phase 19 | New backfills self-heal automatically |
| catalog/builder.py Gamma API calls (eSports only) | patcher.py Gamma API calls (all categories) | Phase 19 | Patches non-eSports markets too |

---

## Open Questions

1. **What does `/markets` API response's `tags` field look like for non-eSports markets?**
   - What we know: The `/markets` endpoint returns `tags` (verified in `ingest.py` code), and for eSports it works
   - What's unclear: Whether non-eSports tags use the same slug format and whether `_extract_classification` produces sensible paths for sports/politics tags
   - Recommendation: Accept whatever tags come back. For non-eSports, `node_path=NULL` is acceptable per locked decisions. The `_extract_classification` function will return `(None, None)` for non-esports tags since it filters for `slug != 'esports'` — meaning non-eSports markets will always go to Tier 3 (category-only) even after a successful API call. This is fine.

2. **Should the backfill hook run for the single-trader path too?**
   - What we know: `backfill` has two code paths: single address (lines 1238-1255) and bulk (lines 1256-1412)
   - What's unclear: Whether the patch is useful after a single-trader backfill (typically only a few new trades, likely already classified)
   - Recommendation: Run the patch in both paths for correctness. The detection query is fast (simple LEFT JOIN), so overhead is negligible even when result is zero.

3. **What if `markets` table doesn't have the condition_id at all?**
   - What we know: CONTEXT.md says "All 401 ARE in the `markets` table" — this is verified for the current backlog
   - What's unclear: Whether future backfills could produce trades for condition_ids not yet in `markets`
   - Recommendation: Handle gracefully — if `market` lookup returns None, log at DEBUG and skip. Don't fail the whole patch.

---

## Sources

### Primary (HIGH confidence)
- `src/pipeline/ingest.py` (lines 1777-1800) — confirmed Gamma `/markets?conditionId=` endpoint works, batch size 20, response format
- `src/gamma/classification.py` — `_extract_classification()` function confirmed reusable
- `src/catalog/builder.py` — `INSERT OR IGNORE` pattern confirmed
- `src/gamma/persist.py` — upsert pattern confirmed
- `data/polymarket.db` — live data queries confirming 401 markets, token format, gamma_events join feasibility

### Secondary (MEDIUM confidence)
- `src/cli/commands.py` (lines 1191-1412) — backfill command structure confirmed; integration points identified
- `src/db/models.py` — TokenCatalog, Market, GammaEvent field names confirmed

### Tertiary (LOW confidence)
- Assumption: Gamma `/markets` API response `tags` field has same slug format for non-eSports categories — not directly tested against live API, but consistent with builder.py and ingest.py usage patterns

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries already in use
- Architecture: HIGH — module location and function signatures derived from actual codebase analysis
- Data formats: HIGH — verified against live database with specific token ID lookups
- Gamma API behavior: HIGH — endpoint already used in production code (ingest.py)
- Pitfalls: HIGH — most derived from actual data findings (NULL tokens, category casing)

**Research date:** 2026-02-27
**Valid until:** 2026-03-27 (Gamma API endpoints are stable; data formats are stable)
