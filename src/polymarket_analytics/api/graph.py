"""Graph API client for The Graph orderbook subgraph.

This module provides an async client for fetching OrderFilledEvent records
from The Graph's orderbook subgraph, used as fallback for complete trade history.
"""

from decimal import Decimal
from typing import List, Optional

import httpx

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

    # Size is the larger of the two amounts (in token terms)
    size = max(maker_amt, taker_amt)

    return {
        "trade_id": f"{event.get('transactionHash', '')}_{event.get('id', '')}",
        "token_id": token_id,
        "timestamp": int(event.get("timestamp", "0")),
        "side": "BUY" if is_maker else "SELL",
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
        self, trader_address: str, batch_size: int = 100
    ) -> List[dict]:
        """Fetch all trades for a trader address.

        Uses cursor-based pagination with id field ordering (ascending).
        Fetches OrderFilledEvents where trader is maker OR taker.

        Args:
            trader_address: Trader wallet address (0x-prefixed)
            batch_size: Number of records per batch (default: 100)

        Returns:
            List of trade dicts with fields:
            - id: Graph event ID
            - transactionHash: Transaction hash
            - timestamp: Unix timestamp
            - orderHash: Order hash
            - maker: Maker address
            - taker: Taker address
            - makerAssetId: Maker asset ID
            - takerAssetId: Taker asset ID
            - makerAmountFilled: Maker amount filled
            - takerAmountFilled: Taker amount filled
            - fee: Fee amount
        """
        client = await self._get_client()
        all_trades: List[dict] = []
        last_id: Optional[str] = None

        while True:
            # Build GraphQL query
            where_clause: dict = {
                "or": [
                    {"maker": trader_address.lower()},
                    {"taker": trader_address.lower()},
                ]
            }
            if last_id:
                where_clause["id_gt"] = last_id

            query = """
            query GetTraderTrades($trader: String!, $lastId: ID, $batchSize: Int!) {
              orderFilledEvents(
                first: $batchSize
                where: {
                  or: [
                    { maker: $trader }
                    { taker: $trader }
                  ]
                  id_gt: $lastId
                }
                orderBy: id
                orderDirection: asc
              ) {
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
              }
            }
            """

            variables = {
                "trader": trader_address.lower(),
                "lastId": last_id,
                "batchSize": batch_size,
            }

            response = await client.post(
                GRAPH_ENDPOINT,
                json={"query": query, "variables": variables},
            )
            response.raise_for_status()
            data = response.json()

            events = data.get("data", {}).get("orderFilledEvents", [])
            if not events:
                break

            all_trades.extend(events)
            last_id = events[-1]["id"]

            # If we got fewer than batch_size, we've reached the end
            if len(events) < batch_size:
                break

        return all_trades
