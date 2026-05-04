"""Tests for Graph API client fixes.

Covers:
1. parse_graph_event: size normalization (÷ 10^6) for BUY and SELL events
2. fetch_trader_trades: first-page query omits id_gt; subsequent pages include it
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Fix 1: size normalization in parse_graph_event
# ---------------------------------------------------------------------------


class TestParseGraphEventSize:
    """parse_graph_event divides raw 6-decimal amounts by 10^6."""

    def _make_event(self, maker_asset_id, taker_asset_id, maker_amt, taker_amt):
        return {
            "id": "event-1",
            "transactionHash": "0xabc",
            "timestamp": "1700000000",
            "orderHash": "0xdef",
            "maker": "0xmaker",
            "taker": "0xtaker",
            "makerAssetId": maker_asset_id,
            "takerAssetId": taker_asset_id,
            "makerAmountFilled": str(maker_amt),
            "takerAmountFilled": str(taker_amt),
            "fee": "0",
        }

    def test_buy_size_normalized(self):
        """BUY: trader is maker, pays USDC (makerAssetId=0), receives tokens.
        size should be token amount ÷ 10^6."""
        from polymarket_analytics.api.graph import parse_graph_event

        token_id = "71321045679252212594626385532694236071962600734667079587390701192518840499786"
        # 30 tokens at 0.17: paid 5.10 USDC
        event = self._make_event(
            maker_asset_id="0",
            taker_asset_id=token_id,
            maker_amt=5_100_000,  # 5.10 USDC (6 decimals)
            taker_amt=30_000_000,  # 30 tokens (6 decimals)
        )

        result = parse_graph_event(event, "0xmaker")

        assert result["side"] == "BUY"
        assert result["token_id"] == token_id
        assert Decimal(result["size"]) == Decimal("30")  # not 30_000_000

    def test_sell_size_normalized(self):
        """SELL: trader is maker, pays tokens (makerAssetId=token), receives USDC.
        size should be token amount ÷ 10^6."""
        from polymarket_analytics.api.graph import parse_graph_event

        token_id = "71321045679252212594626385532694236071962600734667079587390701192518840499786"
        # Trader is the maker: sells 50 tokens, receives 1 USDC
        # makerAssetId=token (maker pays tokens), takerAssetId=0 (taker pays USDC)
        event = self._make_event(
            maker_asset_id=token_id,
            taker_asset_id="0",
            maker_amt=50_000_000,  # 50 tokens (maker pays)
            taker_amt=1_000_000,  # 1 USDC (taker pays)
        )

        result = parse_graph_event(event, "0xmaker")  # trader is the maker

        assert result["side"] == "SELL"
        assert result["token_id"] == token_id
        assert Decimal(result["size"]) == Decimal("50")  # not 50_000_000

    def test_buy_price_correct(self):
        """BUY: price = USDC_paid / tokens_received = 5.10 / 30 ≈ 0.17."""
        from polymarket_analytics.api.graph import parse_graph_event

        token_id = "12345"
        event = self._make_event(
            maker_asset_id="0",
            taker_asset_id=token_id,
            maker_amt=5_100_000,
            taker_amt=30_000_000,
        )

        result = parse_graph_event(event, "0xmaker")

        price = Decimal(result["price"])
        assert Decimal("0.16") < price < Decimal("0.18")

    def test_sell_price_correct(self):
        """SELL: token is maker asset; price = USDC / tokens = 1 / 50 = 0.02."""
        from polymarket_analytics.api.graph import parse_graph_event

        token_id = "12345"
        event = self._make_event(
            maker_asset_id=token_id,
            taker_asset_id="0",
            maker_amt=50_000_000,
            taker_amt=1_000_000,
        )

        result = parse_graph_event(event, "0xtaker")

        price = Decimal(result["price"])
        assert Decimal("0.01") < price < Decimal("0.03")

    def test_confirmed_example_vitality_koi(self):
        """Confirmed real example from investigation: 3 BUY fills, avg 0.2724.

        Fill 1: 30 tokens @ 0.17 (5.10 USDC)
        The trader is the maker (placed BUY limit order, CTFExchange filled it).
        """
        from polymarket_analytics.api.graph import parse_graph_event

        trader = "0xef3a05140677f83cf37c67c4337d55a1954edc6b"
        token_id = "71321045679252212594626385532694236071962600734667079587390701192518840499786"
        event = {
            "id": "event-1",
            "transactionHash": "0xabc",
            "timestamp": "1700000000",
            "orderHash": "0xdef",
            "maker": trader,  # trader is the maker for exchange-minted BUYs
            "taker": "0xexchange",
            "makerAssetId": "0",  # maker pays USDC
            "takerAssetId": token_id,
            "makerAmountFilled": "5100000",  # 5.10 USDC
            "takerAmountFilled": "30000000",  # 30 tokens
            "fee": "0",
        }

        result = parse_graph_event(event, trader)

        assert result["side"] == "BUY"
        assert result["token_id"] == token_id
        assert Decimal(result["size"]) == Decimal("30")
        price = Decimal(result["price"])
        assert Decimal("0.16") < price < Decimal("0.18")


# ---------------------------------------------------------------------------
# Fix 2: fetch_trader_trades first-page query omits id_gt
# ---------------------------------------------------------------------------


_NARROW_SINCE = 1_700_000_000  # 2023-11-14 — a fixed past timestamp
_NARROW_UNTIL = _NARROW_SINCE + 86_400  # +1 day — fits in one 30-day window


class TestFetchTraderTradesQuery:
    """First page sends no id_gt; subsequent pages include id_gt cursor.

    All tests pass both since_unix_ts and until_unix_ts so the range fits
    inside a single 30-day window and the outer windowing loop runs exactly
    once per role (= exactly the number of mocked responses).
    """

    def _make_response(self, events):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"orderFilledEvents": events}}
        return mock_resp

    def _sample_event(self, event_id):
        return {
            "id": event_id,
            "transactionHash": f"0x{event_id}",
            "timestamp": "1700000000",
            "orderHash": "0xhash",
            "maker": "0xtrader",
            "taker": "0xother",
            "makerAssetId": "0",
            "takerAssetId": "99999",
            "makerAmountFilled": "1000000",
            "takerAmountFilled": "5000000",
            "fee": "0",
        }

    @pytest.mark.asyncio
    async def test_first_page_omits_id_gt(self):
        """First page of both maker and taker queries must not include id_gt."""
        from polymarket_analytics.api.graph import GraphAPIClient

        maker_events = [self._sample_event(f"m-{i}") for i in range(3)]
        # Two calls: maker first page, taker first page (both < batch_size → loops end)
        responses = [
            self._make_response(maker_events),  # maker page 1
            self._make_response([]),  # taker page 1 (empty)
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=responses)

        client = GraphAPIClient()
        client._client = mock_client

        await client.fetch_trader_trades(
            "0xtrader", batch_size=100,
            since_unix_ts=_NARROW_SINCE, until_unix_ts=_NARROW_UNTIL,
        )

        assert mock_client.post.call_count == 2

        # Both first-page calls must not contain id_gt
        for i, call in enumerate(mock_client.post.call_args_list):
            payload = call[1]["json"] if call[1] else call[0][1]
            query_text = payload["query"]
            assert "id_gt" not in query_text, (
                f"Call {i + 1} (first page) must not include id_gt"
            )

    @pytest.mark.asyncio
    async def test_second_page_includes_id_gt_cursor(self):
        """Page 2+ of a role query must embed id_gt with the last event id."""
        from polymarket_analytics.api.graph import GraphAPIClient

        # maker: page 1 full (batch=2 → continues), page 2 empty → stops
        # taker: page 1 empty → stops
        maker_page1 = [self._sample_event(f"evt-{i}") for i in range(2)]
        responses = [
            self._make_response(maker_page1),  # maker page 1
            self._make_response([]),  # maker page 2
            self._make_response([]),  # taker page 1
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=responses)

        client = GraphAPIClient()
        client._client = mock_client

        await client.fetch_trader_trades(
            "0xtrader", batch_size=2,
            since_unix_ts=_NARROW_SINCE, until_unix_ts=_NARROW_UNTIL,
        )

        assert mock_client.post.call_count == 3

        # Second call is maker page 2 — must include id_gt with last id from page 1
        second_call = mock_client.post.call_args_list[1]
        payload = second_call[1]["json"] if second_call[1] else second_call[0][1]
        query_text = payload["query"]
        assert "id_gt" in query_text, "Maker page 2 must include id_gt"
        assert "evt-1" in query_text, "id_gt must use last event id from page 1"

    @pytest.mark.asyncio
    async def test_returns_all_events_across_pages(self):
        """All events from all pages are collected and returned."""
        from polymarket_analytics.api.graph import GraphAPIClient

        page1 = [self._sample_event(f"a-{i}") for i in range(2)]
        page2 = [self._sample_event(f"b-{i}") for i in range(1)]
        responses = [
            self._make_response(page1),
            self._make_response(page2),
            self._make_response([]),
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=responses)

        client = GraphAPIClient()
        client._client = mock_client

        result = await client.fetch_trader_trades(
            "0xtrader", batch_size=2,
            since_unix_ts=_NARROW_SINCE, until_unix_ts=_NARROW_UNTIL,
        )

        assert len(result) == 3


# ---------------------------------------------------------------------------
# Task 4a: timestamp_gte filter tests
# ---------------------------------------------------------------------------


class TestFetchTraderTradesTimestampFilter:
    """timestamp_gte appears in every GraphQL query (windowing always sets it).

    When since_unix_ts is provided, the first window starts at that value.
    When since_unix_ts is None, the first window starts at now-40d (default lookback).
    Both cases include timestamp_gte — the difference is the value, not presence.
    """

    def _make_response(self, events):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"orderFilledEvents": events}}
        return mock_resp

    @pytest.mark.asyncio
    async def test_timestamp_gte_in_query_when_since_set(self):
        """When since_unix_ts is set, timestamp_gte equals that value in the query."""
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

        await client.fetch_trader_trades(
            "0xtrader",
            since_unix_ts=_NARROW_SINCE,
            until_unix_ts=_NARROW_UNTIL,
        )

        assert mock_client.post.call_count == 2
        for call in mock_client.post.call_args_list:
            payload = call[1]["json"] if call[1] else call[0][1]
            query_text = payload["query"]
            assert "timestamp_gte" in query_text, (
                "timestamp_gte must appear (windowing always sets it)"
            )
            assert str(_NARROW_SINCE) in query_text, (
                "since_unix_ts value must be the window start"
            )

    @pytest.mark.asyncio
    async def test_default_lookback_uses_40d_window_start(self):
        """When since_unix_ts is None, the first window's timestamp_gte is ~now-40d.

        Windowing always emits timestamp_gte; this test verifies the default
        lookback value (40 days) is used as the window start, not e.g. epoch 0.
        """
        import time
        from polymarket_analytics.api.graph import GraphAPIClient

        # Pin a narrow until_unix_ts so only one window fires (now-40d → now-39d).
        DEFAULT_LOOKBACK = 40 * 86400
        now = int(time.time())
        narrow_until = now - DEFAULT_LOOKBACK + 86400  # one day past the lookback start

        responses = [
            self._make_response([]),  # maker page 1
            self._make_response([]),  # taker page 1
        ]

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=responses)

        client = GraphAPIClient()
        client._client = mock_client

        await client.fetch_trader_trades(
            "0xtrader",
            since_unix_ts=None,
            until_unix_ts=narrow_until,
        )

        assert mock_client.post.call_count == 2
        first_call = mock_client.post.call_args_list[0]
        payload = first_call[1]["json"] if first_call[1] else first_call[0][1]
        query_text = payload["query"]
        assert "timestamp_gte" in query_text, "windowing always emits timestamp_gte"
        # The window start should be within ±60s of now-40d
        expected_start = now - DEFAULT_LOOKBACK
        assert str(expected_start) in query_text or str(expected_start - 1) in query_text or str(expected_start + 1) in query_text, (
            f"Expected window start near {expected_start} in query"
        )
