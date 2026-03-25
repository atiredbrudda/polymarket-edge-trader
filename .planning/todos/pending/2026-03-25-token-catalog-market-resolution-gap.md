---
created: 2026-03-25T13:49:16.667Z
title: Build ground truth test set for Graph vs API trade comparison
area: testing
files:
  - src/graph/client.py
  - src/api/client.py
  - src/datasources/jbecker.py
---

## Problem

The Graph converter fix (commit 561e9c7) successfully prevents grabbing USDC asset_id ("0") instead of conditional tokens. However, 60% of trades still can't be resolved to markets.

Before fixing the token catalog, we need **ground truth validation** to:
1. Confirm the actual divergence between Graph and API/JBecker trade data
2. Understand exactly where market_id resolution fails
3. Have a test set to validate fixes against

Current state:
- Total trades: 2,447,277
- Trades with `graph_` prefix (unresolved): 1,464,508 (60%)
- Trades matched to markets: 964,936 (40%)

## Solution

**Build a comparison test set:**

1. **Pull 10 traders via both sources:**
   - Use existing API/JBecker pipeline (trusted format)
   - Pull same traders via Graph (new source)

2. **Split the data:**
   - First 5 traders → test/case study (build solution)
   - Last 5 traders → validation (confirm solution works)

3. **Compare outputs:**
   - Match trades by market, side, timestamp, size
   - Identify exactly where Graph trades diverge
   - Verify market_id resolution is the actual problem

4. **Once Graph matches API format:**
   - Slot Graph data into existing pipeline
   - Then fix catalog coverage with confidence

Priority: High — this testing foundation is required before any catalog fix.

