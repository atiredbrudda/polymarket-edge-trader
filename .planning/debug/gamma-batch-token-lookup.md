# Debug Summary: Gamma API Batch Token Lookup

## Probe Results (2026-02-18)

### API Variants Tested

| Variant | Format | Result |
|---------|--------|--------|
| Single token | `clob_token_ids=TOKEN1` | 1 market (baseline works) |
| Repeated params | `clob_token_ids=TOKEN1&clob_token_ids=TOKEN2` | 1 market (BROKEN - only returns one) |
| Comma-separated | `clob_token_ids=TOKEN1,TOKEN2` | 2 markets (WORKS!) |
| Comma-separated (3 tokens) | `clob_token_ids=TOKEN1,TOKEN2,TOKEN3` | 2 markets (correct - 2 tokens share a market) |

### Decision

**Batch works with comma-separated format.**

Implementing Step 2A: Batch lookup with `BATCH_SIZE=20`.

## Expected Performance

| Trader | Unknown Tokens | Before (sequential) | After (batch=20) | Speedup |
|--------|---------------|---------------------|------------------|---------|
| 1      | 15            | 8.6s                | ~0.4s            | ~20x    |
| 2      | 565           | 207.2s              | ~10.2s           | ~20x    |
| 3      | 164           | 59.4s               | ~3.0s            | ~20x    |

Calculation: `tokens / 20 batches * 0.36s per batch`

## Implementation

Modified `src/pipeline/ingest.py` around line 1546-1611:
- Replaced per-token loop with batched approach
- Uses comma-separated format: `clob_token_ids=TOKEN1,TOKEN2,...`
- Preserves all existing logic for market insertion, deduplication, etc.
- One sleep per batch instead of per token

## Files Changed

- `src/pipeline/ingest.py` — Modified batch token lookup logic
- `tests/pipeline/test_ingest_jbecker.py` — Added batch tests
