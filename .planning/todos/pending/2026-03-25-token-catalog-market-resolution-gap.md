---
created: 2026-03-25T13:49:16.667Z
title: Fix token catalog coverage for market resolution gap
area: data
files:
  - src/graph/converters.py
  - data/polymarket.db
---

## Problem

The Graph converter fix (commit 561e9c7) successfully prevents grabbing USDC asset_id ("0") instead of conditional tokens. However, 60% of trades still can't be resolved to markets.

Current state:
- Total trades: 2,447,277
- Trades with `graph_` prefix (unresolved): 1,464,508 (60%)
- Trades matched to markets: 964,936 (40%)

The converter correctly extracts the conditional token asset_id, but the token catalog lookup isn't finding condition_ids for those assets. This is a **separate issue from the asset_id selection bug** — it's about missing market metadata.

Daily resolution rates show inconsistency:
```
2026-03-25: 15.2%
2026-03-24: 26.6%
2026-03-23: 18.7%
2026-03-16: 28.5%
2026-03-13: 35.3%
```

## Solution

Investigate and fix the token catalog lookup pipeline:
1. Verify how conditional token IDs are mapped to condition_ids
2. Check if markets table has all required condition_id entries
3. Identify why 1,054,260 unique market_ids in trades don't match the 155,568 condition_ids in markets table
4. Either:
   - Expand market ingestion to cover missing condition_ids, OR
   - Improve the token catalog lookup logic in the converter

Priority: High — this blocks accurate position tracking and PnL calculations for 60% of trades.
