# Worker Task: Shared Token Cache for Batch Backfill

## Branch Name
`worker/backfill-token-cache`

## Problem

Backfill is still slow (~2.5 min/trader) after the batch JBecker parquet optimization.
Root cause: `ingest_trader_history_jbecker()` does per-trader token lookups:
- Scans DB for token→condition and condition→category mappings on every trader
- Unknown tokens trigger a Gamma API call per token with `time.sleep(0.05)`
- 96 traders × 300 avg unknown tokens × 0.05s = ~24 minutes just for token lookups

## What Already Exists (do not re-implement)

A partial fix is in your working tree on `main` (uncommitted). When you create your branch,
it will carry over. **Commit it first** as your starting point, then add the missing pieces.

The partial fix in `src/pipeline/ingest.py` adds:
1. `_build_token_cache(session)` method — loads all token→condition and condition→category
   mappings from DB markets into two dicts and returns them as a tuple
2. `token_cache` optional param on `ingest_trader_history_jbecker()` — uses the provided
   cache instead of rebuilding from DB if given

## What to Build

### 1. Thread `token_cache` through `ingest_trader_history_hybrid()` — `src/pipeline/ingest.py`

Add optional param, pass it to the jbecker call:

```python
def ingest_trader_history_hybrid(
    self,
    trader_address: str,
    prefer_jbecker: bool = True,
    fill_gap_with_api: bool = True,
    fallback_to_graph: bool = True,
    fallback_to_blockchain: bool = True,
    prefetched_jbecker_trades: list[dict] | None = None,
    token_cache: tuple[dict[str, str], dict[str, str]] | None = None,  # ADD THIS
) -> dict:
```

In the body, pass it to `ingest_trader_history_jbecker()`:
```python
stats = self.ingest_trader_history_jbecker(
    trader_address,
    prefetched_trades=prefetched_jbecker_trades,
    token_cache=token_cache,  # ADD THIS
)
```

### 2. Build and share cache in `run_full_sweep()` — `src/pipeline/ingest.py`

Right after `traders_to_backfill = session.query(...)` (while that session is still open),
build the cache once:

```python
# Build token cache once for all traders (avoids N per-trader DB scans)
token_cache = None
if use_jbecker and self.jbecker_client and self.jbecker_client.is_available():
    token_cache = self._build_token_cache(session)
    logger.info(
        f"Built token cache: {len(token_cache[0])} tokens, {len(token_cache[1])} conditions"
    )
```

Then pass `token_cache=token_cache` to the `ingest_trader_history_hybrid()` call in the loop.

### 3. Build and share cache in CLI `backfill` command — `src/cli/commands.py`

In the multi-trader path, after the batch JBecker prefetch block, add:

```python
# Build token cache once for all traders (avoids N per-trader DB scans)
token_cache = None
if jbecker_client and jbecker_client.is_available():
    with get_session(session_factory) as session:
        token_cache = pipeline._build_token_cache(session)
    logger.info("Built token cache for backfill session")
```

Then pass `token_cache=token_cache` to the `pipeline.ingest_trader_history_hybrid()` call
in the multi-trader loop.

**Note:** The single-trader path (when `address` arg is given) does NOT need the cache —
it's not a loop, so there's nothing to share.

## Key Property: Growing Cache

The cache dicts are mutable Python dicts passed by reference. When `ingest_trader_history_jbecker()`
discovers an unknown token via Gamma API (writes `token_to_condition[token_id] = cid`), that write
appears in the shared dict. So Trader B skips re-querying tokens that Trader A already discovered.
This is better than a static pre-load — the cache grows during the run.

This is already how the code works — you don't need to do anything special for this, just make
sure the same dict object is passed to each call.

## Tests — `tests/pipeline/test_ingest_jbecker.py`

Add the following tests:

**Test 1: `_build_token_cache` loads from DB**
```
- Set up pipeline with DB containing 2 markets (1 with tokens JSON, 1 without)
- Call _build_token_cache(session)
- Assert token_to_condition has entries from the tokenized market
- Assert condition_to_category has entries for both markets
```

**Test 2: `ingest_trader_history_jbecker` skips DB scan when cache provided**
```
- Patch session.query to raise if called for Market (should not be called)
- Call ingest_trader_history_jbecker(..., token_cache=({}, {}))
- Assert no exception (cache was used, DB not queried for tokens)
```

**Test 3: `ingest_trader_history_hybrid` passes token_cache through**
```
- Patch ingest_trader_history_jbecker to capture its kwargs
- Call ingest_trader_history_hybrid(..., token_cache=some_cache)
- Assert ingest_trader_history_jbecker was called with token_cache=some_cache
```

**Test 4: Cache is enriched during processing (growing cache)**
```
- Start with empty token_cache dicts
- Call ingest_trader_history_jbecker with a trade that has an unknown token
- Mock Gamma API to return a condition for that token
- Assert the token_cache dict has the new token after the call
```

## Validation

Run `bash scripts/worker_validate.sh` before pushing. Expected: same 7 pre-existing failures,
591 passed, 0 new regressions.

Check for mocks of `ingest_trader_history_hybrid` that may need updating:
```
grep -r "ingest_trader_history_hybrid" tests/ --include="*.py"
```
The new `token_cache` param is optional (None default) so existing mocks should not need changes.
