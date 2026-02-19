# Phase 13: Esports Token Catalog & JBecker Classification - Research

**Researched:** 2026-02-19
**Domain:** JBecker parquet catalog build, SQLite schema extension, backfill integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Catalog storage**
- SQLite table in `polymarket.db` (not DuckDB runtime, not JSON file)
- Explicit SQLite chosen for debuggability
- Use DuckDB to scan the JBecker markets parquet and write results into the SQLite table (one-time build)

**Catalog schema**
- Store ALL markets from JBecker (not just esports) — architecture prototype for future niche expansion
- Schema: `token_id, condition_id, question, niche_slug, node_path, depth, market_type`
  - `niche_slug`: matched niche string (e.g., "esports", null for unmatched) — extensible
  - `node_path`: full taxonomy path (e.g., "eSports.CS2.IEM Katowice") — instant lookup
  - `depth`: taxonomy depth (1=game, 2=tournament, 3=team, null for unmatched)
  - `market_type`: "match" or "prop" for esports, null otherwise

**Catalog build trigger**
- Auto-built during backfill if catalog table is empty or missing
- Fully invisible to user — no manual step
- Build is one-time scan of 41 markets parquet files
- Rebuildable when taxonomy patterns update

**Trade classification during backfill**
- Look up maker_asset_id / taker_asset_id in catalog
- If esports match: create Market + MarketClassification records, ingest normally
- If not in catalog: skip trade, log warning

**Live pipeline integration**
- No schema changes to Trade, Market, or MarketClassification tables
- JBecker trades flow through existing scoring pipeline unchanged after Market records created

**CLI**
- Add `polymarket catalog-stats` command

### Claude's Discretion
- niche_slug format convention
- Scoring re-run timing after backfill
- Batch size for catalog build
- Index strategy on token_catalog table

### Deferred Ideas (OUT OF SCOPE)
- Discovering new traders from JBecker market trades (deferred — separate project)
</user_constraints>

---

## Summary

Phase 13 builds a token catalog that bridges JBecker trade data (which references numeric token IDs) to the existing taxonomy classification system (which operates on market question text). The catalog is a single SQLite table — `token_catalog` — that explodes each JBecker market's `clob_token_ids` JSON array into one row per token, then stores the PatternMatcher classification result alongside it.

The JBecker markets parquet holds 408,863 markets across 41 files. DuckDB scans all 41 files in under 1 second, producing 817,683 token rows (2 tokens per market: YES + NO). Running `PatternMatcher.classify()` on all 408,863 questions takes approximately 15 seconds in Python. Writing 817,683 rows to SQLite in a single transaction takes ~8 seconds. Total first-run catalog build time: approximately 25 seconds end-to-end. This is acceptable for a one-time build that is transparent to the user.

The backfill integration is a targeted addition to `ingest_trader_history_jbecker()`. When a JBecker trade's token ID resolves to a catalog entry with `niche_slug='esports'`, the pipeline creates a `Market` record and a `MarketClassification` record for that condition_id if they do not already exist. Trades then flow into the `trades` table unchanged via the existing routing logic. No Trade, Market, or MarketClassification schema changes are required.

**Primary recommendation:** New module `src/catalog/builder.py` owns catalog build logic. Modify `ingest_trader_history_jbecker()` in `src/pipeline/ingest.py` to consult the catalog as a pre-step to the existing Gamma API token lookup fallback.

---

## Standard Stack

### Core (all already in requirements)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| duckdb | installed | Scan JBecker markets parquet | Already used in JBeckerDataset; 0.5s to read 408k markets |
| sqlalchemy | 2.0.46 | ORM for token_catalog table | Project standard; `Base.metadata.create_all` is idempotent |
| sqlite3 | stdlib | Direct bulk insert via `executemany` | 7.6s single-transaction write of 817k rows |
| src.taxonomy.classifier | local | PatternMatcher classification | Exact same classifier already used in classify.py |

### No New Dependencies Required

The entire phase is implemented using already-installed libraries. DuckDB reads the parquet; Python classifies with PatternMatcher; SQLAlchemy defines the ORM model; raw sqlite3 `executemany` handles bulk insert.

**Installation:** None needed.

---

## Architecture Patterns

### Recommended New Files

```
src/
├── catalog/
│   ├── __init__.py
│   └── builder.py          # TokenCatalogBuilder class
```

Modifications to existing files:
```
src/db/models.py             # Add TokenCatalog ORM model
src/pipeline/ingest.py       # Modify ingest_trader_history_jbecker()
src/cli/commands.py          # Add catalog-stats command
```

### Pattern 1: TokenCatalog ORM Model

Add to `src/db/models.py` following the existing pattern:

```python
class TokenCatalog(Base):
    """Maps JBecker clob_token_ids to taxonomy classification.

    One row per token (YES or NO) per market. ALL 408k JBecker markets
    are stored regardless of niche — null niche_slug means unmatched.
    Built once from JBecker markets parquet; rebuilt when taxonomy updates.
    """

    __tablename__ = "token_catalog"

    token_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    condition_id: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    niche_slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    node_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    depth: Mapped[int | None] = mapped_column(nullable=True)
    market_type: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        Index("ix_catalog_condition", "condition_id"),
        Index("ix_catalog_niche", "niche_slug"),
    )
```

**Why no `created_at`:** The catalog is rebuilt atomically; row timestamps add no value.

### Pattern 2: TokenCatalogBuilder

```python
# src/catalog/builder.py
class TokenCatalogBuilder:
    """Builds token_catalog from JBecker markets parquet.

    One-time build: ~25 seconds for 408k markets / 817k tokens.
    Idempotent: INSERT OR IGNORE skips rows already present.
    """

    def __init__(self, markets_path: str, taxonomy_path: Path, db_url: str):
        self.markets_path = markets_path  # e.g. "./data"
        self.taxonomy_path = taxonomy_path
        self.db_url = db_url

    def is_built(self, session) -> bool:
        """Return True if token_catalog has at least one row."""
        from src.db.models import TokenCatalog
        return session.query(TokenCatalog).first() is not None

    def build(self, session) -> dict:
        """Scan markets parquet, classify, write catalog. Returns stats dict."""
        ...
```

### Pattern 3: Auto-Build Trigger in Backfill

In `ingest_trader_history_jbecker()`, add a catalog check before the existing `_build_token_cache()` call:

```python
# Auto-build catalog if empty (one-time, ~25s)
with self.session_factory() as check_session:
    from src.catalog.builder import TokenCatalogBuilder
    builder = TokenCatalogBuilder(
        markets_path=settings.jbecker_data_path,
        taxonomy_path=Path(settings.taxonomy_path),
        db_url=settings.database_url,
    )
    if not builder.is_built(check_session):
        logger.info("Token catalog empty — building from JBecker markets parquet...")
        stats = builder.build(check_session)
        logger.info(f"Catalog built: {stats['total_rows']} rows, {stats['esports_rows']} esports")
```

### Pattern 4: Catalog Lookup During Backfill

Replace the existing Gamma API unknown-token lookup with catalog lookup as the primary path:

```python
# Current flow in ingest_trader_history_jbecker (simplified):
# 1. Build token_cache from Market.tokens (SQLite)
# 2. For unknown tokens: call Gamma API -> create Market record
# 3. Route trades

# New flow with catalog:
# 1. Build token_cache from Market.tokens (SQLite)  [unchanged]
# 2. For unknown tokens: check token_catalog first  [NEW]
#    a. If catalog hit + niche_slug='esports':
#       - Create Market(condition_id, question, category='eSports')
#       - Create MarketClassification(node_path, market_type, ...)
#       - Add to token_to_condition cache
#    b. If catalog miss: fall through to Gamma API lookup  [existing behavior]
# 3. Route trades  [unchanged]
```

This preserves the Gamma API fallback for tokens not in the JBecker markets parquet (e.g., markets created after the snapshot date).

### Pattern 5: Market + MarketClassification Creation from Catalog

```python
def _create_market_from_catalog(self, session, catalog_entry) -> Market:
    """Create Market record from token_catalog entry (esports only)."""
    market = Market(
        condition_id=catalog_entry.condition_id,
        question=catalog_entry.question,
        category="eSports",
        active=False,   # Historical — activity status unknown
    )
    session.add(market)
    session.flush()  # Get DB id
    return market

def _create_classification_from_catalog(self, session, catalog_entry) -> MarketClassification:
    """Create MarketClassification from token_catalog entry."""
    # Resolve taxonomy_node_id from node_path slug
    node_path_parts = catalog_entry.node_path.split(".")
    slug = ".".join(p.lower() for p in node_path_parts)
    taxonomy_node = session.query(TaxonomyNode).filter_by(slug=slug).first()

    return MarketClassification(
        market_id=catalog_entry.condition_id,
        taxonomy_node_id=taxonomy_node.id if taxonomy_node else None,
        node_path=catalog_entry.node_path,
        market_type=catalog_entry.market_type,
        matched_pattern=None,       # Pattern not stored in catalog
        flagged_for_review=False,
    )
```

### Pattern 6: catalog-stats CLI Command

```python
@cli.command("catalog-stats")
def catalog_stats():
    """Show token catalog statistics.

    Displays total rows, esports coverage, and per-game breakdown.

    Example:
        polymarket catalog-stats
    """
```

### Anti-Patterns to Avoid

- **Using DuckDB ATTACH to write catalog directly:** DuckDB can attach SQLite and write, but it bypasses SQLAlchemy connection events (WAL mode, foreign_keys pragma). Use SQLAlchemy + executemany instead.
- **Classifying inside a DuckDB SQL query:** PatternMatcher is Python regex, not SQL. Must fetch all rows to Python, then classify in a loop.
- **Storing only esports rows:** The decision is ALL markets (817k rows). This enables future niche expansion without rebuilding. Non-esports rows have `niche_slug=NULL`.
- **Calling Gamma API for all unknown tokens before checking catalog:** The catalog covers 100% of JBecker markets by definition. Check catalog first, API only for misses.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reading 41 parquet files | Custom file iteration | `duckdb.execute("read_parquet('*.parquet')")` | DuckDB glob reads all 41 files in 0.5s |
| Idempotent bulk insert | Custom dedup logic | `INSERT OR IGNORE` via `executemany` | SQLite handles constraint violations natively |
| Schema migration for new table | Custom DDL scripts | `Base.metadata.create_all(engine)` | SQLAlchemy creates table if not exists, no-ops if it exists |
| Market classification | Custom regex in catalog builder | `PatternMatcher.classify()` from `src/taxonomy/classifier.py` | Same classifier used everywhere; consistency required |
| JSON parsing of clob_token_ids | Custom parser | `json.loads(clob_json)` + error handling | Standard; already used in existing converters |

**Key insight:** The catalog build is a data pipeline step, not a production query path. Optimize for correctness and rebuild speed, not latency.

---

## Common Pitfalls

### Pitfall 1: PatternMatcher False Positives

**What goes wrong:** The PatternMatcher produces false positives. "Chelsea or Porto win the second leg of their Champions League match?" matches `eSports.Valorant.VCT Champions` because the pattern `\bChampions\b` is too broad. "Who will win the 2022 World Championship chess match?" matches `eSports.League of Legends.World Championship`.

**Why it happens:** Existing taxonomy patterns are designed for eSports market titles. When applied to 408k general markets, broad patterns fire on unrelated questions.

**How to avoid:** This is not a Phase 13 problem to solve — the catalog stores exactly what PatternMatcher returns, false positives included. The correct fix is narrowing taxonomy patterns (out of scope for Phase 13). Document in catalog-stats output as `flagged_for_review` count.

**Warning signs:** `catalog-stats` shows unexpectedly high esports row count (confirmed: 18,331 rows across 9,166 markets out of 408,863). Some of those are false positives but the number is small relative to total.

### Pitfall 2: Token ID Data Type Mismatch

**What goes wrong:** `clob_token_ids` in the markets parquet is a JSON string `["71321956...", "60869871..."]`. The `maker_asset_id` / `taker_asset_id` in the trades parquet are stored as VARCHAR. If the catalog stores `token_id` as anything other than plain `str(tid)`, the lookup fails.

**Why it happens:** DuckDB's `json_extract_string` returns strings, but sloppy casting can produce quoted strings or integers.

**How to avoid:** Always `str(tid)` when building catalog entries. Always `str(jbecker_trade["maker_asset_id"])` on the lookup side. Both sides go through `str()` already in `jbecker_trade_to_api_response()`.

**Warning signs:** Lookup returns None for a token you expect to be in the catalog.

### Pitfall 3: maker_asset_id=0 Records

**What goes wrong:** In the trades parquet, ~78% of records have `maker_asset_id='0'`. The converter sets `asset_id = maker_asset_id if is_maker else taker_asset_id`. When a trader is the maker and `maker_asset_id='0'`, the lookup `token_to_condition.get('0')` returns None and the trade is skipped.

**Why it happens:** `maker_asset_id=0` means the maker side provided USDC (the collateral token). The market token is always the `taker_asset_id` in this case. The existing converter handles this correctly because `is_maker=True` when `trader==maker`, but `maker_asset_id=0` means the trader was actually selling USDC to buy the token.

**How to avoid:** Do not add `'0'` → any mapping in the catalog. The `'0'` skip is correct. The trade's relevant token is the non-zero asset ID, which the existing converter already selects via the `is_maker` branch.

**Warning signs:** High `skipped_invalid` count in backfill stats is expected for this reason and is not a catalog bug.

### Pitfall 4: Catalog Build on Every Backfill Call

**What goes wrong:** The auto-build check runs inside `ingest_trader_history_jbecker()`, which is called once per trader. If the check is implemented by counting rows (slow), it adds overhead. If it doesn't guard against concurrent builds, two parallel backfill workers could both trigger a build simultaneously.

**Why it happens:** The backfill command batch-processes N traders sequentially in the current implementation (not parallel), so this is a theoretical concern. But the `is_built()` check must be fast.

**How to avoid:** Use `session.query(TokenCatalog).limit(1).first() is not None` — this uses the primary key index and returns instantly. Cache the result in the `IngestionPipeline` instance after first check:

```python
# In IngestionPipeline.__init__:
self._catalog_built: bool = False  # instance-level cache

# In ingest_trader_history_jbecker:
if not self._catalog_built:
    with self.session_factory() as s:
        if not builder.is_built(s):
            builder.build(s)
    self._catalog_built = True
```

**Warning signs:** Backfill of 100 traders takes 100x longer than expected due to repeated catalog scans.

### Pitfall 5: Missing TaxonomyNode When Creating MarketClassification

**What goes wrong:** `MarketClassification.taxonomy_node_id` is a foreign key to `taxonomy_nodes`. If `sync_taxonomy_to_db()` has not been run (e.g., fresh install), the TaxonomyNode rows don't exist, and the FK lookup returns None.

**Why it happens:** TaxonomyNode rows are created by `ClassificationPipeline.sync_taxonomy_to_db()`, which is typically called during the `sweep` command. A fresh backfill before any sweep has run will find no TaxonomyNode rows.

**How to avoid:** In the catalog-based Market/Classification creation path, allow `taxonomy_node_id=None` (the FK is already nullable in the existing schema). The `node_path` string is still stored correctly and can be used for scoring. Do not block backfill on missing TaxonomyNode rows.

**Warning signs:** `MarketClassification.taxonomy_node_id` is NULL for all catalog-sourced records. This is acceptable behavior, not a bug.

### Pitfall 6: Duplicate Market/MarketClassification INSERT

**What goes wrong:** Backfilling the same trader twice (or two different traders who both traded the same market) attempts to INSERT a Market with a `condition_id` that already exists. `Market.condition_id` has `unique=True`, so the second INSERT raises `IntegrityError`.

**Why it happens:** Multiple traders can trade the same market. The backfill loops over traders, and for each trader loops over their trades.

**How to avoid:** Check-first pattern before INSERT:

```python
existing = session.query(Market).filter_by(condition_id=cid).first()
if not existing:
    session.add(Market(...))
    session.flush()
```

Same pattern for `MarketClassification` (also `unique=True` on `market_id`). This is already the pattern used in `ingest_active_markets()` and the Gamma API lookup code.

**Warning signs:** `IntegrityError: UNIQUE constraint failed: markets.condition_id` during backfill.

---

## Code Examples

### Building the Catalog: Full Flow

```python
# Source: verified against live data (2026-02-19)
import duckdb
import json
from pathlib import Path
from src.taxonomy.classifier import PatternMatcher, detect_market_type
from src.taxonomy.loader import load_taxonomy

def build_token_catalog(markets_glob: str, taxonomy_path: Path) -> list[tuple]:
    """Returns list of (token_id, condition_id, question, niche_slug,
    node_path, depth, market_type) tuples for all JBecker markets."""
    taxonomy = load_taxonomy(taxonomy_path)
    matcher = PatternMatcher(taxonomy)

    # DuckDB reads all 41 files in ~0.5s
    result = duckdb.execute(
        "SELECT condition_id, question, clob_token_ids "
        "FROM read_parquet($1) WHERE question IS NOT NULL",
        [markets_glob]
    )
    rows = result.fetchall()   # ~0.5s, 408,863 rows

    catalog_rows = []
    for cid, question, clob_json in rows:   # ~15s classification loop
        cr = matcher.classify(question)
        niche_slug = "esports" if (cr and cr.depth >= 1) else None
        node_path = cr.node_path if cr else None
        depth = cr.depth if cr else None
        market_type = detect_market_type(question) if niche_slug else None
        try:
            token_ids = json.loads(clob_json) if clob_json else []
        except (ValueError, TypeError):
            token_ids = []
        for tid in token_ids:
            catalog_rows.append(
                (str(tid), cid, question[:500], niche_slug, node_path, depth, market_type)
            )
    return catalog_rows  # ~817,683 rows
```

### Writing to SQLite: Single-Transaction Bulk Insert

```python
# Source: benchmarked (2026-02-19): 817k rows in ~8s single transaction
import sqlite3

def write_catalog_to_sqlite(catalog_rows: list[tuple], db_path: str) -> int:
    """Write catalog rows using raw sqlite3 for bulk performance.
    Returns number of rows written."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    # Single transaction: ~8s for 817k rows (vs 11s with batches of 50k)
    cur.executemany(
        "INSERT OR IGNORE INTO token_catalog "
        "(token_id, condition_id, question, niche_slug, node_path, depth, market_type) "
        "VALUES (?,?,?,?,?,?,?)",
        catalog_rows
    )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM token_catalog")
    count = cur.fetchone()[0]
    conn.close()
    return count
```

### Catalog Lookup in Backfill

```python
# Source: adapted from ingest.py _build_token_cache pattern
def _build_catalog_token_cache(self, session) -> dict[str, tuple[str, str, str | None]]:
    """Build token_id -> (condition_id, node_path, market_type) from token_catalog.
    Only returns esports entries (niche_slug='esports')."""
    from src.db.models import TokenCatalog
    entries = (
        session.query(TokenCatalog)
        .filter(TokenCatalog.niche_slug == "esports")
        .all()
    )
    return {
        e.token_id: (e.condition_id, e.node_path, e.market_type)
        for e in entries
    }
```

### SQLAlchemy Model Registration

```python
# In src/db/models.py — add to existing file, no other changes needed
# Base.metadata.create_all(engine) will create the new table automatically
# No migration scripts needed; SQLAlchemy handles IF NOT EXISTS

class TokenCatalog(Base):
    __tablename__ = "token_catalog"
    token_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    condition_id: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    niche_slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    node_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    depth: Mapped[int | None] = mapped_column(nullable=True)
    market_type: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        Index("ix_catalog_condition", "condition_id"),
        Index("ix_catalog_niche", "niche_slug"),
    )
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|-----------------|--------|
| Token lookup: Gamma API HTTP call per batch | Token lookup: SQLite catalog (offline) | Removes API dependency from backfill; ~100x faster lookup |
| Market creation: requires live API response | Market creation: from catalog question field | Backfill works fully offline after catalog build |
| `_build_token_cache`: only markets already in SQLite | `_build_token_cache` + catalog: covers all 408k JBecker markets | Orders of magnitude more coverage for historical backfill |

---

## Open Questions

1. **Catalog rebuild mechanism for taxonomy updates**
   - What we know: The CONTEXT says "rebuildable when taxonomy patterns update" — the `is_built()` check uses row count. A taxonomy update doesn't automatically empty the catalog.
   - What's unclear: How does a user trigger a rebuild? There is no `catalog-rebuild` CLI command planned in this phase.
   - Recommendation: For Phase 13, rebuilding is done by truncating the `token_catalog` table manually (or dropping + recreating via `Base.metadata.create_all`). A `--rebuild` flag on `catalog-stats` command could be added in a future phase. The planner should note this limitation explicitly.

2. **`active` field on Market records created from catalog**
   - What we know: JBecker markets parquet has `active` and `closed` boolean fields.
   - What's unclear: The catalog schema as specified does NOT store `active`/`closed`. When creating Market records from the catalog, what value to use?
   - Recommendation: Store `active=False` for all catalog-sourced Market records. These are historical markets (JBecker dataset ends before 2026). The `active` field is used for live market display (`polymarket markets`); historical records don't need to appear there.

3. **niche_slug format convention (Claude's Discretion)**
   - Recommendation: Use lowercase, no spaces: `"esports"`. This matches the existing `detail_categories = ["eSports"]` after `.lower()` normalization. Consistent with how `CategoryFilter` lowercases for comparison. Future niches: `"crypto"`, `"sports"` following the same pattern.

4. **Index strategy (Claude's Discretion)**
   - Recommendation: Two secondary indexes are sufficient:
     - `ix_catalog_condition` on `condition_id` — used by catalog-stats and Market creation dedup check
     - `ix_catalog_niche` on `niche_slug` — used by `_build_catalog_token_cache` query
   - Primary key on `token_id` is the main lookup index for backfill. No additional indexes needed.

5. **Batch size for catalog build (Claude's Discretion)**
   - Recommendation: Use a single transaction (no batching) for the write. Benchmarked result: 817k rows in 7.6s as one transaction vs 11.6s with 50k batches. The build runs once; crash-safety of batching is not worth the overhead.

---

## Sources

### Primary (HIGH confidence)

- Live code inspection: `src/datasources/jbecker.py` — JBeckerDataset.query_trader_history() confirmed; trades_path glob pattern confirmed
- Live code inspection: `src/datasources/converters.py` — jbecker_trade_to_api_response() asset_id selection logic confirmed
- Live code inspection: `src/pipeline/ingest.py` — `_build_token_cache()`, `ingest_trader_history_jbecker()`, Gamma API unknown-token lookup flow confirmed
- Live code inspection: `src/db/models.py` — Market.condition_id unique=True, MarketClassification.market_id unique=True confirmed; existing ORM patterns confirmed
- Live code inspection: `src/taxonomy/classifier.py` — PatternMatcher.classify() and detect_market_type() confirmed
- Live code inspection: `src/config/settings.py` — jbecker_data_path, taxonomy_path, database_url settings confirmed
- Live data inspection: `data/polymarket/markets/*.parquet` — 41 files, 408,863 markets, clob_token_ids is JSON string array confirmed
- Live data inspection: `data/polymarket/trades/trades_0_10000.parquet` — maker_asset_id/taker_asset_id are VARCHAR confirmed; 77.8% records have maker_asset_id='0'

### Secondary (MEDIUM confidence — verified by live execution)

- DuckDB scan benchmark: 408,863 markets in 0.5s (measured 2026-02-19)
- PatternMatcher classification benchmark: 408,863 markets classified in ~15s (measured 2026-02-19)
- SQLite write benchmark: 817,683 rows, single transaction, 7.6s (measured 2026-02-19)
- Token catalog size: 817,683 total rows; 18,331 esports rows (9,166 markets, 2.2% of total)
- False positive confirmed: "Champions League" matches `eSports.Valorant.VCT Champions` — existing PatternMatcher behavior, not Phase 13's concern
- INSERT OR IGNORE idempotency: verified in Python test with duplicate primary key

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project, versions confirmed
- Architecture: HIGH — based on reading actual ingest.py code; patterns directly adapted from working code
- Pitfalls: HIGH — false positives, zero asset IDs, and unique constraint risks verified against live data
- Performance numbers: HIGH — all benchmarks run against actual 408k market dataset

**Research date:** 2026-02-19
**Valid until:** 2026-03-19 (stable domain; JBecker dataset is static)
