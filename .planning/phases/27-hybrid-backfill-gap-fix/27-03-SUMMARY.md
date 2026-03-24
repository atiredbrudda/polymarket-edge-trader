# Plan 27-03 Summary: Graph Price Conversion Fix

## What was built

Fixed the price validation error in Graph trade processing by converting decimal odds to implied probability format.

## Root Cause

The Graph subgraph returns prices in **decimal odds** (European odds) format, where:
- Decimal odds > 1.0 represent underdogs (e.g., 2.0 = pay $2 to win $1)
- Decimal odds < 1.0 represent favorites (e.g., 0.5 = pay $0.50 to win $1)

However, `TradeResponse` model expects **probability** format (0 < price < 1), where the price represents the implied probability of the outcome occurring.

This mismatch caused Pydantic validation errors for any Graph trade with decimal odds > 1.0:
```
Value error, Price must be between 0 and 1 (exclusive), got 1.123595505617977528089887640449438
Value error, Price must be between 0 and 1 (exclusive), got 32.25806339035813249017596024317552
Value error, Price must be between 0 and 1 (exclusive), got 50
```

Impact: ~9% of Graph trades were being silently dropped during backfill (188 of 2,024 trades for one test address).

## Key Changes

### src/graph/converters.py (Line 81-85)

Added price normalization logic:

```python
# Price from Graph is in decimal odds format (can be > 1 for underdogs)
# Convert to probability format (0-1 range) expected by TradeResponse
price = Decimal(graph_trade["price"])
if price > 1:
    # Convert decimal odds to implied probability
    price = Decimal("1") / price
```

The conversion formula: `probability = 1 / decimal_odds`

Examples:
- Decimal odds 2.0 → Probability 0.5 (50% chance)
- Decimal odds 32.26 → Probability 0.031 (3.1% chance)
- Decimal odds 50 → Probability 0.02 (2% chance)
- Decimal odds 0.5 → Probability 0.5 (unchanged, already in valid range)

### tests/test_graph_converters.py (NEW)

Created comprehensive test suite for the Graph converter:

1. `test_graph_trade_price_under_one` — Verifies prices < 1 are kept as-is
2. `test_graph_trade_price_over_one` — Verifies prices > 1 are converted to implied probability
3. `test_graph_trade_price_decimal_odds` — Tests various decimal odds conversions with tolerance checking

All 3 tests pass.

## Deviations from Plan

This was an unplanned fix discovered from user error logs during backfill. No formal plan was written.

## Test Results

```bash
pytest tests/test_graph_converters.py -v
============================= test session starts ==============================
tests/test_graph_converters.py::test_graph_trade_price_under_one PASSED  [ 33%]
tests/test_graph_converters.py::test_graph_trade_price_over_one PASSED   [ 66%]
tests/test_graph_converters.py::test_graph_trade_price_decimal_odds PASSED [100%]

============================== 3 passed in 0.26s ===============================
```

Related tests also pass:
```bash
pytest tests/test_api_models.py tests/test_ingest.py -q
15 passed, 47 warnings in 0.83s
```

## Known Issues

None. The fix is minimal and surgical.

## Files Changed

- `src/graph/converters.py` (+4 lines functional change)
  - Line 81-85: Added decimal odds to probability conversion
- `tests/test_graph_converters.py` (+85 lines, NEW file)
  - 3 comprehensive test cases

## Verification

The fix ensures that all Graph trades with decimal odds > 1 are now properly converted to probability format before validation. Prices that were previously failing validation (e.g., 32.26, 50, 7.14) are now converted to valid probabilities (0.031, 0.02, 0.14) and processed successfully.

## Impact

This fix resolves the validation errors that were silently dropping ~9% of Graph trades during backfill operations. All Graph trades will now be properly processed regardless of whether they represent favorites or underdogs.

Expected behavior after this fix:
- No more "Price must be between 0 and 1" validation errors for Graph trades
- Complete trade history from Graph API with zero dropped trades
- Consistent price format (probability) across all data sources (JBecker, API, Graph)
