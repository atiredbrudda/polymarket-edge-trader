"""Gamma API client for Polymarket market data."""

from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from src.api.rate_limiter import RateLimiter


class GammaMarketClient:
    """Gamma API client for fetching Polymarket markets with server-side filtering.

    Provides methods to fetch markets from the Gamma API with support for:
    - Server-side filtering by end date, tag, and closed status
    - Pagination via offset parameter
    - Optional rate limiting

    Attributes:
        BASE_URL: The base URL for the Gamma API
        rate_limiter: Optional rate limiter for API requests
    """

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, rate_limiter: RateLimiter | None = None):
        """Initialize the Gamma API client.

        Args:
            rate_limiter: Optional rate limiter to control request rate
        """
        self.rate_limiter = rate_limiter

    def get_markets(
        self,
        end_date_max: datetime | None = None,
        tag: str | None = None,
        closed: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch markets from Gamma API with optional filters.

        Supports server-side filtering and automatic pagination.

        Args:
            end_date_max: Maximum end date filter (markets ending before this)
            tag: Tag filter (e.g., "esports", "crypto")
            closed: Whether to include closed markets
            limit: Number of results per page

        Returns:
            List of market dictionaries

        Raises:
            httpx.HTTPStatusError: If the API returns an error response
        """
        all_markets = []
        offset = 0

        while True:
            params: dict[str, Any] = {
                "closed": str(closed).lower(),
                "limit": limit,
                "offset": offset,
            }

            if end_date_max is not None:
                params["end_date_max"] = end_date_max.isoformat()

            if tag is not None:
                params["tag"] = tag

            if self.rate_limiter is not None:
                self.rate_limiter.acquire()

            logger.debug(
                f"Fetching markets (offset={offset}, limit={limit}, "
                f"closed={closed}, tag={tag}, end_date_max={end_date_max})"
            )

            response = httpx.get(
                self.BASE_URL + "/markets", params=params, timeout=30.0
            )
            response.raise_for_status()

            markets = response.json()

            if not markets:
                break

            all_markets.extend(markets)

            if len(markets) < limit:
                break

            offset += limit

        logger.info(f"Fetched {len(all_markets)} markets from Gamma API")
        return all_markets

    def get_events(
        self,
        start_date_max: datetime | None = None,
        start_date_min: datetime | None = None,
        tag_id: int | None = None,
        active: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch events from Gamma API with optional filters.

        The /events endpoint actually works correctly (unlike /markets which ignores filters).
        Returns real game times in startDate/endDate fields.

        Args:
            start_date_max: Maximum start date filter (events starting before this)
            start_date_min: Minimum start date filter (events starting after this)
            tag_id: Tag ID filter (e.g., 64 for esports)
            active: Only return active events
            limit: Number of results per page

        Returns:
            List of event dictionaries with real game times

        Raises:
            httpx.HTTPStatusError: If the API returns an error response
        """
        all_events = []
        offset = 0

        while True:
            params: dict[str, Any] = {
                "active": str(active).lower(),
                "limit": limit,
                "offset": offset,
                "order": "startDate",
                "ascending": "false",
            }

            if start_date_max is not None:
                params["start_date_max"] = start_date_max.isoformat()

            if start_date_min is not None:
                params["start_date_min"] = start_date_min.isoformat()

            if tag_id is not None:
                params["tag_id"] = tag_id

            if self.rate_limiter is not None:
                self.rate_limiter.acquire()

            logger.debug(
                f"Fetching events (offset={offset}, limit={limit}, "
                f"active={active}, tag_id={tag_id}, start_date_max={start_date_max})"
            )

            response = httpx.get(self.BASE_URL + "/events", params=params, timeout=30.0)
            response.raise_for_status()

            events = response.json()

            if not events:
                break

            all_events.extend(events)

            if len(events) < limit:
                break

            offset += limit

        logger.info(f"Fetched {len(all_events)} events from Gamma API")
        return all_events
