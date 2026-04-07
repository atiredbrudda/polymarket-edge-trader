"""Tests for incremental backfill — since_unix_ts early-exit pagination."""

import pytest
from unittest.mock import AsyncMock, MagicMock


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
            {
                "asset": "tok1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "timestamp": 1700000100,
            },
            {
                "asset": "tok1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "timestamp": 1700000050,
            },
        ]
        page2 = [
            {
                "asset": "tok1",
                "side": "SELL",
                "price": "0.6",
                "size": "5",
                "timestamp": 1700000010,
            },
            {
                "asset": "tok1",
                "side": "SELL",
                "price": "0.4",
                "size": "5",
                "timestamp": 1699999999,
            },  # old
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=[
                self._make_response(page1),
                self._make_response(page2),
            ]
        )

        client = DataAPIClient()
        client._client = mock_client

        result = await client.fetch_user_trades(
            "0xtrader", limit=2, since_unix_ts=since_ts
        )

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
            {
                "asset": "tok1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "timestamp": 1700000100,
            },
            {
                "asset": "tok1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "timestamp": 1699000000,
            },  # old
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=[
                self._make_response(page1),
                self._make_response([]),  # second page empty → stops
            ]
        )

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
            {
                "asset": "tok1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "timestamp": 1700000100,
            },
            {
                "asset": "tok1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "timestamp": 1700000050,
            },
        ]
        page2 = [
            {
                "asset": "tok1",
                "side": "SELL",
                "price": "0.6",
                "size": "5",
                "timestamp": 1699500000,
            },
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=[
                self._make_response(page1),
                self._make_response(page2),
            ]
        )

        client = DataAPIClient()
        client._client = mock_client

        result = await client.fetch_user_trades(
            "0xtrader", limit=2, since_unix_ts=since_ts
        )

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
        db["traders"].insert(
            {
                "address": "0xtrader",
                "first_seen": now,
                "last_seen": now,
                "backfill_complete": False,
                "created_at": now,
                "last_backfilled_at": None,
                "last_trade_seen_at": None,
            }
        )

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

        db["traders"].insert(
            {
                "address": "0xtrader",
                "first_seen": now,
                "last_seen": now,
                "backfill_complete": True,
                "created_at": now,
                "last_backfilled_at": now,
                "last_trade_seen_at": last_seen,
            }
        )

        mock_data = AsyncMock(spec=DataAPIClient)
        mock_data.fetch_user_trades = AsyncMock(return_value=[])
        mock_graph = AsyncMock(spec=GraphAPIClient)
        mock_graph.fetch_trader_trades = AsyncMock(return_value=[])

        # backfill_async is what reads last_trade_seen_at and converts it;
        # we pass since_unix_ts directly to backfill_trader here to test forwarding
        await backfill_trader(
            db, "0xtrader", mock_data, mock_graph, since_unix_ts=expected_ts
        )

        # In incremental mode, historical coverage is already in the DB — Graph should
        # NOT be called (coverage window check is skipped when since_unix_ts is set).
        mock_graph.fetch_trader_trades.assert_not_called()

        # Data API should have been called with the timestamp
        mock_data.fetch_user_trades.assert_called_once()
        data_kwargs = mock_data.fetch_user_trades.call_args[1]
        assert data_kwargs.get("since_unix_ts") == expected_ts
