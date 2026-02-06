"""Polymarket CLOB API client wrapper with retry logic and rate limiting."""

from typing import Callable, List, TypeVar

import httpx
from loguru import logger
from py_clob_client.client import ClobClient
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.api.models import EventResponse, MarketResponse, TradeResponse
from src.api.rate_limiter import RateLimiter
from src.config.settings import Settings, get_settings

T = TypeVar("T")


class PolymarketClient:
    """Polymarket CLOB API client with rate limiting and retry logic.

    Wraps py-clob-client with:
    - Token bucket rate limiting
    - Exponential backoff retry on transient failures
    - Pydantic validation of API responses
    - Pagination handling

    Attributes:
        client: Underlying ClobClient instance
        settings: Configuration settings
        rate_limiter: Token bucket rate limiter
    """

    def __init__(self, settings: Settings | None = None):
        """Initialize API client.

        Args:
            settings: Configuration settings (uses defaults if None)
        """
        self.settings = settings or get_settings()

        # Initialize py-clob-client in read-only mode
        self.client = ClobClient(
            self.settings.polymarket_api_host,
            key=self.settings.polymarket_api_key
        )

        # Initialize rate limiter
        self.rate_limiter = RateLimiter(
            max_per_second=self.settings.max_requests_per_second
        )

        logger.info(
            f"Initialized PolymarketClient with rate limit "
            f"{self.settings.max_requests_per_second}/s"
        )

    def _retry_call(self, func: Callable[[], T]) -> T:
        """Execute a function with retry logic.

        Args:
            func: Callable to execute with retry

        Returns:
            Result of function call

        Raises:
            RetryError: If all retry attempts exhausted
        """
        retryer = Retrying(
            stop=stop_after_attempt(self.settings.retry_max_attempts),
            wait=wait_exponential(
                multiplier=self.settings.retry_backoff_multiplier,
                min=self.settings.retry_min_wait,
                max=self.settings.retry_max_wait,
            ),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, httpx.HTTPError)),
            before_sleep=lambda retry_state: logger.warning(
                f"Retrying after {retry_state.outcome.exception()}, "
                f"attempt {retry_state.attempt_number}"
            ),
        )
        return retryer(func)

    def get_events(self, active: bool = True) -> List[EventResponse]:
        """Fetch events from Polymarket CLOB API.

        Handles pagination automatically by following next_cursor until
        pagination is complete.

        Args:
            active: If True, only return active events

        Returns:
            List of validated EventResponse models

        Raises:
            RetryError: If all retry attempts are exhausted
        """
        self.rate_limiter.acquire()

        all_events = []
        next_cursor = None

        while True:
            logger.debug(f"Fetching events (active={active}, cursor={next_cursor})")

            # Make API call
            response = self.client.get_events(next_cursor=next_cursor)

            # Handle both dict response and list response
            if isinstance(response, dict):
                events_data = response.get("data", [])
                next_cursor = response.get("next_cursor")
            else:
                # Direct list response (no pagination)
                events_data = response
                next_cursor = None

            # Validate and collect events
            for event_data in events_data:
                try:
                    event = EventResponse(**event_data)
                    if not active or event.active:
                        all_events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to validate event: {e}")
                    continue

            # Check pagination termination
            if not next_cursor or next_cursor == "LTE" or next_cursor == "":
                break

            # Rate limit before next page
            self.rate_limiter.acquire()

        logger.info(f"Fetched {len(all_events)} events")
        return all_events

    def get_markets(self, active: bool = True) -> List[MarketResponse]:
        """Fetch simplified markets from Polymarket CLOB API.

        Handles pagination automatically by following next_cursor until
        pagination is complete.

        Args:
            active: If True, only return active markets

        Returns:
            List of validated MarketResponse models

        Raises:
            RetryError: If all retry attempts are exhausted
        """
        def _fetch_markets():
            all_markets = []
            next_cursor = None

            while True:
                self.rate_limiter.acquire()
                logger.debug(f"Fetching markets (active={active}, cursor={next_cursor})")

                # Make API call with retry
                response = self.client.get_simplified_markets(next_cursor=next_cursor)

                # Handle both dict response and list response
                if isinstance(response, dict):
                    markets_data = response.get("data", [])
                    next_cursor = response.get("next_cursor")
                else:
                    # Direct list response (no pagination)
                    markets_data = response
                    next_cursor = None

                # Validate and collect markets
                for market_data in markets_data:
                    try:
                        market = MarketResponse(**market_data)
                        if not active or market.active:
                            all_markets.append(market)
                    except Exception as e:
                        logger.warning(f"Failed to validate market: {e}")
                        continue

                # Check pagination termination
                if not next_cursor or next_cursor == "LTE" or next_cursor == "":
                    break

            logger.info(f"Fetched {len(all_markets)} markets")
            return all_markets

        return self._retry_call(_fetch_markets)

    def get_market_trades(
        self, condition_id: str, limit: int = 500
    ) -> List[TradeResponse]:
        """Fetch trades for a specific market.

        This discovers traders by seeing who trades on a market (public data).
        Note: py-clob-client's get_trades() returns only authenticated user's
        trades. To discover traders, we fetch trades on specific markets.

        Handles pagination automatically.

        Args:
            condition_id: Market condition ID
            limit: Maximum trades per page

        Returns:
            List of validated TradeResponse models

        Raises:
            RetryError: If all retry attempts are exhausted
        """
        self.rate_limiter.acquire()

        all_trades = []
        next_cursor = None

        while True:
            logger.debug(
                f"Fetching trades for market {condition_id} "
                f"(limit={limit}, cursor={next_cursor})"
            )

            # Make API call
            response = self.client.get_trades(
                market=condition_id,
                next_cursor=next_cursor
            )

            # Handle both dict response and list response
            if isinstance(response, dict):
                trades_data = response.get("data", [])
                next_cursor = response.get("next_cursor")
            else:
                # Direct list response (no pagination)
                trades_data = response
                next_cursor = None

            # Validate and collect trades
            for trade_data in trades_data:
                try:
                    trade = TradeResponse(**trade_data)
                    all_trades.append(trade)
                except Exception as e:
                    logger.warning(f"Failed to validate trade: {e}")
                    continue

            # Check pagination termination
            if not next_cursor or next_cursor == "LTE" or next_cursor == "":
                break

            # Rate limit before next page
            self.rate_limiter.acquire()

        logger.info(
            f"Fetched {len(all_trades)} trades for market {condition_id}"
        )
        return all_trades
