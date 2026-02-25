# Phase 18: End-to-End Validation - Research

**Researched:** 2026-02-25
**Domain:** Pipeline integration debugging — connecting market resolution, token classification, and scoring
**Confidence:** HIGH (full codebase read, data flow traced end-to-end)

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| E2E-01 | `score` command produces non-empty expertise scores on JBecker data after Gamma ingestion | Identified two blocking gaps: (1) Position.resolved never set; (2) get_all_game_slugs_with_positions returns empty because taxonomy_node_id is NULL in MarketClassification rows created post-backfill |
| E2E-02 | Leaderboard shows correctly scored traders with win rates calculated from resolved outcomes | Depends on E2E-01 being solved first; win rate requires Position.outcome="win"/"loss" which also needs the position resolver step |
</phase_requirements>

---

## Summary

Phase 18 is a diagnostic-then-fix phase. The scoring pipeline has always produced empty output because two gaps exist in the data pipeline that were not fixed by Phases 16 and 17. This research traces each gap precisely to pinpoint the fixes needed.

**Gap 1 — Position rows are never resolved.** The `score` command calls `compute_all_game_scores()`, which filters positions with `p.resolved and p.outcome != "void"`. The `Position` model has `resolved: bool = False` (default) and `outcome: str | None = None`. There is no code anywhere in `src/` that sets `position.resolved = True` or `position.outcome = "win"/"loss"`. The function `calculate_pnl()` in `src/discovery/position_tracker.py` has the logic to compute these values, but it is never called to update existing `Position` rows. Phase 16 populated `Market.outcome` (with "YES"/"NO") but did not propagate that into the `Position` table.

**Gap 2 — `get_all_game_slugs_with_positions` may return nothing.** This function queries `TaxonomyNode WHERE node_type = "game"` joined through `MarketClassification.taxonomy_node_id`. During JBecker backfill (`ingest_trader_history_jbecker`), `MarketClassification` rows are created, and `taxonomy_node_id` is populated from `token_catalog.node_path` — but only if `token_catalog.node_path` was already populated at ingest time. For tokens where `node_path` was NULL at backfill time (before Phase 17), the `MarketClassification.taxonomy_node_id` remains NULL even after Phase 17 classifies the `token_catalog`. This is a forward-only population problem: Phase 17 updates `token_catalog` but does not backfill the already-existing NULL `MarketClassification.taxonomy_node_id` rows.

**Primary recommendation:** Phase 18 needs two tasks: (1) a `resolve-positions` step that joins `Position` + `Market.outcome` to populate `Position.resolved`, `Position.outcome`, and `Position.pnl`; (2) a `backfill-market-classifications` step that updates `MarketClassification.taxonomy_node_id` for rows that have a non-NULL `node_path` in `token_catalog` but NULL `taxonomy_node_id`. Then run `score` and verify the leaderboard is non-empty.

---

## Standard Stack

This phase uses only the existing project stack — no new libraries required.

### Core
| Component | Module | Purpose | Notes |
|-----------|--------|---------|-------|
| SQLAlchemy ORM | `src/db/models.py` | Position, Market, MarketClassification, TaxonomyNode | Already in use |
| `calculate_pnl()` | `src/discovery/position_tracker.py` | Converts Market.outcome + Position direction/size → win/loss/pnl | Already exists, just not called at pipeline time |
| `resolve_market_outcomes()` | `src/gamma/resolution.py` | Sets Market.outcome (Phase 16) | Already complete |
| `classify_tokens_from_gamma_events()` | `src/gamma/classification.py` | Sets token_catalog.node_path/depth (Phase 17) | Already complete |
| `compute_all_game_scores()` | `src/pipeline/scoring_pipeline.py` | Scoring entry point | Already exists |
| Click CLI | `src/cli/commands.py` | CLI command registration | Already in use |

### Supporting
| Component | Module | Purpose | Notes |
|-----------|--------|---------|-------|
| SQLite raw SQL | `sqlalchemy.text()` | Batch UPDATE statements | Used in Phase 17 classify |
| pytest + SQLite in-memory | `tests/` | TDD verification | Standard pattern in project |
| loguru | project-wide | Progress logging | Standard pattern in project |

---

## Architecture Patterns

### Pattern 1: Position Resolver

**What:** A function `resolve_positions(session)` that joins `Position` → `Market` on `Position.market_id == Market.condition_id`, filters markets where `Market.outcome IS NOT NULL`, and for each such position calls `calculate_pnl()` to compute `outcome` and `pnl`, then sets `position.resolved = True`.

**Key detail:** `Market.outcome` is "YES" or "NO" (set by Phase 16). `calculate_pnl()` expects `market_outcome` as "YES", "NO", or "VOID". So the resolver calls `calculate_pnl(position_data, resolution_price, market_outcome)`.

**Problem:** `calculate_pnl()` takes a `PositionData` dataclass (from `position_tracker.py`), not a `Position` ORM object. The resolver needs to either: (a) reconstruct a `PositionData` from the `Position` ORM fields, or (b) use an inline computation directly on the ORM object without converting.

**Resolution price mapping:** Binary Polymarket markets resolve at 1.0 (YES wins) or 0.0 (NO wins). When `market_outcome = "YES"`, the resolution_price is `Decimal("1.0")`. When `market_outcome = "NO"`, resolution_price is `Decimal("0.0")`.

**Win/loss logic for binary positions:**
- LONG + YES → win (pnl = size * (1.0 - avg_entry_price), positive)
- LONG + NO → loss (pnl = size * (0.0 - avg_entry_price), negative)
- SHORT + YES → loss
- SHORT + NO → win

**Where to place:** New function `resolve_positions(session: Session) -> dict[str, int]` in a new module `src/gamma/position_resolver.py` (following the pattern of `src/gamma/resolution.py`). Returns `{"resolved": N, "skipped_no_outcome": M, "skipped_flat": K}`.

**CLI command:** `polymarket resolve-positions` — analogous to `polymarket resolve-outcomes`. Calls `resolve_positions()` then commits.

### Pattern 2: Market Classification Backfill

**What:** After Phase 17 populates `token_catalog.node_path`, existing `MarketClassification` rows that have `taxonomy_node_id IS NULL` need updating. The fix joins `MarketClassification` → `token_catalog` on `market_id = condition_id`, finds rows where `token_catalog.node_path IS NOT NULL` but `MarketClassification.taxonomy_node_id IS NULL`, then looks up the `TaxonomyNode.id` for that slug and updates.

**Where to place:** Can be added to `src/gamma/classification.py` as a second function `backfill_market_classifications(session)`, or added to `src/pipeline/classify.py`. The `classification.py` location is preferred for cohesion with Phase 17 work.

**CLI command:** Either a new `polymarket backfill-classifications` command, or this step can be called automatically after `classify-tokens` (in the same CLI command or as part of the `classify-tokens` command).

**Note:** This may not be the blocking issue if `get_all_game_slugs_with_positions` already returns results from MarketClassification rows created during JBecker backfill (which do attempt to look up `taxonomy_node_id` from `token_catalog.node_path` at ingest time). Must verify with a diagnostic query before assuming this is blocked.

### Pattern 3: Diagnostic-First Approach

**What:** Before writing any fix code, run diagnostic SQL queries against the live DB to confirm exactly what is NULL where. This avoids fixing the wrong thing.

**Queries to run as a diagnostic plan:**

```python
# Query 1: How many positions exist, and how many are resolved?
SELECT COUNT(*) as total, SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved_count
FROM positions;

# Query 2: How many markets have outcome set?
SELECT COUNT(*) as total,
       SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as has_outcome
FROM markets;

# Query 3: How many MarketClassification rows have taxonomy_node_id NULL?
SELECT COUNT(*) as total,
       SUM(CASE WHEN taxonomy_node_id IS NULL THEN 1 ELSE 0 END) as null_node
FROM market_classifications;

# Query 4: What does get_all_game_slugs_with_positions return?
SELECT tn.slug
FROM taxonomy_nodes tn
JOIN market_classifications mc ON mc.taxonomy_node_id = tn.id
JOIN positions p ON p.market_id = mc.market_id
WHERE tn.node_type = 'game'
GROUP BY tn.slug;

# Query 5: For known trader @Xero100i, what positions exist?
SELECT p.market_id, p.resolved, p.outcome, p.pnl, m.outcome as market_outcome
FROM positions p
JOIN markets m ON p.market_id = m.condition_id
WHERE p.trader_address = '0xeffd76b6a4318d50c6f71a16b276c5b279445a86'
LIMIT 20;

# Query 6: token_catalog coverage for resolved markets
SELECT COUNT(*) as total_tc,
       SUM(CASE WHEN node_path IS NOT NULL THEN 1 ELSE 0 END) as classified
FROM token_catalog
WHERE niche_slug = 'esports';
```

### Recommended Plan Structure

Given the diagnostic-first approach, Phase 18 should have 2 plans:

**Plan 18-01 — Diagnostic + Position Resolver**
- Diagnostic script that queries the DB and prints state
- `resolve_positions()` in `src/gamma/position_resolver.py` (TDD)
- `polymarket resolve-positions` CLI command
- Run command and verify positions get resolved=True, outcome=win/loss

**Plan 18-02 — Classification Backfill + E2E Verification**
- `backfill_market_classifications()` (if diagnostic shows it's needed)
- Run `polymarket score` and verify non-empty output
- Run `polymarket leaderboard esports.cs2` and verify @Xero100i appears
- Acceptance test: at least one trader with `resolved_market_count >= 5` in output

### Anti-Patterns to Avoid

- **Skipping the diagnostic step:** Directly writing code without first confirming which gaps actually exist in the live DB will risk fixing the wrong thing.
- **Using `calculate_pnl()` with wrong resolution price:** Binary markets resolve at 1.0 (YES wins) or 0.0 (NO wins). Don't pass `0.5` or the token price.
- **Session commit inside library functions:** The project convention (established in Phase 17 code review) is that library functions like `resolve_positions()` should NOT call `session.commit()` internally. The CLI command handles the commit.
- **Touching scoring_pipeline.py first:** The scoring pipeline code is correct. The failure is in missing data, not in the scoring logic itself.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PnL calculation | Custom win/loss logic | `calculate_pnl()` from `src/discovery/position_tracker.py` | Already handles LONG/SHORT, edge cases, FLAT/VOID |
| Batch SQL updates | Row-by-row ORM updates | `session.execute(text(...), params_list)` | Same pattern used in Phase 17's classify; much faster |
| Resolution price lookup | API call or complex query | Simple mapping: YES→1.0, NO→0.0, VOID→0.0 | Binary Polymarket markets resolve at 0 or 1 |

**Key insight:** All needed logic already exists — this phase is about wiring, not new functionality.

---

## Common Pitfalls

### Pitfall 1: Assuming Phase 16 fixed scoring
**What goes wrong:** Phase 16 set `Market.outcome` to "YES"/"NO". This is NOT the same as `Position.outcome` ("win"/"loss"). The scoring pipeline reads `Position.resolved` and `Position.outcome`, not `Market.outcome`. The fix bridge (`resolve_positions`) was intentionally deferred to Phase 18.
**How to avoid:** Always distinguish `Market.outcome` ("YES"/"NO") from `Position.outcome` ("win"/"loss"/"void"/"flat") and `Position.resolved` (bool).

### Pitfall 2: `calculate_pnl()` takes PositionData, not Position ORM
**What goes wrong:** `calculate_pnl()` accepts a `PositionData` dataclass (from `position_tracker.py`). A `Position` ORM object has different field names and types.
**How to avoid:** In `resolve_positions()`, either (a) construct a minimal `PositionData` from ORM fields, or (b) inline the calculation directly. The inline approach is simpler and avoids an unnecessary dataclass conversion. The math is just 3 lines.

### Pitfall 3: FLAT positions cause scoring to fail
**What goes wrong:** `Position.direction = "FLAT"` means the trader fully closed before resolution. `calculate_pnl()` returns `outcome="flat"` for these. The scoring pipeline filters `p.outcome != "void"` but FLAT positions that get `outcome="flat"` will also be excluded from `resolved_positions` (the filter is `p.resolved and p.outcome != "void"` — flat is not void, so they would be included in the resolved count but contribute 0 to win rate).
**How to avoid:** Handle FLAT positions correctly in `resolve_positions()` — they should set `resolved=True, outcome="flat", pnl=0`. This is handled by `calculate_pnl()` already.

### Pitfall 4: MarketClassification.taxonomy_node_id still NULL after Phase 17
**What goes wrong:** Phase 17 updated `token_catalog.node_path`, but `MarketClassification.taxonomy_node_id` is populated at JBecker ingest time from the then-current `token_catalog`. Tokens that were `node_path=NULL` at backfill time have `NULL` taxonomy_node_id in MarketClassification even after Phase 17.
**Warning signs:** `get_all_game_slugs_with_positions()` returns an empty list despite positions existing. Run diagnostic Query 4 above first.

### Pitfall 5: Minimum 5 resolved markets filter
**What goes wrong:** The scoring pipeline skips traders with fewer than 5 resolved positions (`MIN_RESOLVED_MARKETS = 5`). Even after fixing `Position.resolved`, if a trader has fewer than 5 resolved eSports positions, they will not appear in the leaderboard.
**How to avoid:** Use the known trader @Xero100i (2,024 trades from Graph) as the verification target — this trader should easily pass the 5-resolved-markets threshold if the data pipeline is complete. If verification still fails, check why this specific trader has fewer than 5 resolved positions.

### Pitfall 6: Position rows may not exist at all
**What goes wrong:** `Position` rows are created by `compute_and_store_positions()` in `trader_discovery.py`, which must be called explicitly. This is called from the `score` command's `refresh_all_positions` — but ONLY if positions don't exist yet. If the `backfill` command ran but `score` was never run, positions might not exist.
**How to avoid:** Run diagnostic Query 1. If total positions = 0, the issue is that positions need to be computed from trades first (via `discover_esports_traders` → `compute_and_store_positions`). This is pre-existing functionality — check if it runs correctly as part of `score` or if it must be called separately.

---

## Code Examples

### Inline PnL calculation for Position resolver

```python
# Source: src/discovery/position_tracker.py - calculate_pnl() logic
# Used in src/gamma/position_resolver.py

def resolve_positions(session: Session) -> dict[str, int]:
    """Populate Position.resolved, Position.outcome, Position.pnl
    for all positions on markets with a known outcome.

    Caller must commit after this returns.
    """
    resolved = 0
    skipped_no_outcome = 0
    skipped_flat = 0

    positions = (
        session.query(Position)
        .join(Market, Position.market_id == Market.condition_id)
        .filter(Market.outcome.is_not(None))
        .filter(Position.resolved == False)  # idempotency: skip already-resolved
        .all()
    )

    for position in positions:
        market = session.query(Market).filter_by(
            condition_id=position.market_id
        ).first()
        if market is None or market.outcome is None:
            skipped_no_outcome += 1
            continue

        market_outcome = market.outcome  # "YES" or "NO"

        # Binary markets: YES=1.0, NO=0.0
        if market_outcome == "YES":
            resolution_price = Decimal("1.0")
        elif market_outcome == "NO":
            resolution_price = Decimal("0.0")
        else:
            # VOID or unexpected
            position.resolved = True
            position.outcome = "void"
            position.pnl = Decimal("0")
            resolved += 1
            continue

        # FLAT position (fully closed before resolution)
        if position.size == Decimal("0") or position.direction == "FLAT":
            position.resolved = True
            position.outcome = "flat"
            position.pnl = Decimal("0")
            skipped_flat += 1
            continue

        # Calculate PnL
        if position.direction == "LONG":
            if position.avg_entry_price is not None:
                pnl = position.size * (resolution_price - position.avg_entry_price)
            else:
                pnl = Decimal("0")
        else:  # SHORT
            if position.avg_entry_price is not None:
                pnl = abs(position.size) * (position.avg_entry_price - resolution_price)
            else:
                pnl = Decimal("0")

        outcome = "win" if pnl > Decimal("0") else "loss" if pnl < Decimal("0") else "flat"

        position.resolved = True
        position.outcome = outcome
        position.pnl = pnl
        resolved += 1

    logger.info(f"Position resolution: {resolved} resolved, {skipped_no_outcome} no outcome, {skipped_flat} flat")
    return {"resolved": resolved, "skipped_no_outcome": skipped_no_outcome, "skipped_flat": skipped_flat}
```

### Market classification backfill

```python
# Source: pattern from src/gamma/classification.py (Phase 17)
# Used in src/gamma/classification.py as a new function

def backfill_market_classifications(session: Session) -> dict[str, int]:
    """Update MarketClassification.taxonomy_node_id for rows that have
    a matching token_catalog entry with node_path but NULL taxonomy_node_id.

    Caller must commit after this returns.
    """
    updated = 0
    skipped_no_node = 0

    # Find MarketClassification rows with NULL taxonomy_node_id
    # that have a token_catalog entry with a node_path
    rows = (
        session.query(MarketClassification, TokenCatalog)
        .join(TokenCatalog, MarketClassification.market_id == TokenCatalog.condition_id)
        .filter(MarketClassification.taxonomy_node_id.is_(None))
        .filter(TokenCatalog.node_path.is_not(None))
        .all()
    )

    for mc, tc in rows:
        # Convert node_path (e.g., "esports/cs2") to TaxonomyNode slug format
        # node_path uses "/" separator; slug uses "." separator
        slug = tc.node_path.replace("/", ".")
        node = session.query(TaxonomyNode).filter_by(slug=slug).first()
        if node:
            mc.taxonomy_node_id = node.id
            mc.node_path = tc.node_path
            updated += 1
        else:
            skipped_no_node += 1

    logger.info(f"Classification backfill: {updated} updated, {skipped_no_node} no matching node")
    return {"updated": updated, "skipped_no_node": skipped_no_node}
```

**Warning:** The `node_path` format in `token_catalog` uses "/" (e.g., `esports/cs2`) as set by `_extract_classification()` in `classification.py`. The `TaxonomyNode.slug` uses "." (e.g., `esports.cs2`). The conversion is `node_path.replace("/", ".")`. Verify this before implementing.

### Diagnostic SQL queries

```python
# Run before writing any fix code
from sqlalchemy import text

with get_session(session_factory) as session:
    # Gap 1: positions resolved?
    result = session.execute(text(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved "
        "FROM positions"
    )).fetchone()
    print(f"Positions: {result.total} total, {result.resolved} resolved")

    # Gap 2: game slugs from scoring pipeline
    result = session.execute(text(
        "SELECT tn.slug FROM taxonomy_nodes tn "
        "JOIN market_classifications mc ON mc.taxonomy_node_id = tn.id "
        "JOIN positions p ON p.market_id = mc.market_id "
        "WHERE tn.node_type = 'game' GROUP BY tn.slug"
    )).fetchall()
    print(f"Game slugs with positions: {[r[0] for r in result]}")

    # Known trader check
    result = session.execute(text(
        "SELECT COUNT(*) as pos_count, "
        "SUM(CASE WHEN p.resolved THEN 1 ELSE 0 END) as resolved "
        "FROM positions p "
        "WHERE p.trader_address = '0xeffd76b6a4318d50c6f71a16b276c5b279445a86'"
    )).fetchone()
    print(f"Xero100i: {result.pos_count} positions, {result.resolved} resolved")
```

---

## Data Flow Diagram

```
JBecker parquet
    ↓ backfill command
Trade rows (market_id=condition_id, trader_address, side, size, price)
    ↓ compute_and_store_positions() [trader_discovery.py]
Position rows (resolved=False, outcome=NULL, pnl=NULL)
    ↓ [MISSING STEP — Phase 18 adds this]
    ↓ resolve_positions() using Market.outcome
Position rows (resolved=True, outcome="win"/"loss"/"flat", pnl=calculated)
    ↓ compute_all_game_scores() [scoring_pipeline.py]
ExpertiseScore rows → Leaderboard

===

token_catalog (token_id, condition_id, node_path, depth)
    ↓ Phase 17: classify-tokens populates node_path/depth
    ↓ [POTENTIALLY MISSING STEP — Phase 18 may add this]
    ↓ backfill_market_classifications()
MarketClassification (market_id, taxonomy_node_id→TaxonomyNode)
    ↑ required by get_all_game_slugs_with_positions()
    ↑ required by get_positions_for_game()
```

---

## State of the Art

| Old State | Current State | Changed | Impact |
|-----------|--------------|---------|--------|
| markets.outcome = NULL for all | markets.outcome = YES/NO for ~10,797 markets | Phase 16 | Enables position resolution |
| token_catalog.node_path = NULL | token_catalog.node_path populated (esports/cs2/...) for ~8,519 events worth of tokens | Phase 17 | Enables MarketClassification backfill |
| Position.resolved = False everywhere | Still False — Phase 18 fixes this | Phase 18 target | Unblocks scoring pipeline |
| get_all_game_slugs_with_positions() returns [] | Unknown — diagnostic will confirm | Phase 18 diagnostic | May require classification backfill |

---

## Open Questions

1. **Do Position rows exist at all for JBecker traders?**
   - What we know: `compute_and_store_positions()` must be called explicitly
   - What's unclear: Whether the scoring pipeline calls it, or if it only reads existing Position rows
   - Recommendation: Run diagnostic Query 1. If `SELECT COUNT(*) FROM positions` returns 0, need to understand when positions get created (likely by the `score` command's call chain, or a separate step).

2. **Does `backfill_market_classifications` actually use "/" or "." in node_path?**
   - What we know: `_extract_classification()` builds node_path as `"/".join(path_parts)`, so format is `esports/cs2`
   - What's unclear: Whether the slug format in TaxonomyNode uses `esports.cs2` or `esports/cs2`
   - Recommendation: Verify from `sync_taxonomy_to_db()` in `classify.py` — it builds slugs as `f"{root_slug}.{game.name.lower()}"`, so TaxonomyNode slugs use "." separator. Conversion needed.

3. **Will the leaderboard be non-empty after fixing position resolver alone?**
   - What we know: `get_all_game_slugs_with_positions()` requires non-NULL `taxonomy_node_id` in MarketClassification. Phase 17 may have fixed this implicitly if those rows were created during a post-Phase-17 backfill.
   - What's unclear: Whether any traders were backfilled after Phase 17 (which would have correct taxonomy_node_id) vs. before (which would have NULL taxonomy_node_id).
   - Recommendation: Run diagnostic Query 4 first. If it returns game slugs, Gap 2 is resolved and only Gap 1 (position resolver) needs fixing.

---

## Sources

### Primary (HIGH confidence)
- Direct source code inspection: `src/pipeline/scoring_pipeline.py` — full read, verified filtering logic
- Direct source code inspection: `src/pipeline/queries.py` — `get_all_game_slugs_with_positions()` verified
- Direct source code inspection: `src/discovery/position_tracker.py` — `calculate_pnl()` verified
- Direct source code inspection: `src/pipeline/ingest.py` lines 1630-1660 — MarketClassification creation during JBecker backfill verified
- Direct source code inspection: `src/gamma/classification.py` — `_extract_classification()` slash separator verified
- Direct source code inspection: `src/pipeline/classify.py` — `sync_taxonomy_to_db()` dot separator verified
- Phase 16 SUMMARY: 10,797 markets resolved in DB (3,648 YES + 7,149 NO)
- Phase 17 SUMMARY: token_catalog.node_path populated for esports tokens

### Secondary (MEDIUM confidence)
- Grep across all src/*.py files confirms `Position.resolved = True` is set NOWHERE (0 matches)
- Grep confirms `calculate_pnl()` is only defined in `position_tracker.py`, never called on ORM objects

---

## Metadata

**Confidence breakdown:**
- Gap identification: HIGH — code proves no Position.resolved setter exists
- Architecture (resolver pattern): HIGH — follows existing Phase 16 resolution.py pattern
- Classification backfill need: MEDIUM — requires diagnostic to confirm (may be pre-existing or resolved)
- Minimum trader data availability: MEDIUM — @Xero100i has 2,024+ trades in JBecker, but whether positions computed and whether 5+ resolve is unknown until diagnostic runs

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable codebase, no external dependencies)
