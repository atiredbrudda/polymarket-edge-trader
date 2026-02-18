# Worker Task: Gamma API Batch Token Lookup

## Branch Name
`worker/gamma-batch-token-lookup`

## Context

Backfill performance after the two batch optimizations (parquet scan + token cache):

| Trader | Unknown Tokens | Time   |
|--------|---------------|--------|
| 1      | 15            | 8.6s   |
| 2      | 565           | 207.2s |
| 3      | 164           | 59.4s  |

The remaining bottleneck is N sequential Gamma API calls for unknown tokens.
Each call costs ~0.31s in network latency + 0.05s sleep = ~0.36s/token.
For Trader 2: 565 × 0.36s ≈ 203s — almost all of their 207.2s.

Reducing the sleep has minimal impact (~11%). The only significant fix is reducing
the number of API calls — i.e., querying multiple tokens per request.

## Step 1: Probe the Gamma API (do this first, before writing code)

The current call is:
```
GET https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}
```

Test whether it accepts multiple tokens in a single request. Try these variants:

```bash
# Repeated params
curl "https://gamma-api.polymarket.com/markets?clob_token_ids=TOKEN1&clob_token_ids=TOKEN2"

# Comma-separated
curl "https://gamma-api.polymarket.com/markets?clob_token_ids=TOKEN1,TOKEN2"
```

Use two real token IDs from the DB to test:
```bash
source .venv/bin/activate
python -c "
from src.db.session import get_session_factory
from src.db.models import Market
import json
sf = get_session_factory()
s = sf()
markets = s.query(Market).filter(Market.tokens.isnot(None)).limit(3).all()
for m in markets:
    tokens = json.loads(m.tokens)
    print([t['token_id'] for t in tokens[:2]])
s.close()
"
```

**Decision point:**
- If batch works → implement batch lookup (see Step 2A)
- If batch doesn't work → implement sleep reduction only (see Step 2B)

Document the probe result in the debug summary before writing any code.

## Step 2A: If batch lookup works

Modify `ingest_trader_history_jbecker()` in `src/pipeline/ingest.py`
(around line 1546 — the `if unknown_tokens and self.gamma_client:` block).

Replace the per-token loop with a batched approach:

```python
BATCH_SIZE = 20  # tune based on API limits — start conservative

if unknown_tokens and self.gamma_client:
    token_list = list(unknown_tokens)
    for i in range(0, len(token_list), BATCH_SIZE):
        batch = token_list[i:i + BATCH_SIZE]
        try:
            resp = httpx.get(
                "https://gamma-api.polymarket.com/markets",
                params=[("clob_token_ids", t) for t in batch],
                timeout=10,
            )
            if resp.status_code == 200:
                for md in resp.json():
                    # process each market result (same logic as before)
                    ...
        except Exception as e:
            logger.debug(f"Batch token lookup failed: {e}")
        time.sleep(0.05)  # one sleep per batch, not per token
```

Key things to preserve:
- The existing logic for writing new markets to the DB (unchanged)
- The `token_to_condition` and `condition_to_category` mutations (unchanged)
- The `seen_conditions` deduplication guard (unchanged)
- Exception handling + session rollback on failure (unchanged)

Expected speedup for Trader 2 with batch=20:
- 565 tokens → 29 batches × 0.36s = ~10s (vs 207s) — **~20x speedup**

## Step 2B: If batch lookup does NOT work

Fall back to reducing the sleep only:

```python
time.sleep(0.01)  # was 0.05 — saves ~22% but network latency still dominates
```

This is a 2-line change. Still worth doing as a minor improvement.
Document clearly in the debug summary that batch was attempted and failed.

## Debug Summary

Create `.planning/debug/gamma-batch-token-lookup.md` documenting:
- Which batch variants were tested and what the API returned
- Whether batch works (and with what param format)
- Chosen approach and why
- Performance before/after (estimate or measured)

## Tests

**If Step 2A (batch implemented):**

In `tests/pipeline/test_ingest_jbecker.py`, add 2 tests:

1. **Batch groups tokens correctly**
   - Provide 45 unknown tokens
   - Mock `httpx.get` to capture calls
   - Verify httpx.get called 3 times (ceil(45/20) = 3 batches), not 45 times
   - Verify each call has multiple `clob_token_ids` params

2. **Batch processes all responses**
   - Mock httpx.get returning 2 markets per batch
   - Verify all discovered condition IDs end up in `token_to_condition`

**If Step 2B (sleep reduction only):**

No new tests needed — existing token cache tests cover the lookup path.
Just note the change in the debug summary.

## Validation

Run `bash scripts/worker_validate.sh` before pushing.
Expected: 602 passed (or more if new tests added), 0 new regressions.

Check mocks of anything you changed:
```
grep -r "httpx.get\|gamma-api.polymarket.com/markets" tests/ --include="*.py"
```
