# Plan: Fix 9 Pre-existing Test Failures

## Overview

9 tests have been failing on main since the Data API migration and JBecker integration rewrote core ingestion methods. All failures are **mock mismatches** — the production code works correctly, but older tests still mock the old interfaces.

**Baseline:** 9 failed, 585 passed (both main and worker/fix-lsp-errors)

---

## Group A: API Client — Mock targets wrong endpoint (2 tests)

**Files:** `tests/test_api_client.py`
**Tests:**
1. `test_get_market_trades_returns_trades` (line 114)
2. `test_get_market_trades_pagination` (line ~150)

**Root cause:** Tests mock `ClobClient.get_trades()` (the old py-clob-client method), but `get_market_trades()` was rewritten to use the public Data API via `httpx.get("https://data-api.polymarket.com/trades?market=...")` (see `src/api/client.py:191`). The ClobClient mock is never called, so 0 trades are returned.

Additionally, the old mock data uses `{"id": "trade-1", "market": "0xabc", "maker": "0x..."}` format, but the new code expects Data API format with `conditionId`, `proxyWallet`, `transactionHash`, etc., and performs `conditionId` filtering (line 205).

**Fix:**
1. Replace `@patch("src.api.client.ClobClient")` with `@patch("httpx.get")` (or use `respx` library)
2. Mock response should return JSON matching Data API schema:
   ```python
   mock_response.json.return_value = [
       {
           "transactionHash": "0x...",
           "conditionId": "0xabc",  # Must match the queried condition_id
           "proxyWallet": "0x742d...",
           "side": "BUY",
           "size": 100.5,
           "price": 0.65,
           "timestamp": 1707220800,
           "outcome": "Yes",
       }
   ]
   mock_response.status_code = 200
   ```
3. The `conditionId` in mock data MUST match the `condition_id` passed to `get_market_trades()`, otherwise the filter on line 205 will skip all trades
4. Verify `response.raise_for_status()` is handled by the mock

**Estimated effort:** ~30 min

---

## Group B: discover_traders needs Market in DB (2 tests)

**Files:** `tests/test_ingest.py`
**Tests:**
3. `test_discover_traders_finds_addresses` (line ~170)
4. `test_discover_traders_skips_existing` (line 206)

**Root cause:** `discover_traders_from_market("market1")` now requires the market to already exist in the database (line 714: `session.query(Market).filter_by(condition_id=condition_id).first()`). If not found, it logs a warning and returns `[]`. The tests mock `get_market_trades` correctly but never insert a `Market` row into the in-memory DB.

**Fix:**
1. Add a Market to the in-memory DB before calling `discover_traders_from_market`:
   ```python
   session = session_factory()
   market = Market(
       condition_id="market1",
       question="Test market",
       category="eSports",
       active=True,
   )
   session.add(market)
   session.commit()
   session.close()
   ```
2. Both tests use `condition_id="market1"` so the same fixture pattern works for both
3. Consider creating a shared `market_fixture` to avoid duplication

**Estimated effort:** ~15 min

---

## Group C: ingest_trader_history mock session not iterable (3 tests)

**Files:** `tests/test_ingest.py`
**Tests:**
5. `test_ingest_trader_history_routes_correctly` (line 260)
6. `test_duplicate_trade_skipped` (line 353)
7. `test_ingest_trader_history_handles_no_trades` (line 507)

**Root cause:** `ingest_trader_history()` now calls `self._get_esports_market_ids(session)` (line 898) which runs:
```python
session.query(MarketClassification.market_id)
    .join(TaxonomyNode, ...)
    .filter(TaxonomyNode.slug.like("esports%"))
    .all()
```
The in-memory DB has the `MarketClassification` and `TaxonomyNode` tables (created by `Base.metadata.create_all`), but they're empty. The `_get_esports_market_ids` helper wraps this in try/except, so it should return an empty set gracefully.

However, the actual error is `TypeError: 'Mock' object is not iterable` at line 844: `market_ids = list(set(trade.market for trade in all_trader_trades))`. This means `all_trader_trades` is a Mock, not a list. The issue is that `client.get_market_trades` returns a Mock (not a list) because the mock's `side_effect` doesn't cover all called condition_ids, or the pipeline's internal flow changed.

Looking at the test setup: `mock_client.get_market_trades.side_effect = mock_get_market_trades` handles "market1" and "market2". But the pipeline now fetches trades differently — it iterates markets from the DB query, not from the mock setup.

**Fix:**
1. The pipeline now calls `client.get_market_trades()` for each market the trader has positions in. Since these tests don't create positions, the pipeline tries to get trades via the API client's method differently than expected.
2. Need to trace the exact call path in `ingest_trader_history()` to understand what `all_trader_trades` comes from — it's likely `client.get_trades()` (the CLOB method for authenticated user's trades) which returns a Mock object.
3. The fix is to properly mock the trader's trade fetching path. Since the pipeline was rewritten to use the Data API, the mock needs to intercept `httpx.get` calls or the specific method the pipeline uses to fetch trader trades.
4. Alternatively, these tests may need to be restructured to match the new pipeline flow:
   - Create markets in DB
   - Mock the HTTP-level trade fetching
   - Verify routing still works

**Estimated effort:** ~45 min (most complex group — requires understanding the new pipeline flow)

---

## Group D: hybrid signature changed (2 tests)

**Files:** `tests/pipeline/test_ingest_blockchain.py`
**Tests:**
8. `test_ingest_trader_history_hybrid_prefers_blockchain` (line ~270)
9. `test_ingest_trader_history_hybrid_falls_back_to_api` (line ~295)

**Root cause:** Tests call `pipeline.ingest_trader_history_hybrid(trader_address, prefer_blockchain=True)` but the method signature changed to:
```python
def ingest_trader_history_hybrid(
    self, trader_address: str,
    prefer_jbecker: bool = True,
    fill_gap_with_api: bool = True,
    fallback_to_graph: bool = True,
)
```
The `prefer_blockchain` parameter no longer exists.

**Fix:**
1. Remove `prefer_blockchain=True` from both test calls
2. Update test logic to match the new JBecker-first hybrid flow:
   - Test 8 ("prefers blockchain"): Should now test that JBecker is preferred first. Mock `jbecker_client.query_trader_history` to return trades, verify it's called before blockchain.
   - Test 9 ("falls back to API"): Should test fallback chain: JBecker → API → Graph. Mock JBecker to fail, API to return trades, verify fallback works.
3. If the tests are meant to test blockchain specifically, they may need `fallback_to_graph=False` or the blockchain client needs to be added to the hybrid flow.

**Estimated effort:** ~30 min

---

## Execution Order

1. **Group B first** (easiest — just add Market rows to fixtures)
2. **Group D next** (signature fix + assertion updates)
3. **Group A next** (mock target change, straightforward)
4. **Group C last** (most complex, may require deeper pipeline tracing)

## Validation

After all fixes:
```bash
source .venv/bin/activate
python -m pytest tests/ --tb=short -q
```

**Target:** 0 failed, 594 passed (585 + 9 fixed)
