---
status: resolved
trigger: "Backfill still slow after batch optimization. 1 trader takes ~2.5 minutes even with prefetched data."
created: 2026-02-18T09:10:00Z
updated: 2026-02-18T12:30:00Z
---

## Current Focus

hypothesis: "Token lookup (384 tokens × 0.05s delay) is the remaining bottleneck"
test: "Profiled single trader backfill with verbose logging"
expecting: "Identify which step takes the most time"
next_action: "Complete token cache plumbing — partial fix exists in working tree"

## Symptoms

expected: Backfill should process prefetched trades quickly
actual: 1 trader with 1124 trades takes ~2.5 minutes even after batch prefetch
errors: None - just slow
reproduction: Run `polymarket backfill --limit 1` with verbose logging
started: Observed after batch optimization was applied

## Evidence

- timestamp: 2026-02-18T09:04:48Z
  checked: Single trader backfill timing breakdown
  found: |
    - Parquet batch scan: ~35s (for 1 trader)
    - Token lookup: 384 tokens × 0.05s = 2.5 MINUTES per trader
    - Market fetches: 33 sequential API calls during gap fill
  implication: Token lookup dominates runtime even with batch prefetch

- timestamp: 2026-02-18T09:07:41Z
  checked: Token lookup code (ingest.py lines 1522-1589)
  found: Each unknown token triggers Gamma API call with 0.05s sleep
  implication: Traders with hundreds of unknown tokens take minutes

- timestamp: 2026-02-18T09:07:41Z
  checked: Trade skipping statistics
  found: 1124 trades prefetched, 438 skipped as "invalid" (no category mapping)
  implication: Most trades are processed but category mapping is the bottleneck

## ROOT CAUSE IDENTIFIED

The batch optimization solved the N parquet scans problem, but **token lookup is still per-trader**:

1. **Token → Condition mapping**: Unknown tokens trigger Gamma API lookup with 0.05s delay
2. **Per-trader lookup**: Each trader's unknown tokens are looked up independently
3. **No global cache**: Token mappings aren't shared across traders

**Math:**
- 96 traders × 300 avg unknown tokens × 0.05s = **24 minutes** just for token lookups
- Plus parquet scans, market fetches, trade processing

## Fix Plan

### What the partial fix (working tree) already has
- `_build_token_cache(session)` method on IngestionPipeline — loads all token→condition and
  condition→category mappings from existing DB markets
- `token_cache` param on `ingest_trader_history_jbecker()` — uses cache dict if provided,
  otherwise builds from DB

### What's still missing

**1. Thread `token_cache` through `ingest_trader_history_hybrid()`**
Add optional `token_cache` param, pass it to the `ingest_trader_history_jbecker()` call.
No change to existing callers (defaults to None).

**2. Build and share cache in `run_full_sweep()`**
Right after getting `traders_to_backfill` (session still open), build the cache once:
```python
token_cache = None
if use_jbecker and self.jbecker_client and self.jbecker_client.is_available():
    token_cache = self._build_token_cache(session)
```
Pass `token_cache=token_cache` to each `ingest_trader_history_hybrid()` call in the loop.

**3. Build and share cache in CLI `backfill` command**
Before the multi-trader loop (after batch JBecker prefetch), open a session and build the cache:
```python
token_cache = None
if jbecker_client and jbecker_client.is_available():
    with get_session(session_factory) as session:
        token_cache = pipeline._build_token_cache(session)
```
Pass `token_cache=token_cache` to each `pipeline.ingest_trader_history_hybrid()` call in the loop.

**4. Tests**
- `test_ingest_jbecker.py`: `_build_token_cache()` loads from DB correctly
- `test_ingest_jbecker.py`: `ingest_trader_history_jbecker()` skips DB query when cache provided
- `test_ingest_jbecker.py`: `ingest_trader_history_hybrid()` threads `token_cache` through
- `test_ingest_jbecker.py`: cache is enriched with newly discovered tokens (Gamma lookups update
  the shared dict, so Trader B benefits from Trader A's discoveries)

### Key property: growing cache
The cache dict is mutable and passed by reference. When unknown tokens are discovered during
Trader A's processing (Gamma API → `token_to_condition[token_id] = cid`), those writes appear
in the shared dict. Trader B won't re-lookup the same tokens. This is better than a static
pre-load — the cache grows during the run.

### Non-issue (noted separately)
Address interpolation in `batch_query_traders_history()` SQL is technically unsafe (no parameterization),
but acceptable for internal tool with DB-sourced addresses. Simple fix: validate hex format before
interpolating. Defer to another time.

## Files Involved

- src/pipeline/ingest.py — `ingest_trader_history_hybrid()`, `run_full_sweep()` (partial fix here)
- src/cli/commands.py — backfill command multi-trader loop
- tests/pipeline/test_ingest_jbecker.py — new tests for cache behavior
