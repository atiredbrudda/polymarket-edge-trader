# Graph vs API Ground Truth Test Set

## Purpose

This test set validates the divergence between The Graph and Polymarket API/JBecker trade data sources. It provides ground truth for:

1. Confirming the actual divergence rate between sources
2. Understanding where market_id resolution fails
3. Validating fixes to the token catalog coverage

## Test Set Structure

The test set splits 10 traders into two groups:

- **Test set (5 traders)**: Used to build and refine the solution
- **Validation set (5 traders)**: Used to confirm the solution generalizes

## Files Generated

```
data/graph_api_comparison/
├── summary.json                    # Overall statistics
├── test_set_comparison.json        # Detailed results for test traders
└── validation_set_comparison.json  # Detailed results for validation traders
```

## Summary Format

```json
{
  "generated_at": "2026-03-25T14:00:00",
  "total_traders": 10,
  "test_traders": 5,
  "validation_traders": 5,
  "test_results": [
    {
      "trader": "0xabc123...",
      "graph_trades": 150,
      "api_trades": 148,
      "matched": 60,
      "unmatched_graph": 90,
      "unmatched_api": 88,
      "market_divergences": 45
    }
  ],
  "validation_results": [...]
}
```

## Metrics

### Match Rate
Percentage of trades that match between Graph and API on:
- Market ID (or resolvable market)
- Side (BUY/SELL)
- Timestamp (within 60s tolerance)
- Size (within 1% tolerance)

### Market ID Divergences
Trades where the market_id differs between sources but other fields match. This is the primary indicator of token catalog coverage gaps.

### Unmatched Trades
Trades present in one source but not the other. High unmatched rates indicate:
- Data source gaps (one source missing data)
- Severe market_id resolution failures
- Timestamp/size mismatches beyond tolerance

## Usage

### Generate Test Set

```bash
# Using API as Source B
polymarket compare-trades \
  --traders 0xabc123,0xdef456,0x789...,0x...,0x...,0x...,0x...,0x...,0x...,0x... \
  --output-dir ./data/graph_api_comparison

# Using JBecker dataset as Source B
polymarket compare-trades \
  --traders 0xabc123,0xdef456,... \
  --output-dir ./data/graph_api_comparison \
  --source-b jbecker
```

### Interpret Results

**Expected (before token catalog fix):**
- Match rate: 40-50% (matching current production)
- Market divergences: High (60%+ of Graph trades use synthetic `graph_<tx>_<asset>` IDs)
- Unmatched Graph: High (trades can't be matched to markets)

**Expected (after token catalog fix):**
- Match rate: 85%+ (approaching API/JBecker as ground truth)
- Market divergences: Low (<10%)
- Unmatched Graph: Low (<15%, mostly real data gaps)

## Next Steps

1. **Generate test set** with 10 representative traders
2. **Analyze divergences** to identify top failure modes
3. **Fix token catalog** coverage with test set as validation
4. **Re-run comparison** to confirm improvement
5. **Use validation set** to ensure solution generalizes

## Troubleshooting

### Graph API Key Error
Ensure `THE_GRAPH_API_KEY` is set in `.env` or environment.

### JBecker Dataset Not Found
Download from https://s3.jbecker.dev/data.tar.zst and extract to configured path.

### Low Match Rate (<10%)
Check if traders have activity in both sources. Some traders may only exist in one dataset.
