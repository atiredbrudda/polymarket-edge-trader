# Fix: Non-eSports Market & Trade Pollution in Database

**Date:** 2026-03-15
**Severity:** High — polluted data was actively mixing into esports-only analysis
**Status:** Fixed and verified

---

## Problem

The database contained 206,599 non-esports markets (out of 222,829 total) and 143,080 non-esports trades in the `trades` table (which should only hold esports detail trades). Categories included Unknown (202K), Crypto, Sports, Politics, Weather, Finance, and dozens more.

## Root Cause

Three of four backfill code paths in `src/pipeline/ingest.py` had no category filtering on market insertion, and one had no category filtering on trade storage at all.

### Path-by-path breakdown

| Backfill Path | Market Insert Filter | Trade Storage Filter | Bug |
|---|---|---|---|
| **API** (line ~868) | None | Yes (CategoryFilter) | Inserted all markets regardless of category |
| **Blockchain** (line ~1133) | None | Yes (CategoryFilter) | Same — inserted all markets |
| **JBecker** (line ~1710) | None | Yes (CategoryFilter) | Inserted all markets; Gamma API fallback labeled unknowns as "Unknown" |
| **Graph** (line ~1386) | None | **None** | Worst offender — no filtering at all, dumped every trade as detail |

### How it accumulated

1. **Previous runs (pre-wipe, Feb 20+):** Backfill inserted non-esports markets over multiple runs. When the user wiped `traders` and `trades` tables, the `markets` table was not included, so ~170K stale non-esports markets survived.

2. **Current run (post-wipe, Mar 14+):** Running `polymarket backfill` after a clean discover created 34K+ new non-esports markets and 143K non-esports trades. The mechanism: esports traders also trade in other categories (Crypto, Sports, etc.), and backfill fetches their *entire* trade history, then inserts every market they touched.

### Why `discover` was not the culprit

`polymarket discover --niche esports --closing-within 3h` correctly uses `ingest_targeted_markets()` which filters by niche. Verified by before/after DB comparison — only 11 esports markets were added by discover.

### Why `ingest-events` and `patch-catalog` were not culprits

- `ingest-events` only writes to `gamma_events` table
- `patch-catalog` only writes to `token_catalog` table
- Neither touches the `markets` table

## Verification: No False Positives

Before purging, we verified that no real esports data would be lost:

- **0** markets with a confirmed esports `node_path` in `token_catalog` had a non-esports category label
- **0** "Unknown" markets had a real esports `node_path` (all 466 were Tier 3 fallbacks — Champions League, golf, etc.)
- The API consistently labels esports markets as `eSports` or `esports` — both caught by `category.lower()` matching
- The 104K "Unknown" markets in `market_classifications` labeled "eSports" were from a polluted classifier, not real esports content

## Fix Applied

### 1. Code changes (`src/pipeline/ingest.py`)

Added `self.category_filter.requires_detail()` checks to all four backfill paths:

**API backfill (line ~868):** Market metadata is still fetched (needed for trade routing), but the `Market` row is only persisted if the category passes the filter.

**Blockchain backfill (line ~1133):** Same pattern — fetch metadata for routing, only persist detail-category markets.

**JBecker backfill (line ~1710):** Gamma API fallback still resolves `condition_id → category` mapping (needed for `CategoryFilter.route_trades()`), but only persists market rows for detail categories. Token-to-condition mapping is preserved regardless of category so trade routing still works.

**Graph backfill (line ~1386):** Complete rewrite of this path. Previously had zero categorization (`"Store as detail trade (no categorization for now)"`). Now:
- Resolves market category via DB lookup or API fetch
- Uses `CategoryFilter.route_trades()` to split detail vs summary
- Only persists detail-category markets
- Routes non-esports trades to `trader_category_summaries` instead of `trades`

### 2. Database purge

```sql
DELETE FROM trades WHERE market_id IN
  (SELECT condition_id FROM markets WHERE LOWER(category) NOT IN ('esports'));
-- 143,080 deleted

DELETE FROM trader_category_summaries WHERE LOWER(category) NOT IN ('esports');
-- 16,488 deleted

DELETE FROM markets WHERE LOWER(category) NOT IN ('esports');
-- 206,599 deleted
```

### 3. No changes needed to CLI commands

The `CategoryFilter` is already injected into `IngestionPipeline` at construction time. The filter reads from `detail_categories` in `src/config/settings.py` (default: `["eSports"]`), configurable via `.env`. No new flags or arguments required.

## Post-Fix Verification

Ran the full pipeline chain after the fix:
`ingest-events` → `discover --niche esports --closing-within 3h` → `patch-catalog` → `backfill`

### Results

| Table | Pre-fix | Post-purge | Post-backfill | Status |
|---|---|---|---|---|
| Markets (eSports) | 15,254 | 15,253 | 15,275 | Clean |
| Markets (esports) | 976 | 987 | 987 | Clean |
| **Non-esports markets** | **206,599** | **0** | **0** | **Fixed** |
| Trades | 1,166,210 | 1,023,130 | 1,037,252 | Clean |
| Summaries (non-esports) | 16,488 | 0 | 1,149 | Correctly routed |
| Traders | 6,079 | 6,079 | 6,105 | Unaffected |

Non-esports trades from backfill now correctly route to `trader_category_summaries` (Sports: 183, Politics: 183, Crypto: 183, etc.) instead of the `trades` detail table.

## Lesson Learned

- When wiping the database, include the `markets` table — not just `traders` and `trades`
- The `CategoryFilter` routing pattern (detail vs summary) must be applied at both the market-insertion and trade-insertion layers, not just one
- "Temporary" code comments like `"no categorization for now"` in the Graph path became permanent bugs
