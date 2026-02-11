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

from py_clob_client.clob_types import TradeParams

from src.api.models import MarketResponse, TradeResponse
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
            next_cursor = "MA=="  # Start with default cursor

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

    def get_market(self, condition_id: str) -> MarketResponse | None:
        """Fetch a single market by condition ID.

        Args:
            condition_id: Market condition ID

        Returns:
            MarketResponse or None if not found

        Raises:
            RetryError: If all retry attempts are exhausted
        """
        self.rate_limiter.acquire()
        logger.debug(f"Fetching market {condition_id}")

        try:
            response = self.client.get_market(condition_id)
            market = MarketResponse(**response)
            logger.info(f"Fetched market: {market.question}")
            return market
        except Exception as e:
            logger.warning(f"Failed to fetch market {condition_id}: {e}")
            return None

    def get_market_trades(
        self, condition_id: str, limit: int = 500
    ) -> List[TradeResponse]:
        """Fetch trades for a specific market using public Data API.

        Uses Polymarket's public data API at https://data-api.polymarket.com/trades
        which doesn't require authentication.

        Args:
            condition_id: Market condition ID
            limit: Maximum trades to fetch (default 500)

        Returns:
            List of validated TradeResponse models

        Raises:
            RetryError: If all retry attempts are exhausted
        """
        self.rate_limiter.acquire()
        logger.debug(f"Fetching trades for market {condition_id}")

        try:
            # Use public Data API
            url = f"https://data-api.polymarket.com/trades?market={condition_id}"
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()

            trades_data = response.json()

            # Validate and collect trades
            all_trades = []
            for trade_data in trades_data[:limit]:
                try:
                    # CRITICAL FIX: The API may return trades from multiple markets
                    # We must filter to only include trades from the requested market
                    trade_market_id = trade_data.get("conditionId", "")

                    if trade_market_id.lower() != condition_id.lower():
                        # Skip trades from other markets
                        continue

                    # Map public API fields to TradeResponse fields
                    mapped_data = {
                        "id": trade_data.get("transactionHash", ""),
                        "market": trade_market_id,
                        "maker": trade_data.get("proxyWallet", ""),
                        "side": trade_data.get("side", ""),
                        "size": str(trade_data.get("size", 0)),
                        "price": str(trade_data.get("price", 0)),
                        "timestamp": trade_data.get("timestamp", 0),
                        "asset_ticker": trade_data.get("outcome", ""),
                    }
                    trade = TradeResponse(**mapped_data)
                    all_trades.append(trade)
                except Exception as e:
                    logger.warning(f"Failed to validate trade: {e}")
                    continue

            logger.info(
                f"Fetched {len(all_trades)} trades for market {condition_id}"
            )
            return all_trades

        except Exception as e:
            logger.error(f"Failed to fetch trades for market {condition_id}: {e}")
            return []

    def get_trader_trades(
        self, trader_address: str, limit: int = 1000
    ) -> List[TradeResponse]:
        """Fetch all trades for a specific trader using public Data API.

        Uses Polymarket's public data API at https://data-api.polymarket.com/trades
        to fetch a trader's complete trading history.

        Args:
            trader_address: Trader wallet address (proxyWallet)
            limit: Maximum trades to fetch (default 1000)

        Returns:
            List of validated TradeResponse models

        Raises:
            RetryError: If all retry attempts are exhausted
        """
        self.rate_limiter.acquire()
        logger.debug(f"Fetching trades for trader {trader_address[:8]}...")

        try:
            # Use public Data API with proxyWallet parameter
            url = f"https://data-api.polymarket.com/trades?proxyWallet={trader_address}"
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()

            trades_data = response.json()

            # Validate and collect trades
            all_trades = []
            for trade_data in trades_data[:limit]:
                try:
                    # Map public API fields to TradeResponse fields
                    mapped_data = {
                        "id": trade_data.get("transactionHash", ""),
                        "market": trade_data.get("conditionId", ""),
                        "maker": trade_data.get("proxyWallet", ""),
                        "side": trade_data.get("side", ""),
                        "size": str(trade_data.get("size", 0)),
                        "price": str(trade_data.get("price", 0)),
                        "timestamp": trade_data.get("timestamp", 0),
                        "asset_ticker": trade_data.get("outcome", ""),
                    }
                    trade = TradeResponse(**mapped_data)
                    all_trades.append(trade)
                except Exception as e:
                    logger.warning(f"Failed to validate trade: {e}")
                    continue

            logger.info(
                f"Fetched {len(all_trades)} trades for trader {trader_address[:8]}..."
            )
            return all_trades

        except Exception as e:
            logger.error(f"Failed to fetch trades for trader {trader_address[:8]}...: {e}")
            return []
