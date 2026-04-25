"""Graph API client for The Graph orderbook subgraph.

This module provides an async client for fetching OrderFilledEvent records
from The Graph's orderbook subgraph, used as fallback for complete trade history.
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# Graph endpoint for orderbook subgraph
GRAPH_ENDPOINT = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn"


def select_asset_id(maker_asset_id: str, taker_asset_id: str, is_maker: bool) -> str:
    """Select the non-zero asset_id from a trade.

    Avoids the 48% USDC bug where role-based selection picks USDC (asset_id=0)
    instead of the conditional token.

    Args:
        maker_asset_id: The maker's asset ID (may be "0" for USDC)
        taker_asset_id: The taker's asset ID (may be "0" for USDC)
        is_maker: True if the trader was the maker, False if taker

    Returns:
        The non-zero asset_id, or "0" if both are zero (shouldn't happen)
    """
    maker_is_token = maker_asset_id != "0"
    taker_is_token = taker_asset_id != "0"

    if maker_is_token and not taker_is_token:
        return maker_asset_id
    elif taker_is_token and not maker_is_token:
        return taker_asset_id
    elif maker_is_token and taker_is_token:
        # Token-for-token swap: use maker/taker role
        return maker_asset_id if is_maker else taker_asset_id
    else:
        return "0"  # Shouldn't happen


def convert_price(price_str: str) -> Decimal:
    """Convert Graph decimal odds to implied probability.

    Graph prices can be > 1.0 (decimal odds for underdogs).
    Convert to implied probability (0-1 range).

    Args:
        price_str: Price as string from Graph API

    Returns:
        Implied probability as Decimal
    """
    price = Decimal(price_str)
    if price > 1:
        return Decimal("1") / price
    return price


def parse_graph_event(event: dict, trader_address: str) -> dict:
    """Transform OrderFilledEvent to trade format.

    Args:
        event: OrderFilledEvent record from Graph API
        trader_address: The trader address we're fetching trades for

    Returns:
        Trade dict with fields:
        - trade_id: Unique identifier
        - token_id: The conditional token ID (non-zero asset_id)
        - timestamp: Unix timestamp as int
        - side: "BUY" if maker, "SELL" if taker (simplified)
        - size: Max of maker/taker amounts
        - price: Implied probability
        - market_id: None (caller handles via token_catalog lookup)
    """
    maker = event.get("maker", "")
    taker = event.get("taker", "")
    maker_asset_id = event.get("makerAssetId", "0")
    taker_asset_id = event.get("takerAssetId", "0")
    maker_amount = event.get("makerAmountFilled", "0")
    taker_amount = event.get("takerAmountFilled", "0")

    is_maker = maker.lower() == trader_address.lower()

    # Select non-zero asset_id
    token_id = select_asset_id(maker_asset_id, taker_asset_id, is_maker)

    # Derive price from ratio (use taker/maker ratio as price proxy)
    # If maker is token side: price = makerAmount / takerAmount
    # If taker is token side: price = takerAmount / makerAmount
    maker_amt = Decimal(maker_amount) if maker_amount else Decimal("0")
    taker_amt = Decimal(taker_amount) if taker_amount else Decimal("0")

    if maker_is_token := (maker_asset_id != "0"):
        if taker_amt > 0:
            price_raw = maker_amt / taker_amt
        else:
            price_raw = Decimal("0")
    else:
        if maker_amt > 0:
            price_raw = taker_amt / maker_amt
        else:
            price_raw = Decimal("0")

    price = convert_price(str(price_raw))

    # Size is the token amount (not USDC). Graph amounts are raw 6-decimal integers
    # (e.g., 30_000_000 = 30 tokens), so divide by 10^6 to get actual token count.
    _DECIMALS = Decimal("1000000")
    if maker_is_token:
        size = maker_amt / _DECIMALS
    else:
        size = taker_amt / _DECIMALS

    # trade_id is prefixed with the trader's address because a CLOB fill is ONE
    # on-chain event shared between maker and taker. Without this prefix, both
    # sides share the same trade_id and INSERT OR IGNORE silently drops the
    # second-backfilled participant's view of the fill.
    return {
        "trade_id": f"{trader_address.lower()}_{event.get('transactionHash', '')}_{event.get('id', '')}",
        "token_id": token_id,
        "timestamp": int(event.get("timestamp", "0")),
        # BUY if trader pays USDC to receive tokens; SELL if trader pays tokens.
        # Cannot use is_maker alone — a maker can sell tokens (makerAssetId = token).
        "side": "BUY"
        if (
            (is_maker and maker_asset_id == "0")
            or (not is_maker and taker_asset_id == "0")
        )
        else "SELL",
        "size": str(size),
        "price": str(price),
        "market_id": None,  # Caller resolves via token_catalog
    }


class GraphAPIClient:
    """Async client for The Graph orderbook subgraph.

    Fetches OrderFilledEvent records for trader addresses using cursor-based
    pagination. Used as fallback when API backfill is incomplete.

    Attributes:
        api_key: Optional API key for quota management
        client: httpx.AsyncClient for HTTP requests

    Example:
        >>> client = GraphAPIClient(api_key="...")
        >>> trades = await client.fetch_trader_trades("0x123...")
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Graph API client.

        Args:
            api_key: Optional API key for The Graph (Goldsky)
        """
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx AsyncClient."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers=headers,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_trader_trades(
        self,
        trader_address: str,
        batch_size: int = 100,
        since_unix_ts: Optional[int] = None,
        until_unix_ts: Optional[int] = None,
    ) -> List[dict]:
        """Fetch all trades for a trader address.

        Runs two separate paginated queries (maker role, taker role) and merges
        results. A single `or` query cannot paginate correctly on this Goldsky
        endpoint — combining `or` with `id_gt` returns 0 results on page 2+.

        The time range is split into 30-day windows before pagination. Goldsky
        enforces a Postgres statement timeout per GraphQL query; a month-bounded
        query is cheap enough that the retry budget almost never exhausts, even
        for whale traders with 50k+ lifetime events. A single-range fetch on
        those traders can exhaust the budget and silently return partial data.
        Windowing localizes a bad window to itself and lets the rest proceed.

        Args:
            trader_address: Trader wallet address (0x-prefixed)
            batch_size: Number of records per batch (default: 100)
            since_unix_ts: Optional lower bound (inclusive). If None, defaults
                to "now - 40 days" — the project's retention horizon. Older
                trades are pruned from analytics.db, so fetching past the
                horizon is wasted Graph budget.
            until_unix_ts: Optional upper bound (exclusive). If None, defaults
                to "now + 1h" so the final window captures in-flight events.

        Returns:
            List of raw OrderFilledEvent dicts (deduped by id).
        """
        client = await self._get_client()

        _FIELDS = """
            id
            transactionHash
            timestamp
            orderHash
            maker
            taker
            makerAssetId
            takerAssetId
            makerAmountFilled
            takerAmountFilled
            fee
        """

        # Window sizing. 30 days keeps month-bounded queries well under the
        # subgraph's statement-timeout ceiling. Default lookback is 40 days
        # (the project's retention horizon — older trades are pruned from
        # analytics.db and trapped-pair cleanup deletes exhausted positions
        # at the same cutoff, so fetching further back is wasted work). A
        # 40-day fetch = at most two 30-day windows.
        WINDOW_SECONDS = 30 * 86400
        DEFAULT_LOOKBACK_SECONDS = 40 * 86400

        now_ts = int(time.time())
        start_ts = (
            since_unix_ts
            if since_unix_ts is not None
            else now_ts - DEFAULT_LOOKBACK_SECONDS
        )
        end_ts = until_unix_ts if until_unix_ts is not None else now_ts + 3600

        async def _paginate(
            role: str, since_ts: int, until_ts: int
        ) -> List[dict]:
            """Paginate a single-role, single-window query to completion.

            Per-page retries handle HTTP transients, GraphQL in-body errors,
            and Postgres statement timeouts from Goldsky. On timeout-class
            errors we shrink `page_size` for the next retry — the server-side
            query cost scales with result size, so smaller pages often succeed
            where `first: 100` times out.

            If all retries for a page fail, we log a warning and return the
            events gathered so far (partial fetch) rather than raising. With
            30-day windowing this should be rare; the bad window is localized
            and downstream windows still execute.
            """
            events: List[dict] = []
            last_id: Optional[str] = None
            ts_clause = (
                f', timestamp_gte: "{since_ts}", timestamp_lt: "{until_ts}"'
            )
            page_size = batch_size
            MIN_PAGE = 10
            while True:
                batch: Optional[List[dict]] = None
                last_error: Optional[str] = None
                attempt_size = page_size
                for _attempt in range(6):
                    if last_id is None:
                        query = (
                            f"query {{ orderFilledEvents("
                            f"first: {attempt_size}, "
                            f'where: {{ {role}: "{trader_address.lower()}"{ts_clause} }}, '
                            f"orderBy: id, orderDirection: asc"
                            f") {{ {_FIELDS} }} }}"
                        )
                    else:
                        query = (
                            f"query {{ orderFilledEvents("
                            f"first: {attempt_size}, "
                            f'where: {{ {role}: "{trader_address.lower()}", id_gt: "{last_id}"{ts_clause} }}, '
                            f"orderBy: id, orderDirection: asc"
                            f") {{ {_FIELDS} }} }}"
                        )
                    shrinkable = False
                    try:
                        response = await client.post(
                            GRAPH_ENDPOINT, json={"query": query}
                        )
                    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError) as e:
                        last_error = f"{type(e).__name__}: {e}"
                        shrinkable = True
                    else:
                        if response.status_code in (429, 502, 503, 504):
                            last_error = f"HTTP {response.status_code}"
                            shrinkable = response.status_code in (502, 503, 504)
                        else:
                            response.raise_for_status()
                            body = response.json()
                            if body.get("errors"):
                                err0 = str(body["errors"][:1])
                                last_error = f"GraphQL errors: {err0[:200]}"
                                # Postgres statement timeouts are shrinkable;
                                # smaller page -> shorter query -> under limit.
                                shrinkable = "timeout" in err0.lower()
                            else:
                                data = body.get("data") or {}
                                fetched = data.get("orderFilledEvents")
                                if fetched is None:
                                    last_error = "missing orderFilledEvents in response"
                                else:
                                    batch = fetched
                                    break
                    await asyncio.sleep(min(2 ** _attempt, 16))
                    if shrinkable and attempt_size > MIN_PAGE:
                        attempt_size = max(attempt_size // 2, MIN_PAGE)
                if batch is None:
                    logger.warning(
                        "Graph pagination gave up on %s=%s window=[%d,%d) "
                        "last_id=%s after 6 attempts (min_page=%d): %s. "
                        "Returning %d events collected so far.",
                        role, trader_address[:10], since_ts, until_ts,
                        last_id, MIN_PAGE, last_error, len(events),
                    )
                    return events
                # On successful fetch at a shrunk size, let page_size grow back
                # slowly so subsequent pages don't stay tiny forever.
                if attempt_size < page_size and len(batch) == attempt_size:
                    page_size = min(batch_size, attempt_size * 2)
                if not batch:
                    # Empty page after successful response — legitimate EOS.
                    break
                events.extend(batch)
                last_id = batch[-1]["id"]
                if len(batch) < attempt_size:
                    break
            return events

        seen: set = set()
        merged: List[dict] = []
        window_start = start_ts
        while window_start < end_ts:
            window_end = min(window_start + WINDOW_SECONDS, end_ts)
            _t0 = time.time()
            maker_events = await _paginate("maker", window_start, window_end)
            taker_events = await _paginate("taker", window_start, window_end)
            new_this_window = 0
            for event in maker_events + taker_events:
                if event["id"] not in seen:
                    seen.add(event["id"])
                    merged.append(event)
                    new_this_window += 1
            logger.debug(
                "Graph window trader=%s [%d,%d) maker=%d taker=%d new=%d "
                "(%.1fs)",
                trader_address[:10], window_start, window_end,
                len(maker_events), len(taker_events), new_this_window,
                time.time() - _t0,
            )
            window_start = window_end

        return merged
