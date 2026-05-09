"""Gamma API client for fetching Polymarket eSports markets.

This module provides a rate-limited async client for the Polymarket Gamma API,
handling pagination and error handling for market ingestion.
"""

import asyncio
from typing import Callable, List, Optional

import httpx
from aiolimiter import AsyncLimiter

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"


class GammaAPIClient:
    """Async client for Polymarket Gamma API with rate limiting.

    Attributes:
        limiter: AsyncLimiter instance for rate limiting (30 req/s)
        client: httpx.AsyncClient for HTTP requests
    """

    def __init__(self, limiter: Optional[AsyncLimiter] = None):
        """Initialize Gamma API client.

        Args:
            limiter: Optional AsyncLimiter instance. If not provided,
                     creates one with 30 req/s limit.
        """
        self.limiter = limiter or AsyncLimiter(max_rate=30, time_period=1)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_tag_id(self, slug: str) -> int:
        """Fetch tag_id from Gamma API by slug.

        Args:
            slug: Tag slug (e.g., "esports")

        Returns:
            Tag ID as integer (REQUIRED - not string)

        Raises:
            httpx.HTTPStatusError: If tag not found or API error
        """
        client = await self._get_client()
        async with self.limiter:
            response = await client.get(f"{GAMMA_BASE_URL}/tags/slug/{slug}")
            response.raise_for_status()
            data = response.json()
            return int(data["id"])

    async def fetch_markets(
        self,
        tag_id: int,
        limit: int = 200,
        closed: Optional[bool] = None,
        end_date_min: Optional[str] = None,
        on_page: Optional[Callable[[int, int], None]] = None,
    ) -> List[dict]:
        """Fetch all markets for a given tag_id with pagination.

        Args:
            tag_id: Tag ID (integer) to fetch markets for
            limit: Number of markets per page (default: 200)
            closed: If False, fetch only open/unresolved markets. If True, only closed.
                    If None (default), fetch all markets.
            end_date_min: ISO timestamp string. If provided, only returns markets whose
                          endDate >= this value. Used to limit closed sweeps to recently-
                          closed markets instead of all 115k+ historical markets.
            on_page: Optional callback(page_num, total_so_far) called after each page

        Returns:
            List of market dicts

        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        client = await self._get_client()
        all_markets: List[dict] = []
        offset = 0
        page = 0

        params: dict = {"tag_id": tag_id, "limit": limit}
        if closed is not None:
            params["closed"] = "true" if closed else "false"
        if end_date_min is not None:
            params["end_date_min"] = end_date_min

        while True:
            last_err = None
            for attempt in range(4):
                try:
                    async with self.limiter:
                        response = await client.get(
                            f"{GAMMA_BASE_URL}/markets",
                            params={**params, "offset": offset},
                        )
                        response.raise_for_status()
                    last_err = None
                    break
                except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError,
                        httpx.ReadTimeout, httpx.ConnectTimeout, httpx.HTTPStatusError) as e:
                    last_err = e
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                        raise  # don't retry client errors
                    await asyncio.sleep(2 ** attempt)
            if last_err is not None:
                raise last_err

            markets = response.json()
            if not markets:
                break

            all_markets.extend(markets)
            offset += limit
            page += 1

            if on_page:
                on_page(page, len(all_markets))

        return all_markets


    async def fetch_market_by_condition(self, condition_id: str) -> Optional[dict]:
        """Fetch a single market by condition_id from CLOB API.

        Uses CLOB endpoint which correctly filters by condition_id.
        Gamma API /markets ignores the condition_id param and returns a default page.
        """
        client = await self._get_client()
        async with self.limiter:
            response = await client.get(
                f"{CLOB_BASE_URL}/markets/{condition_id}",
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            # CLOB returns a single dict, not a list
            return data if isinstance(data, dict) and data.get("condition_id") else None


async def fetch_tag_id(slug: str) -> int:
    """Convenience function to fetch tag_id for a slug.

    Args:
        slug: Tag slug (e.g., "esports")

    Returns:
        Tag ID as integer
    """
    client = GammaAPIClient()
    try:
        return await client.get_tag_id(slug)
    finally:
        await client.close()
