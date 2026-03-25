# Market Outcome Coverage Research

**Date:** 2026-03-25  
**Purpose:** Research the bottleneck in market outcome resolution blocking position scoring

---

## Executive Summary

The scoring pipeline cannot resolve positions because **91% of markets lack outcome data**. This is a market outcome coverage problem, not a position resolution problem.

### Key Statistics

| Metric | Count | Percentage |
|--------|-------|------------|
| Total markets | 148,997 | 100% |
| Resolved markets | 12,356 | **8%** |
| Unresolved markets | 136,641 | **91%** |
| Total trades | 2,529,922 | - |
| Trades with `graph_` placeholder | 1,841,558 | **72%** |
| Total positions | 97,060 | - |
| Resolved positions | 70,822 | 72% |
| Unresolved positions | 26,238 | **27%** |

**Root cause:** Only 8.3% of markets have `outcome` populated. The `resolve-positions` command requires `Market.outcome` to compute position PnL, but 136K markets are in a blind spot.

---

## Problem Breakdown

### 1. Market Sources and Coverage Gaps

Markets enter the system through three paths:

| Source | Description | Coverage |
|--------|-------------|----------|
| **Gamma Events API** | Ingested via `ingest-events` → `gamma_events` table | ~11K events, esports-focused |
| **Graph (The Graph)** | Real-time subgraph queries → synthetic `graph_` IDs | 1.8M trades (72%) |
| **JBecker Dataset** | Historical parquet files → synthetic `graph_` IDs | Part of 1.8M |

**The Gap:** Markets created via Graph/JBecker paths:
- Have `market_id = "graph_{txHash}_{assetId}"` (synthetic placeholder)
- Were never matched to real `condition_id` during migration
- Have no corresponding `GammaEvent` row
- Cannot be resolved by `resolve-outcomes` (which only scans `gamma_events` table)

### 2. Category Distribution of Unresolved Markets

```
Unknown:        130,420 (95% of unresolved)
Other:            3,292
esports:          1,470
Crypto:             568
Sports:             300
Weather:            202
Politics:           148
eSports:             92
```

**Critical finding:** 130K unresolved markets are categorized as "Unknown" — these have `NULL` end dates and no taxonomy classification.

### 3. Esports Market Analysis

| Metric | Count |
|--------|-------|
| Total esports markets | 13,918 |
| Resolved | 12,356 (89%) |
| Active & Unresolved | 1,102 |
| Unresolved with end_date < 30 days ago | 1,040 |
| Unresolved with end_date > 30 days ago | 0 |

**Insight:** All 1,040 unresolved esports markets have end dates within the last 30 days. There are **no old, definitely-closed esports markets** remaining — they've all been resolved.

### 4. The `graph_` Placeholder Problem

**What is `graph_`:**
- Format: `graph_{transactionHash}_{assetId}`
- Created in `src/graph/converters.py:102` when `token_to_condition` lookup fails
- Represents trades where the asset_id couldn't be mapped to a condition_id

**Why it matters:**
- 72% of all trades use placeholder IDs
- These trades cannot be linked to markets for resolution
- The migration from `graph_` to real condition_ids achieved only 11.4% match rate

**Example:**
```
Trade.market_id: graph_0xf704ff1584f312b6a1f38599e9cdebf0768c6f23cc27e1166a52e00fdbef7547_54104800394221291794784713979963016024782081813693508603329576574109946650821
├── transactionHash: 0xf704ff1584f312b6a1f38599e9cdebf0768c6f23cc27e1166a52e00fdbef7547
└── assetId: 54104800394221291794784713979963016024782081813693508603329576574109946650821
```

**Matching attempt:** Extracted condition_ids from `graph_` market_ids do NOT exist in the `markets` table — they are transaction hashes, not condition IDs.

---

## Current Resolution Pipeline

### Phase 29 Solution (Already Implemented)

**File:** `src/gamma/events_resolver.py`  
**Command:** `polymarket resolve-markets-from-events`

**How it works:**
1. Fetches ALL closed events from Gamma API (`active=false`, no tag filter)
2. Extracts winner from `outcomePrices` (token with price closest to 1.0)
3. Updates `markets.outcome` for matched markets

**Limitation:** Only resolves markets that:
- Have a corresponding event in Gamma API
- Can be matched via token_id → market.tokens join

**Does NOT cover:**
- Markets with `NULL` end dates (130K "Unknown" category)
- Markets not listed in Gamma API (delisted/old markets)

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      MARKET INGESTION                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Gamma API ──► gamma_events table ──┐                          │
│  (11K events)                        │                          │
│                                      ▼                          │
│  Graph Subgraph ──► trades table     │  resolve-outcomes        │
│  (graph_ placeholders) ──────────────┼──► markets.outcome       │
│                                      │   (12K resolved)         │
│  JBecker Parquet ──► trades table    │                          │
│  (graph_ placeholders) ──────────────┘                          │
│                                                                 │
│  Blind spot: 136K markets with no GammaEvent row               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    POSITION RESOLUTION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  trades ──► build-positions ──► positions ──┐                   │
│                                              │                   │
│  markets.outcome (IS NOT NULL) ──────────────┼──► resolve-positions
│  (12K markets)                               │   (70K resolved)  │
│                                              │                   │
│  markets.outcome (IS NULL) ──────────────────┘   (26K blocked)   │
│  (136K markets - CANNOT RESOLVE)                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Findings

### 1. The "Unknown" Category Problem

**130,420 markets** are categorized as "Unknown" with:
- `active = TRUE`
- `outcome = NULL`
- `end_date = NULL`
- `tokens IS NOT NULL` (has token IDs)
- No `GammaEvent` row

**Hypothesis:** These are markets that:
- Were created via Graph/JBecker path
- Never received end_date metadata
- May be closed in reality but DB shows `active=TRUE`
- Could potentially be resolved via live Gamma API lookup

### 2. Esports is Actually Well-Covered

- 89% of esports markets are resolved (12,356 / 13,918)
- Remaining 1,040 unresolved are all recent (< 30 days)
- No old, definitely-closed esports markets remain

**Conclusion:** The esports resolution pipeline is working. The bottleneck is non-esports categories.

### 3. Token Coverage is Good

- 144,219 markets (97%) have `tokens` JSON populated
- This means token_id → market matching should work for most markets
- The missing piece is **GammaEvent data**, not token metadata

### 4. Phase 29 Coverage Unknown

The `resolve-markets-from-events` command was implemented but coverage metrics are unknown:
- How many of the 136K unresolved markets exist in Gamma API?
- How many are delisted/404 from Gamma?
- What's the expected resolution rate?

**Recommendation:** Run the command and measure:
```bash
polymarket resolve-markets-from-events --verbose
```

---

## Research Questions Answered

### Q: Where do the 1.8M `graph_` trades come from?

**A:** The Graph subgraph queries and JBecker dataset ingestion. When `token_to_condition` lookup fails (token not in catalog), the converter creates a synthetic `graph_{txHash}_{assetId}` placeholder.

### Q: Can `graph_` placeholders be matched to real markets?

**A:** No — the extracted "condition_id" portion is actually a transaction hash, not a condition ID. These are truly orphaned trades.

### Q: Are there closed esports markets that haven't been resolved?

**A:** No. All unresolved esports markets have end dates within the last 30 days. The 14,827 markets mentioned in the problem statement are not in the current database state.

### Q: What's the actual bottleneck?

**A:** 130K "Unknown" category markets with NULL end dates and no GammaEvent rows. These are likely:
- Non-esports markets (politics, crypto, sports, etc.)
- Ingested via Graph/JBecker without full metadata
- Not present in the `gamma_events` table

---

## Recommended Next Steps

1. **Run Phase 29 resolver** and measure coverage:
   ```bash
   polymarket resolve-markets-from-events --verbose
   # Track: markets_resolved, events_processed, events_skipped
   ```

2. **Query Gamma API directly** for sample of "Unknown" markets to check:
   - Do they exist in Gamma API?
   - Are they marked closed?
   - Do they have outcomePrices?

3. **Investigate "Unknown" category origin:**
   - When were these markets ingested?
   - What ingestion path created them?
   - Why no end_date?

4. **Consider CLOB API fallback:**
   - Query `/markets?conditionId=` for unknown markets
   - May return 404 for delisted markets
   - Could populate end_date and active status

5. **Token catalog expansion:**
   - More complete token → condition_id mapping
   - Would reduce `graph_` placeholder creation
   - Enables matching more trades to real markets

---

## Appendix: File Reference

| File | Purpose |
|------|---------|
| `src/gamma/resolution.py` | Original resolver (gamma_events table only) |
| `src/gamma/events_resolver.py` | Phase 29 bulk resolver (live Gamma API) |
| `src/graph/converters.py` | Creates `graph_` placeholders |
| `src/graph/client.py` | The Graph subgraph client |
| `src/datasources/jbecker.py` | JBecker parquet dataset queries |
| `src/db/models.py` | Market, GammaEvent, Trade, Position models |
| `src/cli/commands.py` | CLI commands (resolve-outcomes, resolve-markets-from-events) |

---

**Researcher:** opencode  
**Session Date:** 2026-03-25
