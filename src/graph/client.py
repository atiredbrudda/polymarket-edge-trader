"""The Graph client for querying Polymarket Orderbook subgraph.

This provides instant, zero-storage access to complete trader histories
via The Graph's decentralized indexing protocol.
"""

import requests
from loguru import logger

from src.config.settings import Settings, get_settings

# Polymarket Orderbook subgraph on Polygon
ORDERBOOK_SUBGRAPH_ID = "7fu2DWYK93ePfzB24c2wrP94S3x4LGHUrQxphhoEypyY"


class GraphClient:
    """Client for querying Polymarket data via The Graph.

    Provides access to complete trader histories without downloading
    blockchain data or hitting API rate limits.

    Attributes:
        api_key: The Graph API key
        subgraph_id: Polymarket Orderbook subgraph ID
        endpoint: Full GraphQL endpoint URL
    """

    def __init__(
        self,
        api_key: str | None = None,
        settings: Settings | None = None,
        subgraph_id: str = ORDERBOOK_SUBGRAPH_ID,
    ):
        """Initialize The Graph client.

        Args:
            api_key: The Graph API key (reads from settings if None)
            settings: Application settings
            subgraph_id: Subgraph ID to query (defaults to Polymarket Orderbook)
        """
        self.settings = settings or get_settings()
        self.api_key = api_key or self.settings.the_graph_api_key
        self.subgraph_id = subgraph_id
        self.endpoint = f"https://gateway.thegraph.com/api/{self.api_key}/subgraphs/id/{self.subgraph_id}"

        if not self.api_key:
            raise ValueError(
                "The Graph API key not configured. "
                "Set THE_GRAPH_API_KEY in .env or settings"
            )

        logger.info(f"Initialized GraphClient for subgraph {subgraph_id[:8]}...")

    def query(self, graphql_query: str) -> dict:
        """Execute GraphQL query against the subgraph.

        Args:
            graphql_query: GraphQL query string

        Returns:
            Query response data

        Raises:
            ValueError: If query returns errors
            requests.RequestException: If HTTP request fails
        """
        response = requests.post(
            self.endpoint,
            json={"query": graphql_query},
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()

        if "errors" in result:
            error_msg = result["errors"][0].get("message", "Unknown error")
            raise ValueError(f"GraphQL query error: {error_msg}")

        return result.get("data", {})

    def get_trader_trades(
        self,
        trader_address: str,
        max_per_query: int = 1000,
        max_total: int | None = None,
    ) -> list[dict]:
        """Fetch ALL trades for a trader (both maker and taker).

        This is the main method that replaces blockchain scanning.
        Uses pagination to fetch complete history.

        Args:
            trader_address: Trader wallet address (0x...)
            max_per_query: Results per GraphQL query (max 1000)
            max_total: Optional limit on total trades to fetch

        Returns:
            List of trade dicts with fields:
            - id: Unique trade ID
            - maker: Maker address
            - taker: Taker address
            - makerAmountFilled: Maker amount (raw, 6 decimals for USDC)
            - takerAmountFilled: Taker amount (raw, 6 decimals)
            - makerAssetId: Maker asset ID (token ID)
            - takerAssetId: Taker asset ID (token ID)
            - fee: Trading fee (raw, 6 decimals)
            - timestamp: Unix timestamp
            - blockNumber: Polygon block number
            - transactionHash: Transaction hash
            - orderHash: Order hash
            - side: Trade side
            - price: Trade price
        """
        trader_address = trader_address.lower()
        all_trades = []

        logger.info(f"Fetching trades for {trader_address[:8]}... from The Graph")

        # Query 1: Trades where address is MAKER
        logger.debug("Querying trades as MAKER...")
        skip = 0
        while True:
            if max_total and len(all_trades) >= max_total:
                break

            query = f"""
            {{
              orderFilledEvents(
                first: {max_per_query}
                skip: {skip}
                where: {{maker: "{trader_address}"}}
                orderBy: timestamp
                orderDirection: desc
              ) {{
                id
                maker
                taker
                makerAmountFilled
                takerAmountFilled
                makerAssetId
                takerAssetId
                fee
                timestamp
                blockNumber
                transactionHash
                orderHash
                side
                price
              }}
            }}
            """

            data = self.query(query)
            events = data.get("orderFilledEvents", [])

            if not events:
                break

            all_trades.extend(events)
            logger.debug(
                f"  Fetched {len(events)} trades as maker (total: {len(all_trades)})"
            )

            if len(events) < max_per_query:
                break

            skip += max_per_query

        maker_count = len(all_trades)

        # Query 2: Trades where address is TAKER
        logger.debug("Querying trades as TAKER...")
        skip = 0
        while True:
            if max_total and len(all_trades) >= max_total:
                break

            query = f"""
            {{
              orderFilledEvents(
                first: {max_per_query}
                skip: {skip}
                where: {{taker: "{trader_address}"}}
                orderBy: timestamp
                orderDirection: desc
              ) {{
                id
                maker
                taker
                makerAmountFilled
                takerAmountFilled
                makerAssetId
                takerAssetId
                fee
                timestamp
                blockNumber
                transactionHash
                orderHash
                side
                price
              }}
            }}
            """

            data = self.query(query)
            events = data.get("orderFilledEvents", [])

            if not events:
                break

            all_trades.extend(events)
            logger.debug(
                f"  Fetched {len(events)} trades as taker (total: {len(all_trades)})"
            )

            if len(events) < max_per_query:
                break

            skip += max_per_query

        taker_count = len(all_trades) - maker_count

        logger.info(
            f"Found {len(all_trades)} trades for {trader_address[:8]}... "
            f"({maker_count} as maker, {taker_count} as taker) from The Graph"
        )

        return all_trades

    def get_account_stats(self, trader_address: str) -> dict | None:
        """Get aggregated account statistics for a trader.

        Args:
            trader_address: Trader wallet address

        Returns:
            Account stats dict or None if account not found
        """
        trader_address = trader_address.lower()

        query = f"""
        {{
          account(id: "{trader_address}") {{
            id
            tradesQuantity
            totalVolume
            totalFees
            firstTrade
            lastTrade
            isActive
          }}
        }}
        """

        data = self.query(query)
        return data.get("account")
