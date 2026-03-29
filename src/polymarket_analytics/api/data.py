"""Data API client for fetching Polymarket trades and holders.

This module provides a rate-limited async client for the Polymarket Data API,
handling batched requests for trades and holders data.
"""

from typing import List, Optional

import httpx
from aiolimiter import AsyncLimiter

# Data API base URL
DATA_BASE_URL = "https://data-api.polymarket.com"


class DataAPIClient:
    """Async client for Polymarket Data API with rate limiting.

    The Data API provides access to trades, holders, and leaderboard data.
    This client handles rate limiting (20 req/s) and batches condition IDs
    to avoid URL length limits.

    Attributes:
        limiter: AsyncLimiter instance for rate limiting (20 req/s)
        client: httpx.AsyncClient for HTTP requests

    Example:
        >>> client = DataAPIClient()
        >>> trades = await client.fetch_trades(["0x123...", "0x456..."])
        >>> holders = await client.fetch_holders(["0x123..."])
        >>> user_trades = await client.fetch_user_trades("0xabc...")
    """

    def __init__(self, limiter: Optional[AsyncLimiter] = None):
        """Initialize Data API client.

        Args:
            limiter: Optional AsyncLimiter instance. If not provided,
                     creates one with 20 req/s limit (Data API limit).
        """
        self.limiter = limiter or AsyncLimiter(max_rate=20, time_period=1)
        self._client: Optional[httpx.AsyncClient] = None
        self._batch_size = 50  # Batch condition IDs to avoid URL length limits

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_trades(
        self, condition_ids: List[str], limit: int = 1000
    ) -> List[dict]:
        """Fetch trades for multiple markets.

        Batches condition_ids in groups of 50 to avoid URL length limits
        (research pitfall #2). Each batch is fetched with rate limiting.

        Args:
            condition_ids: List of condition IDs (0x-prefixed 64-hex strings)
            limit: Max trades per market (default: 1000, max: 10000)

        Returns:
            List of trade objects with fields:
            - proxyWallet: Trader wallet address
            - side: BUY or SELL
            - conditionId: Market condition ID
            - size: Trade size
            - price: Trade price
            - timestamp: Unix timestamp
            - outcome: YES or NO
            - outcomeIndex: 0 or 1

        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        client = await self._get_client()
        all_trades: List[dict] = []

        # Batch condition IDs to avoid URL length limits
        for i in range(0, len(condition_ids), self._batch_size):
            batch = condition_ids[i : i + self._batch_size]
            market_param = ",".join(batch)

            async with self.limiter:
                response = await client.get(
                    f"{DATA_BASE_URL}/trades",
                    params={"market": market_param, "limit": limit},
                )
                response.raise_for_status()

            trades = response.json()
            all_trades.extend(trades)

        return all_trades

    async def fetch_holders(
        self, condition_ids: List[str], limit: int = 20
    ) -> List[dict]:
        """Fetch top holders for multiple markets.

        Batches condition_ids in groups of 50 to avoid URL length limits.
        Note: limit is per market (max 20 per market).

        Args:
            condition_ids: List of condition IDs (0x-prefixed 64-hex strings)
            limit: Max holders per market (default: 20, max: 20)

        Returns:
            List of holder objects with fields:
            - token: Outcome token ID
            - holders: List of holder objects with:
              - proxyWallet: Holder wallet address
              - amount: Holdings amount
              - outcomeIndex: 0 or 1
              - pseudonym: Optional trader name
              - profileImage: Optional profile image URL

        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        client = await self._get_client()
        all_holders: List[dict] = []

        # Batch condition IDs to avoid URL length limits
        for i in range(0, len(condition_ids), self._batch_size):
            batch = condition_ids[i : i + self._batch_size]
            market_param = ",".join(batch)

            async with self.limiter:
                response = await client.get(
                    f"{DATA_BASE_URL}/holders",
                    params={"market": market_param, "limit": limit},
                )
                response.raise_for_status()

            holders_data = response.json()
            all_holders.extend(holders_data)

        return all_holders

    async def fetch_user_trades(
        self, trader_address: str, limit: int = 1000
    ) -> List[dict]:
        """Fetch all trades for a specific trader address.

        Uses offset-based pagination (not cursor-based like CLOB API).
        Fetches trades where the trader is the proxyWallet.

        Args:
            trader_address: Trader wallet address (0x-prefixed)
            limit: Max trades per request (default: 1000)

        Returns:
            List of trade dicts with fields:
            - proxyWallet: Trader wallet address
            - side: BUY or SELL
            - asset: Outcome token ID
            - conditionId: Market condition ID
            - size: Trade size
            - price: Trade price
            - timestamp: Unix timestamp
            - outcome: YES or NO
            - outcomeIndex: 0 or 1

        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        client = await self._get_client()
        all_trades: List[dict] = []
        offset = 0

        while True:
            async with self.limiter:
                response = await client.get(
                    f"{DATA_BASE_URL}/trades",
                    params={
                        "user": trader_address.lower(),
                        "limit": limit,
                        "offset": offset,
                    },
                )
                response.raise_for_status()

            trades = response.json()
            if not trades:
                break

            all_trades.extend(trades)

            # If we got fewer than limit, we've reached the end
            if len(trades) < limit:
                break

            offset += limit

        return all_trades
