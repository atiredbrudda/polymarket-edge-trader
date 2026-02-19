# Phase 13: Esports Token Catalog & JBecker Classification - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a token catalog that maps JBecker `clob_token_ids` → esports taxonomy nodes, then use it to classify historical JBecker trades for already-known traders during backfill.

JBecker trades reference numeric token IDs. The existing classifier works on market question text. This phase bridges the gap by scanning the JBecker markets parquet (41 files, includes `question` + `clob_token_ids`), classifying each market, and persisting the mapping in a SQLite table. During backfill, the catalog is consulted to create `Market` + `MarketClassification` records so JBecker trades flow through the existing scoring pipeline unchanged.

**Out of scope:** Discovering new traders from JBecker market trades (deferred — separate project).

</domain>

<decisions>
## Implementation Decisions

### Catalog storage
- SQLite table in `polymarket.db` (not DuckDB runtime, not JSON file)
- Explicit SQLite chosen for debuggability: `sqlite3 polymarket.db "SELECT * FROM token_catalog WHERE ..."` works for debugging misclassifications
- Use DuckDB to scan the JBecker markets parquet and write results into the SQLite table (one-time build)

### Catalog schema
- Store ALL markets from JBecker (not just esports) — this is the architecture prototype that will generalize to other niches
- Schema: `token_id, condition_id, question, niche_slug, node_path, depth, market_type`
  - `niche_slug`: matched niche string (e.g., `"esports"`, `null` for unmatched) — extensible to future niches without schema changes
  - `node_path`: full taxonomy path for matched markets (e.g., `"eSports.CS2.IEM Katowice"`) — classification is instant from catalog, no re-running PatternMatcher at ingestion
  - `depth`: taxonomy depth (1=game, 2=tournament, 3=team, null for unmatched)
  - `market_type`: `"match"` or `"prop"` for esports markets, null otherwise

### Catalog build trigger
- Auto-built during backfill if catalog table is empty or missing
- Fully invisible to user — no manual step required
- Build is a one-time scan of 41 markets parquet files (expected: seconds)
- Rebuildable (truncate + rebuild) for when taxonomy patterns are updated

### Trader discovery scope
- Phase 13 does NOT discover new traders from JBecker
- Catalog classification applies only to traders already discovered via the existing `discover` command
- JBecker-sourced trader discovery is explicitly deferred to a future project

### Trade classification during backfill
- For each JBecker trade, look up `maker_asset_id` / `taker_asset_id` in the catalog
- If found AND `niche_slug = "esports"`: create/update `Market` record + `MarketClassification` record, then ingest trade normally
- If token ID not in catalog (market predates snapshot or missing): **skip the trade, log a warning** — no API fallback
- After classification, scoring update timing: Claude's discretion (fit existing backfill pipeline flow)

### Live pipeline integration
- Catalog-sourced markets create proper `Market` + `MarketClassification` records
- JBecker trades then flow through the existing scoring pipeline unchanged (same path as live-discovered trades)
- No schema changes to Trade, Market, or MarketClassification tables

### CLI
- Add `polymarket catalog-stats` command showing:
  - Total markets in catalog
  - Esports markets by game (CS2, LoL, Dota2, etc.)
  - Unclassified count
  - Coverage stats (useful for verifying catalog was built correctly)

### Claude's Discretion
- Exact niche_slug representation format (e.g., `"esports"` vs `"eSports"` — follow existing taxonomy slug convention)
- Whether scoring re-runs automatically after backfill classifies trades, or relies on next scheduled scoring run
- Batch size for catalog build (reading 41 parquet files across millions of markets)
- Index strategy on `token_catalog` table (token_id indexed for fast lookup during backfill)

</decisions>

<specifics>
## Specific Ideas

- "eSports is to get the logic working which we'll then extend to other parts" — catalog architecture must generalize from day one. The `niche_slug` column is the extensibility hook.
- Debuggability was explicitly called out as a requirement: SQLite chosen over DuckDB runtime precisely because misclassifications must be inspectable without writing query code.
- The catalog is the bridge between token IDs (JBecker world) and market questions (classifier world). Once built, classification during backfill is a simple lookup — no API calls, no re-pattern-matching.

</specifics>

<deferred>
## Deferred Ideas

- **JBecker-sourced trader discovery** — Scanning JBecker esports market trades to find NEW traders not yet in our system. User explicitly called this "best suited for another project entirely." Note for future milestone backlog.
- **Catalog-based discovery for other niches** — Once esports catalog pattern is proven, extending to crypto, sports, etc. would reuse the same `niche_slug` catalog table with new taxonomy configs. Not in scope for Phase 13.

</deferred>

---

*Phase: 13-esports-token-catalog-jbecker-classification*
*Context gathered: 2026-02-19*
