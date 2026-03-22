# Phase 17: Deep Token Classification - Research

**Researched:** 2026-02-25
**Domain:** SQLite UPDATE via SQLAlchemy, Gamma event tag parsing, token catalog enrichment
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CLASS-01 | Token catalog entries receive `node_path` at game/tournament/team depth from Gamma event tags | Gamma tags structure confirmed from Phase 15 Summary. Join path: gamma_events.clob_token_ids -> token_catalog.token_id. Tag slugs map directly to taxonomy depths. |
| CLASS-02 | Token catalog `depth` field reflects actual classification level (1=game, 2=tournament, 3=team) | Depth rule: count of non-"esports" tag slugs determines depth. Game only = 1, game+tournament = 2, game+tournament+team = 3. |
</phase_requirements>

## Summary

Phase 17 enriches the `token_catalog` table with `node_path` and `depth` values by joining `gamma_events.clob_token_ids` to `token_catalog.token_id` and parsing the `tags` JSON field of each event. Currently all 817k token catalog rows have `node_path=NULL` and `depth=NULL` — they only have `niche_slug='esports'`. The classification is stuck at the eSports root because the original `TokenCatalogBuilder` (now rewritten to use the Gamma API) does not populate these fields.

The Gamma Events API stores a `tags` JSON array on each event. From Phase 15 Summary, a real sample shows: `[{"id": 64, "slug": "esports", "label": "eSports"}, ...]`. Additional tags beyond the root eSports tag carry game, tournament, and team slugs. The slug values in these tags directly correspond to the taxonomy hierarchy. The classification logic is: count the non-"esports" / non-root tags to determine depth, and build a `node_path` like `esports/cs2` or `esports/cs2/iem-katowice` by joining the relevant tag slugs.

There are also three low-priority code quality issues (counter naming bug in `resolution.py`, unused `classify_token_outcome()` function, and a weak idempotency test in `test_gamma_resolution.py`) that belong in a separate cleanup plan. The main implementation plan (classify) and the cleanup plan (code quality) are independent and can run in parallel as separate wave plans.

**Primary recommendation:** Build a `classify_tokens` function in `src/gamma/classification.py` that scans all `gamma_events` rows, parses their `tags` JSON, constructs the appropriate `node_path` and `depth` for each event's tokens, and bulk-updates `token_catalog` using SQLAlchemy `text()` with `UPDATE OR IGNORE`. Wire it to a `polymarket classify-tokens` CLI command.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0 (already installed) | ORM + raw SQL via `text()` | Already the project's DB layer |
| json (stdlib) | 3.13 | Parse `gamma_events.tags` JSON column | Already used throughout gamma module |
| loguru | already installed | Logging classification progress | Already project-wide logger |
| click | already installed | CLI command registration | Already the project CLI framework |
| pytest | already installed | TDD for classification logic | Already the project test framework |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy `text()` | 2.0 | Bulk UPDATE with named params | When doing large batch updates (817k rows potentially) |
| `unittest.mock.MagicMock` | stdlib | Mock sessions in unit tests | All unit tests use this pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `text()` bulk UPDATE | ORM `session.query(TokenCatalog).filter(...).update(...)` | ORM update is cleaner but `text()` is more explicit about SQL and already used in `gamma/resolution.py` for the analogous operation |
| Single-pass UPDATE per token | Batch UPDATE with `executemany` | Batch is faster; single-pass is simpler. With ~817k rows, batch preferred. |

**Installation:** No new packages needed. All libraries already present.

## Architecture Patterns

### Recommended Project Structure

```
src/gamma/
├── __init__.py          # existing
├── persist.py           # existing — upsert_gamma_events
├── resolution.py        # existing — resolve_market_outcomes
└── classification.py    # NEW — classify_tokens_from_gamma_events

tests/
├── test_gamma_resolution.py   # existing (also gets cleanup)
└── test_gamma_classification.py  # NEW — TDD tests for classify_tokens
```

The new `classification.py` module mirrors the exact pattern of `resolution.py`: a pure function that takes a `Session`, reads from `gamma_events`, and updates `token_catalog`. This keeps the gamma module cohesive and makes the pattern instantly recognizable.

### Pattern 1: Gamma Tag Depth Determination

**What:** Parse a Gamma event's `tags` JSON array to compute `node_path` and `depth` for all its tokens.

**When to use:** For each row in `gamma_events` that has non-null `tags` and non-null `clob_token_ids`.

**Gamma tag structure (confirmed from Phase 15 SUMMARY):**
```json
[
  {"id": 64, "slug": "esports", "label": "eSports"},
  {"id": 123, "slug": "cs2", "label": "CS2"},
  {"id": 456, "slug": "iem-katowice-2024", "label": "IEM Katowice 2024"}
]
```

**Depth derivation rules:**
- Tags contain slugs at hierarchical levels: "esports" (root), then game slug, tournament slug, team slug
- The "esports" slug is always present (it is the tag_id=64 that was used to filter events)
- Non-"esports" tags: first = game, second = tournament, third = team
- `depth` = number of non-"esports" tag slugs present (min 1, max 3)
- `node_path` = slugs joined with "/" (e.g., "esports/cs2" or "esports/cs2/iem-katowice-2024")

**Example:**
```python
# Source: analysis of gamma_events.tags structure from Phase 15 Summary
def _extract_classification(tags: list[dict]) -> tuple[str | None, int | None]:
    """Extract node_path and depth from Gamma event tags.

    Args:
        tags: Parsed list of tag dicts, each with 'slug' and 'id' fields

    Returns:
        Tuple of (node_path, depth) or (None, None) if classification impossible
    """
    # Filter out root esports tag (id=64 or slug='esports')
    tag_slugs = [t.get("slug", "").strip() for t in tags if t.get("slug")]
    if not tag_slugs:
        return None, None

    # Remove the root 'esports' slug — it's always first
    non_esports = [s for s in tag_slugs if s != "esports"]

    if not non_esports:
        # Only root esports tag — game-level at minimum (depth=1)
        # We only know it's esports, no game sub-classification available
        return None, None

    # Build path: esports + game [+ tournament [+ team]]
    depth = min(len(non_esports), 3)  # cap at 3 (team level)
    path_parts = ["esports"] + non_esports[:depth]
    node_path = "/".join(path_parts)
    return node_path, depth
```

**IMPORTANT OPEN QUESTION:** The actual tag ordering in gamma_events is not fully verified. Phase 15 Summary only shows tags for a single event: `[{"id": 64, "slug": "esports", ...}, ...]`. We do not know if tags beyond the root "esports" tag consistently appear in game/tournament/team order, or whether tags beyond the esports tag reliably encode the sub-classification hierarchy. This must be verified by inspecting actual gamma_events data (query the DB after phases 15+16 have been run on the real DB, or live-query the API before implementation). See Open Questions.

### Pattern 2: Bulk UPDATE token_catalog via executemany

**What:** For each token in a gamma event's `clob_token_ids`, update `token_catalog` with the event's classification.

**When to use:** After computing `node_path`/`depth` for an event, apply to all its token IDs.

**Example (mirrors resolution.py pattern):**
```python
# Source: pattern from src/gamma/resolution.py and src/gamma/persist.py
from sqlalchemy import text
from sqlalchemy.orm import Session

def classify_tokens_from_gamma_events(session: Session) -> dict[str, int]:
    """Populate token_catalog.node_path and depth from gamma_events tags.

    For each gamma_events row, parse tags to derive classification,
    then UPDATE all token_catalog rows whose token_id appears in
    gamma_events.clob_token_ids.

    Returns:
        {"classified": N, "skipped_no_tags": M, "skipped_no_tokens": K,
         "skipped_shallow": L}
    """
    import json
    from loguru import logger
    from src.db.models import GammaEvent

    classified = 0
    skipped_no_tags = 0
    skipped_no_tokens = 0
    skipped_shallow = 0

    events = session.query(GammaEvent).all()
    logger.info(f"Processing {len(events)} gamma events for token classification")

    update_rows = []  # accumulate for batch update

    for event in events:
        # Parse tags
        if not event.tags:
            skipped_no_tags += 1
            continue
        try:
            tags = json.loads(event.tags)
        except (json.JSONDecodeError, TypeError):
            skipped_no_tags += 1
            continue

        node_path, depth = _extract_classification(tags)
        if node_path is None:
            skipped_shallow += 1
            continue

        # Parse token IDs
        if not event.clob_token_ids:
            skipped_no_tokens += 1
            continue
        try:
            token_ids = json.loads(event.clob_token_ids)
        except (json.JSONDecodeError, TypeError):
            skipped_no_tokens += 1
            continue

        for token_id in token_ids:
            if token_id:
                update_rows.append({
                    "token_id": token_id,
                    "node_path": node_path,
                    "depth": depth,
                })

    if update_rows:
        session.execute(
            text("""
                UPDATE token_catalog
                SET node_path = :node_path,
                    depth = :depth
                WHERE token_id = :token_id
                  AND niche_slug = 'esports'
            """),
            update_rows,
        )
        classified = len(update_rows)

    session.commit()
    logger.info(
        f"Classification complete: {classified} token updates, "
        f"{skipped_no_tags} events skipped (no tags), "
        f"{skipped_shallow} events skipped (no sub-classification), "
        f"{skipped_no_tokens} events skipped (no token IDs)"
    )
    return {
        "classified": classified,
        "skipped_no_tags": skipped_no_tags,
        "skipped_no_tokens": skipped_no_tokens,
        "skipped_shallow": skipped_shallow,
    }
```

### Pattern 3: CLI Command Registration

**What:** Wire `classify_tokens_from_gamma_events` to a `polymarket classify-tokens` CLI command.

**When to use:** Follows the exact pattern of `polymarket resolve-outcomes` (16-02-PLAN.md).

**Example:**
```python
# Source: pattern from src/cli/commands.py resolve-outcomes command
@cli.command("classify-tokens")
@click.pass_context
def classify_tokens(ctx):
    """Classify tokens in token_catalog using Gamma event tags."""
    settings = ctx.obj["settings"]
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        result = classify_tokens_from_gamma_events(session)

    console = Console()
    console.print(f"Done. {result['classified']} token updates applied.")
    console.print(f"  Events skipped (no sub-classification tags): {result['skipped_shallow']}")
    console.print(f"  Events skipped (no tags): {result['skipped_no_tags']}")
    console.print(f"  Events skipped (no token IDs): {result['skipped_no_tokens']}")
```

### Pattern 4: TDD Test Structure for Classification Logic

**What:** Unit tests for `classify_tokens_from_gamma_events` and `_extract_classification` using mocked sessions.

**When to use:** All new logic must be TDD — tests written first, then implementation.

**Example (mirrors test_gamma_resolution.py pattern):**
```python
# Source: pattern from tests/test_gamma_resolution.py
import json
from unittest.mock import MagicMock
import pytest
from src.gamma.classification import classify_tokens_from_gamma_events, _extract_classification


class TestExtractClassification:
    def test_game_and_tournament_tags(self):
        tags = [
            {"id": 64, "slug": "esports", "label": "eSports"},
            {"id": 1, "slug": "cs2", "label": "CS2"},
            {"id": 2, "slug": "iem-katowice-2024", "label": "IEM Katowice 2024"},
        ]
        node_path, depth = _extract_classification(tags)
        assert node_path == "esports/cs2/iem-katowice-2024"
        assert depth == 2

    def test_game_only_tag(self):
        tags = [
            {"id": 64, "slug": "esports", "label": "eSports"},
            {"id": 1, "slug": "cs2", "label": "CS2"},
        ]
        node_path, depth = _extract_classification(tags)
        assert node_path == "esports/cs2"
        assert depth == 1

    def test_esports_only_returns_none(self):
        tags = [{"id": 64, "slug": "esports", "label": "eSports"}]
        node_path, depth = _extract_classification(tags)
        assert node_path is None
        assert depth is None

    def test_empty_tags_returns_none(self):
        node_path, depth = _extract_classification([])
        assert node_path is None

    def test_game_tournament_team_tags(self):
        tags = [
            {"id": 64, "slug": "esports"},
            {"id": 1, "slug": "cs2"},
            {"id": 2, "slug": "iem-katowice-2024"},
            {"id": 3, "slug": "navi"},
        ]
        node_path, depth = _extract_classification(tags)
        assert node_path == "esports/cs2/iem-katowice-2024/navi"
        assert depth == 3


class TestClassifyTokensFromGammaEvents:
    def test_classifies_single_event(self):
        mock_session = MagicMock()
        mock_event = MagicMock()
        mock_event.event_id = "event_1"
        mock_event.tags = json.dumps([
            {"id": 64, "slug": "esports"},
            {"id": 1, "slug": "cs2"},
        ])
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_b"])
        mock_session.query.return_value.all.return_value = [mock_event]

        result = classify_tokens_from_gamma_events(mock_session)

        assert result["classified"] == 2
        assert result["skipped_no_tags"] == 0
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()
```

### Pattern 5: Code Quality Cleanup (Separate Plan)

**What:** Fix three pre-existing issues in `resolution.py` and `test_gamma_resolution.py`.

**Issues and fixes:**

1. **Counter naming bug** (`resolution.py:114`):
   The `resolved` counter counts token updates (21,594), not unique markets (10,797). CLI says `"Done. {resolved} markets resolved."` — misleading.
   Fix: Add separate `markets_resolved` counter that tracks unique Market objects touched. The simplest fix: use a `set()` to track market IDs instead of incrementing per token.

2. **Unused `classify_token_outcome()`** (`resolution.py`):
   The function is exported and tested but `resolve_market_outcomes()` uses inlined logic instead. Fix: either call it inside `resolve_market_outcomes()` (replacing the inlined `if token_id == winning_token: market.outcome = "YES"` logic), or remove it and its tests. The cleanest fix is to use it: replace the inline with `market.outcome = classify_token_outcome(token_id, winning_token)`.

3. **Weak idempotency test** (`test_gamma_resolution.py::test_idempotent_re_run`):
   The mock does not preserve `market.outcome` state between two calls to `resolve_market_outcomes()`. The test passes only because both calls return `resolved=1` (the counter is symmetric regardless of existing state). A meaningful idempotency test requires an in-memory SQLite database with real rows to confirm no duplicate rows or outcome flip occurs on re-run.
   Fix: Replace the mock-based test with an in-memory SQLite test using `Base.metadata.create_all(engine)` and real `Market`/`GammaEvent` rows, verifying outcome is identical after two runs.

**Anti-Patterns to Avoid**

- **Joining through market questions:** Do NOT use `PatternMatcher` or regex pattern matching for Phase 17. The Gamma tags are authoritative — no need to re-classify by title. Phase 13 used PatternMatcher on JBecker parquet market titles; Phase 17 uses Gamma tags directly.
- **Modifying token_catalog schema:** The schema already has `node_path` and `depth` columns. Do not add new columns — only UPDATE existing NULL rows.
- **Fetching live Gamma API:** All data is already in `gamma_events` table (8,519 rows). No new API calls needed.
- **Using `INSERT OR REPLACE`:** The existing rows in `token_catalog` have `token_id`, `condition_id`, `question`, and `niche_slug` populated. Use `UPDATE ... WHERE token_id = :token_id` — do not overwrite the whole row.
- **Assuming tag order is guaranteed:** The research confirms that Gamma events fetched via the API have a `tags` array, but the ordering of non-esports tags (game vs. tournament vs. team) has not been verified with multiple samples. This is the key risk. See Open Questions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parsing | Custom parser | `json.loads()` | Already used throughout gamma module |
| Batch SQL UPDATE | Row-by-row ORM updates | `session.execute(text(...), rows)` | Already proven pattern in resolution.py |
| DB session management | Custom transaction manager | `Session` context already in CLI | Consistent with all other commands |
| Tag hierarchy inference | External taxonomy lookup | Direct tag slug concatenation | Tags ARE the classification — no lookup needed |

**Key insight:** The Gamma tags are authoritative Polymarket classifications. There is no need to re-run PatternMatcher or look up the taxonomy YAML. The slug values in tags directly become the node_path segments.

## Common Pitfalls

### Pitfall 1: Unknown Tag Field Structure
**What goes wrong:** Code assumes `tag["slug"]` always exists and is the classification slug. In practice, tags may have unexpected shapes: `{"id": 64}` with no `slug`, or `{"slug": ""}` with empty slug.
**Why it happens:** Gamma API is a third-party API with undocumented tag schemas.
**How to avoid:** Always use `t.get("slug", "").strip()` and filter empty strings. Check `if not tag_slugs` before returning.
**Warning signs:** `KeyError: 'slug'` in tag parsing, or `node_path = "esports/"` (empty segment).

### Pitfall 2: Tag Ordering Not Guaranteed
**What goes wrong:** Assuming tags are always ordered [esports, game, tournament, team]. If Polymarket's API returns tags in a different order on some events, classification is wrong (e.g., assigning a team slug as if it were a game slug).
**Why it happens:** Phase 15 summary shows only one event's tags. Ordering convention may vary.
**How to avoid:** Before implementation, query several `gamma_events` rows to validate ordering. If ordering is unreliable, use tag `id` values or `label` text to identify levels. See Open Questions.
**Warning signs:** `node_path` values that look like `esports/iem-katowice-2024` without a game slug prefix.

### Pitfall 3: Tokens Not in token_catalog
**What goes wrong:** Gamma events reference token IDs that are not in `token_catalog`. The UPDATE silently affects 0 rows for those tokens. This is expected for tokens from the Gamma-sourced catalog that didn't appear in JBecker parquet.
**Why it happens:** `token_catalog` was built from Gamma API events (Phase 13 replacement) but may not cover all 8,519 closed events if some events postdate the catalog build.
**How to avoid:** Track `classified` as the count of actual UPDATE statements sent, not rows affected. Log the discrepancy. The CLI output should say "N token updates applied" not "N tokens classified".
**Warning signs:** `classified=0` despite events being processed — indicates token_catalog is empty or has no matching token_ids.

### Pitfall 4: Overwriting Better Classifications
**What goes wrong:** If a token appears in multiple Gamma events (shared token across events), the last event processed overwrites the previous classification. This can degrade depth if one event has only a game tag while another has game+tournament tags.
**Why it happens:** The UPDATE runs unconditionally for every event/token pair.
**How to avoid:** Only UPDATE if the new depth is GREATER than existing depth, or use a two-pass approach: compute max-depth classification per token_id first, then bulk-update. Simpler: add `AND (depth IS NULL OR depth < :depth)` to the WHERE clause.
**Warning signs:** Tokens losing tournament/team classification after classify-tokens is run multiple times.

### Pitfall 5: The `resolved` Counter Confusion (Code Quality Issue)
**What goes wrong:** The existing `resolve_market_outcomes()` uses `resolved` to count token updates (21,594) but the CLI displays it as "markets resolved". The actual market count is 10,797 (unique markets). This is confusing to the user.
**Why it happens:** Counter was incremented per token, not per unique market.
**How to avoid:** In the cleanup plan, fix the counter to track unique markets using a `set()` of `market.condition_id` values.

## Code Examples

Verified patterns from codebase inspection:

### Parsing gamma_events tags (confirmed structure from Phase 15 Summary)
```python
# Source: src/gamma/resolution.py (analogous JSON parsing pattern)
import json
from loguru import logger

tags_raw = event.tags  # e.g., '[{"id": 64, "slug": "esports", "label": "eSports"}, ...]'
try:
    tags = json.loads(tags_raw) if tags_raw else []
except (json.JSONDecodeError, TypeError) as e:
    logger.warning(f"Event {event.event_id}: tags JSON parse error: {e}")
    tags = []
```

### Bulk UPDATE via text() with executemany
```python
# Source: src/gamma/persist.py upsert pattern + src/gamma/resolution.py bulk pattern
from sqlalchemy import text

session.execute(
    text("""
        UPDATE token_catalog
        SET node_path = :node_path,
            depth = :depth
        WHERE token_id = :token_id
          AND niche_slug = 'esports'
          AND (depth IS NULL OR depth < :depth)
    """),
    [
        {"token_id": "tok_a", "node_path": "esports/cs2", "depth": 1},
        {"token_id": "tok_b", "node_path": "esports/cs2/iem-katowice", "depth": 2},
    ],
)
session.commit()
```

### Querying gamma_events with SQLAlchemy ORM
```python
# Source: src/gamma/resolution.py (identical pattern)
from src.db.models import GammaEvent

events = session.query(GammaEvent).all()
logger.info(f"Processing {len(events)} gamma events")
```

### In-memory SQLite test for idempotency (replaces mock-based test)
```python
# Source: tests/test_gamma_resolution.py existing pattern + pattern from tests/test_catalog_builder.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, GammaEvent, TokenCatalog
import json

@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_idempotent_classify_tokens(in_memory_db):
    session = in_memory_db
    # Insert real GammaEvent row
    event = GammaEvent(
        event_id="evt_1",
        tags=json.dumps([{"id": 64, "slug": "esports"}, {"id": 1, "slug": "cs2"}]),
        clob_token_ids=json.dumps(["tok_a"]),
    )
    session.add(event)
    # Insert token_catalog row to update
    from sqlalchemy import text
    session.execute(text(
        "INSERT INTO token_catalog (token_id, condition_id, question, niche_slug) "
        "VALUES ('tok_a', 'cond_1', 'Test?', 'esports')"
    ))
    session.commit()

    from src.gamma.classification import classify_tokens_from_gamma_events
    result1 = classify_tokens_from_gamma_events(session)
    result2 = classify_tokens_from_gamma_events(session)

    # Verify idempotency: same classification on second run
    catalog_row = session.query(TokenCatalog).filter_by(token_id="tok_a").first()
    assert catalog_row.node_path == "esports/cs2"
    assert catalog_row.depth == 1
    assert result1["classified"] == result2["classified"]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pattern-based classification from JBecker parquet question titles | Gamma tag-based classification (authoritative, no regex) | Phase 13 replaced the PatternMatcher-based builder | Node_path now from authoritative source, not heuristic regex |
| token_catalog built from JBecker parquet (41 files) | token_catalog built from Gamma API events via TokenCatalogBuilder | Phase 13 rewrite | Simpler pipeline, no DuckDB dependency for classification |
| `classify_token_outcome()` called in resolution | Logic inlined in `resolve_market_outcomes()` | Phase 16 implementation | Dead code — needs cleanup |

**Current state of token_catalog:**
- 817k rows, `niche_slug='esports'` for all esports tokens
- `node_path=NULL`, `depth=NULL` for all rows — classification stuck at root
- `token_id` is primary key, values are Polymarket token IDs from JBecker parquet OR Gamma API

**Critical note on token_catalog population:** The current `TokenCatalogBuilder` (in `src/catalog/builder.py`) fetches from the Gamma API. The Phase 13 tests still mock the JBecker parquet path (old implementation). The actual production catalog comes from Gamma API events — all 817k rows have `niche_slug='esports'` but no `node_path`. This means `gamma_events.clob_token_ids` and `token_catalog.token_id` should have high overlap since both came from the Gamma API (though the catalog builder fetches both active and closed, while Phase 15 only fetches closed events).

## Open Questions

1. **Tag ordering convention in Gamma events**
   - What we know: Phase 15 Summary shows one event with tags `[{"id": 64, "slug": "esports"}, ...]`. The first non-esports tag should be the game, but this is confirmed for only one sample.
   - What's unclear: Whether all Gamma eSports events consistently order tags as [root, game, tournament, team]. The Gamma API documentation is not publicly available.
   - Recommendation: Before writing the final implementation, inspect 10-20 actual `gamma_events` rows (after phases 15+16 have been run in the actual DB) to confirm ordering. Alternatively, check the Gamma API live: `curl "https://gamma-api.polymarket.com/events?active=false&tag_id=64&limit=5"` and inspect the tags array.
   - If ordering is inconsistent: Use tag `id` values to determine level (tag id=64 is always the root eSports tag; if other tag IDs are stable for game/tournament/team levels, use those). This requires inspecting multiple events to discover the ID patterns.

2. **Token coverage gap between token_catalog and gamma_events**
   - What we know: `token_catalog` was built by `TokenCatalogBuilder` which fetches both active and closed eSports events from the Gamma API. Phase 15 only ingested 8,519 closed events into `gamma_events`. Active events were not ingested.
   - What's unclear: What percentage of `token_catalog` token_ids appear in `gamma_events.clob_token_ids`? If coverage is low (e.g., <50%), many tokens will remain NULL after classification.
   - Recommendation: The classify-tokens command should report `classified` (token updates sent) vs. the total eSports tokens in `token_catalog`. Accept low coverage gracefully — remaining NULL tokens are either from active events (not in gamma_events) or from events without sub-classification tags.

3. **Handling tokens in multiple events with different depths**
   - What we know: A token ID theoretically corresponds to one market, but the gamma_events table may have the same token_id appear across events due to how they were ingested.
   - What's unclear: Whether the `WHERE depth IS NULL OR depth < :depth` guard is sufficient, or whether multiple events covering the same token would conflict.
   - Recommendation: Use the "only update if new depth is deeper" guard. Accept last-writer-wins for same-depth conflicts since this is extremely rare.

## Sources

### Primary (HIGH confidence)
- `src/db/models.py` (lines 347-393) — TokenCatalog schema + GammaEvent schema confirmed by direct code read
- `src/gamma/resolution.py` — Exact pattern for iterating gamma_events and doing bulk SQL updates
- `src/gamma/persist.py` — Confirmed tags stored as JSON array with `{"id": ..., "slug": ..., "label": ...}` per tag
- `src/catalog/builder.py` — Confirmed `node_path=None, depth=None` for all token_catalog rows as built
- `.planning/phases/15-gamma-events-ingestion/15-01-SUMMARY.md` — Confirmed tag structure: `tags[]` = array of tag objects with `slug`, `id`, `label`
- `.planning/phases/15-gamma-events-ingestion/15-02-SUMMARY.md` — Confirmed actual sample: `tags: [{"id": 64, "slug": "esports", "label": "eSports"}, ...]`
- `.planning/phases/16-market-outcome-resolution/16-02-SUMMARY.md` — Confirmed 8,519 events ingested with outcome_prices fixed; token counts

### Secondary (MEDIUM confidence)
- Analysis of `src/pipeline/scoring_pipeline.py` and `src/pipeline/queries.py` — Confirmed how `node_path` and `depth` from `token_catalog` feed into multi-depth expertise scoring (indirectly via `MarketClassification` and `TaxonomyNode`, not directly — the token_catalog entries need to map to market_classifications which then join to taxonomy nodes)
- `tests/test_gamma_resolution.py` — Confirmed test patterns (mock session, then in-memory DB) for idempotency fix

### Tertiary (LOW confidence)
- Assumed tag ordering (game before tournament before team) based on single sample — NOT verified across multiple events. Flagged as open question.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are existing project dependencies
- Architecture patterns: HIGH — directly mirrors resolution.py (Phase 16) which is proven and working
- Tag structure: MEDIUM — confirmed structure from one sample, but ordering across events not verified
- Pitfalls: HIGH — derived from direct code analysis of existing patterns
- Code quality issues: HIGH — bugs confirmed by direct code + test reading

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable internal codebase — no external dependencies changing)

---

## Planning Notes (for gsd-planner)

### Recommended Plan Structure: 2 plans

**Plan 17-01 (Wave 1): Token classification logic — TDD**
- New file: `src/gamma/classification.py` with `classify_tokens_from_gamma_events()` and `_extract_classification()`
- New file: `tests/test_gamma_classification.py` with TDD test suite
- CLI command: `polymarket classify-tokens` wired to classification logic
- Requirements: CLASS-01, CLASS-02
- Type: tdd
- Files modified: `src/gamma/classification.py` (NEW), `tests/test_gamma_classification.py` (NEW), `src/cli/commands.py` (add command)

**Plan 17-02 (Wave 1, parallel): Code quality cleanup**
- Fix `resolved` counter → track unique markets via set (resolution.py)
- Remove or integrate `classify_token_outcome()` into `resolve_market_outcomes()` (resolution.py)
- Replace weak mock-based idempotency test with in-memory SQLite test (test_gamma_resolution.py)
- Requirements: none (code quality only)
- Type: execute
- Files modified: `src/gamma/resolution.py`, `tests/test_gamma_resolution.py`

Plans 17-01 and 17-02 are fully independent (different files) and can run in parallel (Wave 1 both).

### Key Implementation Detail: node_path Format

The `token_catalog` column `node_path` is `String(300)`. The existing PatternMatcher produces paths like `"eSports.CS2.IEM Katowice"` (dot-separated, mixed case). The Gamma tags will produce slugs like `"esports/cs2/iem-katowice-2024"` (slash-separated, lowercase). The planner must decide which format to use for Phase 17.

**Recommendation:** Use slash-separated lowercase (matching Gamma slugs directly) since:
1. All existing `token_catalog.node_path` values are currently NULL — no legacy format to match
2. The scoring pipeline queries `token_catalog` indirectly (not directly by node_path) — the scoring pipeline joins through `MarketClassification.node_path` which uses dot-separated format from PatternMatcher

**Important:** The scoring pipeline (`scoring_pipeline.py`, `queries.py`) does NOT query `token_catalog.node_path` directly. It queries `TaxonomyNode.slug` via `MarketClassification`. The `token_catalog` is only used during JBecker backfill ingest to route trades to the right niche. So the format of `token_catalog.node_path` is semi-independent from the TaxonomyNode slug format.

However, to maintain consistency with the existing `MarketClassification.node_path` format (dot-separated, e.g., `"eSports.CS2.IEM Katowice"`), and to future-proof the field, it may be better to convert Gamma slugs to a consistent format. The planner should choose ONE format and document it clearly.

### Verifiability Requirement

Success criterion 4 states: "Classification is verifiable — user can query a known token ID and see its resolved node_path and depth." The CLI command `polymarket classify-tokens` should print a summary (N tokens updated). For spot verification, the user can run:
```sql
SELECT token_id, node_path, depth FROM token_catalog WHERE node_path IS NOT NULL LIMIT 10;
```
This requires the CLI to not crash and produce non-zero output.
