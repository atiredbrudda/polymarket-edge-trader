---
phase: 99-pipeline-todos
plan: 05
type: execute
wave: 1
depends_on: [pipeline-todo-04]
files_modified:
  - src/polymarket_analytics/api/graph.py
  - src/polymarket_analytics/api/data.py
  - src/polymarket_analytics/commands/backfill.py
  - tests/test_graph.py
  - tests/test_incremental_backfill.py
autonomous: true

must_haves:
  truths:
    - "GraphAPIClient.fetch_trader_trades accepts since_unix_ts and passes timestamp_gte to GraphQL where clause"
    - "DataAPIClient.fetch_user_trades accepts since_unix_ts and stops pagination early when old trades are encountered"
    - "backfill_trader reads last_trade_seen_at from DB and passes since_unix_ts to both API clients"
    - "Traders with NULL last_trade_seen_at get a full fetch (since_unix_ts=None)"
  artifacts:
    - path: "src/polymarket_analytics/api/graph.py"
      provides: "fetch_trader_trades with since_unix_ts param"
      contains: "timestamp_gte"
    - path: "src/polymarket_analytics/api/data.py"
      provides: "fetch_user_trades with since_unix_ts early-exit pagination"
      contains: "since_unix_ts"
    - path: "src/polymarket_analytics/commands/backfill.py"
      provides: "backfill_trader wired to pass since_unix_ts from last_trade_seen_at"
      contains: "since_unix_ts"
  key_links:
    - from: "src/polymarket_analytics/commands/backfill.py"
      to: "src/polymarket_analytics/api/graph.py"
      via: "backfill_trader passes since_unix_ts to fetch_trader_trades"
      pattern: "since_unix_ts"
    - from: "src/polymarket_analytics/commands/backfill.py"
      to: "src/polymarket_analytics/api/data.py"
      via: "backfill_trader passes since_unix_ts to fetch_user_trades"
      pattern: "since_unix_ts"
---

<objective>
Eliminate full re-fetch on every backfill run by passing last_trade_seen_at as a time filter to both API clients, so only new trades are pulled.

Currently both the Graph API and Data API re-fetch complete trade history on every run, making backfill take hours for 4000+ traders. The traders table already stores last_trade_seen_at (added in Todo #2). This plan wires it as a time filter.

Output: Graph API gets timestamp_gte in its GraphQL where clause. Data API stops pagination early when it hits old trades. backfill_trader reads last_trade_seen_at per trader and passes it to both clients. First-time backfills (NULL last_trade_seen_at) are unaffected.
</objective>

<execution_context>
@/Users/macbookair/.claude/get-shit-done/workflows/execute-plan.md
@/Users/macbookair/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@src/polymarket_analytics/api/graph.py
@src/polymarket_analytics/api/data.py
@src/polymarket_analytics/commands/backfill.py
</context>

<interfaces>
<!-- Exact signatures and code locations the executor needs. No exploration required. -->

**graph.py — GraphAPIClient.fetch_trader_trades (line 175)**
Current signature:
```python
async def fetch_trader_trades(self, trader_address: str, batch_size: int = 100) -> List[dict]:
```
The `_paginate` closure (line 207) builds two query strings — one for the first page (no `id_gt`) and one for subsequent pages (with `id_gt`). Both use:
```python
where: {{ {role}: "{trader_address.lower()}" }}
```

**data.py — DataAPIClient.fetch_user_trades (line 155)**
Current signature:
```python
async def fetch_user_trades(self, trader_address: str, limit: int = 1000) -> List[dict]:
```
Uses offset-based pagination. After each page: `if len(trades) < limit: break`. Assumes newest-first ordering (standard for this API).

**backfill.py — backfill_trader (line 180)**
Current signature:
```python
async def backfill_trader(db, trader_address, data_client, graph_client) -> Dict[str, int]:
```
Calls `fetch_user_trades(trader_address)` (line 204) and `fetch_trader_trades(trader_address)` (line 229).

**backfill.py — backfill_async traders query (line 425)**
Current query fetches only `address`. Change to also fetch `last_trade_seen_at`:
```python
traders = list(db.execute("""
    SELECT address FROM traders
    WHERE ...
""").fetchall())
```
Loop at line 482 unpacks `trader_address = trader[0]`.
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Add since_unix_ts to GraphAPIClient.fetch_trader_trades</name>
  <files>src/polymarket_analytics/api/graph.py</files>
  <action>
1. Update `fetch_trader_trades` signature to add `since_unix_ts: Optional[int] = None`:
```python
async def fetch_trader_trades(
    self, trader_address: str, batch_size: int = 100, since_unix_ts: Optional[int] = None
) -> List[dict]:
```

2. Inside `_paginate`, build a timestamp clause string before the while loop:
```python
ts_clause = f', timestamp_gte: "{since_unix_ts}"' if since_unix_ts is not None else ""
```

3. Update the first-page query where clause from:
```python
where: {{ {role}: "{trader_address.lower()}" }}
```
to:
```python
where: {{ {role}: "{trader_address.lower()}"{ts_clause} }}
```

4. Update the subsequent-page query where clause from:
```python
where: {{ {role}: "{trader_address.lower()}", id_gt: "{last_id}" }}
```
to:
```python
where: {{ {role}: "{trader_address.lower()}", id_gt: "{last_id}"{ts_clause} }}
```

The `ts_clause` variable is captured by the `_paginate` closure via Python's closure semantics — no additional wiring needed since `since_unix_ts` is in the enclosing `fetch_trader_trades` scope.

Update the docstring to mention `since_unix_ts: Optional unix timestamp — if set, only fetch trades at or after this time`.
  </action>
  <verify>
    <automated>cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2 && python -c "
import inspect
from polymarket_analytics.api.graph import GraphAPIClient
sig = inspect.signature(GraphAPIClient.fetch_trader_trades)
assert 'since_unix_ts' in sig.parameters, 'since_unix_ts param missing'
import ast, textwrap
src = inspect.getsource(GraphAPIClient.fetch_trader_trades)
assert 'timestamp_gte' in src, 'timestamp_gte not in source'
print('OK')
"
</automated>
  </verify>
  <done>fetch_trader_trades accepts since_unix_ts. When set, timestamp_gte appears in both first-page and subsequent-page where clauses inside _paginate. When None, query is identical to current behavior.</done>
</task>

<task type="auto">
  <name>Task 2: Add since_unix_ts early-exit pagination to DataAPIClient.fetch_user_trades</name>
  <files>src/polymarket_analytics/api/data.py</files>
  <action>
1. Update `fetch_user_trades` signature to add `since_unix_ts: Optional[int] = None`:
```python
async def fetch_user_trades(
    self, trader_address: str, limit: int = 1000, since_unix_ts: Optional[int] = None
) -> List[dict]:
```

2. Inside the pagination while loop, replace the block starting with `all_trades.extend(trades)` through `offset += limit`. The full replacement shows the complete loop tail so `offset += limit` placement is unambiguous:

Replace:
```python
            all_trades.extend(trades)

            # If we got fewer than limit, we've reached the end
            if len(trades) < limit:
                break

            offset += limit
```
with:
```python
            hit_boundary = False
            if since_unix_ts is not None:
                filtered = [t for t in trades if int(t.get("timestamp") or 0) >= since_unix_ts]
                if len(filtered) < len(trades):
                    hit_boundary = True
                all_trades.extend(filtered)
            else:
                all_trades.extend(trades)

            if hit_boundary or len(trades) < limit:
                break

            offset += limit
```

This assumes newest-first ordering (standard for the Polymarket Data API). When a page contains trades older than `since_unix_ts`, we've reached the historical boundary — keep the new ones and stop. When `since_unix_ts` is None the behavior is identical to current.

Update the docstring to mention `since_unix_ts: Optional unix timestamp — if set, stop pagination when trades older than this are encountered (assumes newest-first ordering)`.
  </action>
  <verify>
    <automated>cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2 && python -c "
import inspect
from polymarket_analytics.api.data import DataAPIClient
sig = inspect.signature(DataAPIClient.fetch_user_trades)
assert 'since_unix_ts' in sig.parameters, 'since_unix_ts param missing'
src = inspect.getsource(DataAPIClient.fetch_user_trades)
assert 'hit_boundary' in src, 'hit_boundary logic missing'
print('OK')
"
</automated>
  </verify>
  <done>fetch_user_trades accepts since_unix_ts. When set, pages are filtered to trades >= since_unix_ts and pagination stops at the boundary. When None, behavior is identical to current.</done>
</task>

<task type="auto">
  <name>Task 3: Wire since_unix_ts through backfill_trader and backfill_async</name>
  <files>src/polymarket_analytics/commands/backfill.py</files>
  <action>
**3a. Update backfill_trader signature** to accept since_unix_ts:
```python
async def backfill_trader(
    db: Any,
    trader_address: str,
    data_client: DataAPIClient,
    graph_client: GraphAPIClient,
    since_unix_ts: Optional[int] = None,
) -> Dict[str, int]:
```

**3b. Pass since_unix_ts to both API calls** inside backfill_trader.

Change (line 204):
```python
api_trades = await fetch_trades_with_retry(data_client, trader_address)
```
to:
```python
api_trades = await fetch_trades_with_retry(data_client, trader_address, since_unix_ts=since_unix_ts)
```

Change (line 229):
```python
graph_events = await graph_client.fetch_trader_trades(trader_address)
```
to:
```python
graph_events = await graph_client.fetch_trader_trades(trader_address, since_unix_ts=since_unix_ts)
```

**3c. Update fetch_trades_with_retry** to accept and forward since_unix_ts.

Current signature (line 126):
```python
async def fetch_trades_with_retry(client, trader_address, max_retries=10, base_delay=1.0, max_delay=30.0):
```
Add `since_unix_ts: Optional[int] = None` and forward it:
```python
trades = await client.fetch_user_trades(trader_address, since_unix_ts=since_unix_ts)
```

**3d. Update the traders query in backfill_async** to also fetch last_trade_seen_at.

Change (line 425):
```python
traders = list(
    db.execute(
        """
    SELECT address FROM traders
    WHERE
        (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
        AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
""",
        {"cutoff": cutoff, "threshold": threshold},
    ).fetchall()
)
```
to:
```python
traders = list(
    db.execute(
        """
    SELECT address, last_trade_seen_at FROM traders
    WHERE
        (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
        AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
""",
        {"cutoff": cutoff, "threshold": threshold},
    ).fetchall()
)
```

**3e. Update the loop body** to compute since_unix_ts and pass it.

Change (line 482):
```python
trader_address = trader[0]
```
to:
```python
trader_address = trader[0]
last_trade_seen_at = trader[1]

since_unix_ts: Optional[int] = None
if last_trade_seen_at:
    try:
        dt = datetime.fromisoformat(last_trade_seen_at.replace("Z", "+00:00"))
        since_unix_ts = int(dt.timestamp())
    except Exception:
        pass
```

And change the backfill_trader call (line 490):
```python
stats = await backfill_trader(
    db,
    trader_address,
    data_client,
    graph_client,
)
```
to:
```python
stats = await backfill_trader(
    db,
    trader_address,
    data_client,
    graph_client,
    since_unix_ts=since_unix_ts,
)
```

Note: `Optional` is already imported at the top of backfill.py. `datetime` and `fromisoformat` are already used in the file.
  </action>
  <verify>
    <automated>cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2 && python -c "
import inspect
from polymarket_analytics.commands.backfill import backfill_trader, fetch_trades_with_retry
sig = inspect.signature(backfill_trader)
assert 'since_unix_ts' in sig.parameters, 'backfill_trader missing since_unix_ts'
sig2 = inspect.signature(fetch_trades_with_retry)
assert 'since_unix_ts' in sig2.parameters, 'fetch_trades_with_retry missing since_unix_ts'
src = inspect.getsource(backfill_trader)
assert 'since_unix_ts' in src, 'since_unix_ts not forwarded in backfill_trader'
src2 = inspect.getsource(fetch_trades_with_retry)
assert 'since_unix_ts' in src2, 'fetch_trades_with_retry body does not forward since_unix_ts to fetch_user_trades'
print('OK')
"
</automated>
  </verify>
  <done>backfill_trader and fetch_trades_with_retry accept since_unix_ts and forward it. backfill_async reads last_trade_seen_at per trader, converts to unix ts, passes to backfill_trader. Traders with NULL last_trade_seen_at get since_unix_ts=None (full fetch, unchanged behavior).</done>
</task>

<task type="auto">
  <name>Task 4: Tests for incremental fetch behavior</name>
  <files>tests/test_graph.py, tests/test_incremental_backfill.py</files>
  <action>
**4a. Extend tests/test_graph.py** — add a new class `TestFetchTraderTradesTimestampFilter` after the existing `TestFetchTraderTradesQuery` class:

```python
class TestFetchTraderTradesTimestampFilter:
    """timestamp_gte is included in GraphQL where clause when since_unix_ts is set."""

    def _make_response(self, events):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"orderFilledEvents": events}}
        return mock_resp

    @pytest.mark.asyncio
    async def test_timestamp_gte_in_query_when_since_set(self):
        """When since_unix_ts is set, timestamp_gte appears in the GraphQL where clause."""
        from polymarket_analytics.api.graph import GraphAPIClient

        responses = [
            self._make_response([]),  # maker page 1 (empty → stops)
            self._make_response([]),  # taker page 1 (empty → stops)
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=responses)

        client = GraphAPIClient()
        client._client = mock_client

        await client.fetch_trader_trades("0xtrader", since_unix_ts=1700000000)

        assert mock_client.post.call_count == 2
        for call in mock_client.post.call_args_list:
            payload = call[1]["json"] if call[1] else call[0][1]
            query_text = payload["query"]
            assert "timestamp_gte" in query_text, "timestamp_gte must appear when since_unix_ts set"
            assert "1700000000" in query_text, "since_unix_ts value must appear in query"

    @pytest.mark.asyncio
    async def test_no_timestamp_filter_when_since_none(self):
        """When since_unix_ts is None, timestamp_gte is absent from the query."""
        from polymarket_analytics.api.graph import GraphAPIClient

        responses = [
            self._make_response([]),
            self._make_response([]),
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=responses)

        client = GraphAPIClient()
        client._client = mock_client

        await client.fetch_trader_trades("0xtrader", since_unix_ts=None)

        for call in mock_client.post.call_args_list:
            payload = call[1]["json"] if call[1] else call[0][1]
            query_text = payload["query"]
            assert "timestamp_gte" not in query_text, "timestamp_gte must be absent when since_unix_ts=None"
```

**4b. Create tests/test_incremental_backfill.py**:

```python
"""Tests for incremental backfill — since_unix_ts early-exit pagination."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDataAPIIncrementalFetch:
    """DataAPIClient.fetch_user_trades stops pagination early when since_unix_ts is set."""

    def _make_response(self, trades):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = trades
        return mock_resp

    @pytest.mark.asyncio
    async def test_stops_at_historical_boundary(self):
        """Stops pagination when a page contains a trade older than since_unix_ts."""
        from polymarket_analytics.api.data import DataAPIClient

        since_ts = 1700000000
        # Page 1: 2 new trades (>= since_ts) → full page (limit=2) but all new → continue
        # Page 2: 1 new + 1 old → hit boundary → stop, return only the new one
        page1 = [
            {"asset": "tok1", "side": "BUY", "price": "0.5", "size": "10", "timestamp": 1700000100},
            {"asset": "tok1", "side": "BUY", "price": "0.5", "size": "10", "timestamp": 1700000050},
        ]
        page2 = [
            {"asset": "tok1", "side": "SELL", "price": "0.6", "size": "5", "timestamp": 1700000010},
            {"asset": "tok1", "side": "SELL", "price": "0.4", "size": "5", "timestamp": 1699999999},  # old
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=[
            self._make_response(page1),
            self._make_response(page2),
        ])

        client = DataAPIClient()
        client._client = mock_client

        result = await client.fetch_user_trades("0xtrader", limit=2, since_unix_ts=since_ts)

        # Should return 3 trades (2 from page1 + 1 new from page2), not 4
        assert len(result) == 3
        # Old trade must be excluded
        timestamps = [t["timestamp"] for t in result]
        assert 1699999999 not in timestamps

    @pytest.mark.asyncio
    async def test_no_early_exit_when_since_none(self):
        """When since_unix_ts is None, all pages are fetched without filtering."""
        from polymarket_analytics.api.data import DataAPIClient

        page1 = [
            {"asset": "tok1", "side": "BUY", "price": "0.5", "size": "10", "timestamp": 1700000100},
            {"asset": "tok1", "side": "BUY", "price": "0.5", "size": "10", "timestamp": 1699000000},  # old
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=self._make_response(page1))

        client = DataAPIClient()
        client._client = mock_client

        result = await client.fetch_user_trades("0xtrader", limit=2, since_unix_ts=None)

        # Both trades returned (no filtering)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_full_fetch_when_all_trades_new(self):
        """When all trades are newer than since_unix_ts, pagination continues normally."""
        from polymarket_analytics.api.data import DataAPIClient

        since_ts = 1699000000
        page1 = [
            {"asset": "tok1", "side": "BUY", "price": "0.5", "size": "10", "timestamp": 1700000100},
            {"asset": "tok1", "side": "BUY", "price": "0.5", "size": "10", "timestamp": 1700000050},
        ]
        page2 = [
            {"asset": "tok1", "side": "SELL", "price": "0.6", "size": "5", "timestamp": 1699500000},
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=[
            self._make_response(page1),
            self._make_response(page2),
        ])

        client = DataAPIClient()
        client._client = mock_client

        result = await client.fetch_user_trades("0xtrader", limit=2, since_unix_ts=since_ts)

        # All 3 trades are >= since_ts → all returned
        assert len(result) == 3


class TestBackfillTraderSinceTs:
    """backfill_trader passes since_unix_ts from last_trade_seen_at."""

    @pytest.mark.asyncio
    async def test_null_last_trade_gives_full_fetch(self, tmp_path):
        """Trader with NULL last_trade_seen_at gets since_unix_ts=None (full fetch)."""
        from polymarket_analytics.api.data import DataAPIClient
        from polymarket_analytics.api.graph import GraphAPIClient
        from polymarket_analytics.commands.backfill import backfill_trader
        from polymarket_analytics.db.schema import init_database

        db = init_database(tmp_path / "test.db")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db["traders"].insert({
            "address": "0xtrader",
            "first_seen": now, "last_seen": now, "backfill_complete": False,
            "created_at": now, "last_backfilled_at": None, "last_trade_seen_at": None,
        })

        mock_data = AsyncMock(spec=DataAPIClient)
        mock_data.fetch_user_trades = AsyncMock(return_value=[])
        mock_graph = AsyncMock(spec=GraphAPIClient)
        mock_graph.fetch_trader_trades = AsyncMock(return_value=[])

        await backfill_trader(db, "0xtrader", mock_data, mock_graph, since_unix_ts=None)

        mock_data.fetch_user_trades.assert_called_once()
        call_kwargs = mock_data.fetch_user_trades.call_args
        # since_unix_ts=None means full fetch
        passed_since = call_kwargs[1].get("since_unix_ts") if call_kwargs[1] else None
        assert passed_since is None

    @pytest.mark.asyncio
    async def test_existing_last_trade_gives_incremental_fetch(self, tmp_path):
        """Trader with last_trade_seen_at gets since_unix_ts set in API calls."""
        from polymarket_analytics.api.data import DataAPIClient
        from polymarket_analytics.api.graph import GraphAPIClient
        from polymarket_analytics.commands.backfill import backfill_trader
        from polymarket_analytics.db.schema import init_database

        db = init_database(tmp_path / "test.db")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        last_seen = "2026-04-01T00:00:00+00:00"
        expected_ts = int(datetime.fromisoformat(last_seen).timestamp())

        db["traders"].insert({
            "address": "0xtrader",
            "first_seen": now, "last_seen": now, "backfill_complete": True,
            "created_at": now, "last_backfilled_at": now, "last_trade_seen_at": last_seen,
        })

        mock_data = AsyncMock(spec=DataAPIClient)
        mock_data.fetch_user_trades = AsyncMock(return_value=[])
        mock_graph = AsyncMock(spec=GraphAPIClient)
        mock_graph.fetch_trader_trades = AsyncMock(return_value=[])

        # backfill_async is what reads last_trade_seen_at and converts it;
        # we pass since_unix_ts directly to backfill_trader here to test forwarding
        await backfill_trader(db, "0xtrader", mock_data, mock_graph, since_unix_ts=expected_ts)

        # Verify Graph client received the timestamp
        mock_graph.fetch_trader_trades.assert_called_once()
        graph_kwargs = mock_graph.fetch_trader_trades.call_args[1]
        assert graph_kwargs.get("since_unix_ts") == expected_ts
```
  </action>
  <verify>
    <automated>cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2 && python -m pytest tests/test_graph.py tests/test_incremental_backfill.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>All new tests pass. timestamp_gte appears in Graph queries when since_unix_ts is set. Data API early-exit stops at historical boundary. backfill_trader forwards since_unix_ts to both clients.</done>
</task>

</tasks>

<verification>
Run full test suite to confirm no regressions:

```bash
cd /Users/macbookair/Documents/project/test/rerun7/polymarketv2 && python -m pytest tests/ -x -q 2>&1 | tail -20
```

All existing tests must pass. New tests in test_graph.py and test_incremental_backfill.py must pass.
</verification>

<success_criteria>
1. GraphAPIClient.fetch_trader_trades accepts since_unix_ts; timestamp_gte appears in GraphQL where clause for both first and subsequent pages when set
2. DataAPIClient.fetch_user_trades accepts since_unix_ts; pagination stops early when a page contains trades older than the cutoff; old trades are filtered out
3. backfill_trader accepts and forwards since_unix_ts to both fetch_user_trades and fetch_trader_trades
4. backfill_async reads last_trade_seen_at per trader, converts ISO → unix ts, passes to backfill_trader
5. Traders with NULL last_trade_seen_at receive since_unix_ts=None (full fetch, unchanged behavior)
6. fetch_trades_with_retry forwards since_unix_ts to fetch_user_trades
7. All existing tests pass (no regressions)
</success_criteria>

<output>
After completion, create `.planning/phases/99-pipeline-todos/99-05-SUMMARY.md`
</output>
