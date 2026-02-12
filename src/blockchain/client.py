"""Polygon blockchain client for querying OrderFilled events."""

import time
from datetime import datetime
from typing import Optional

from loguru import logger
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from web3 import Web3

from src.blockchain.decoder import (
    CTF_EXCHANGE,
    NEGRISK_CTF_EXCHANGE,
    ORDER_FILLED_TOPIC,
    POLYMARKET_START_BLOCK,
    decode_order_filled,
)
from src.blockchain.models import BlockchainTrade
from src.config.settings import Settings, get_settings


class PolygonBlockchainClient:
    """Client for querying Polymarket trades from Polygon blockchain.

    Fetches OrderFilled events from CTF Exchange contracts to get
    complete trader histories (no 100-trade limit like API).

    Attributes:
        w3: Web3 instance connected to Polygon
        settings: Application settings
        _rate_limit_delay: Delay between RPC calls to avoid throttling
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        settings: Optional[Settings] = None,
        rate_limit_delay: float = 0.1,
    ):
        """Initialize blockchain client.

        Args:
            rpc_url: Polygon RPC endpoint (uses settings default if None)
            settings: Configuration settings
            rate_limit_delay: Seconds to wait between RPC calls
        """
        self.settings = settings or get_settings()
        self.rpc_url = rpc_url or self.settings.polygon_rpc_url
        self._rate_limit_delay = rate_limit_delay

        # Initialize Web3 with Polygon RPC
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 30}))

        # Verify connection
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to Polygon RPC: {self.rpc_url}")

        logger.info(f"Connected to Polygon at block {self.get_block_number()}")

    def get_block_number(self) -> int:
        """Get current block number."""
        return self.w3.eth.block_number

    def get_block_timestamp(self, block_number: int) -> int:
        """Get timestamp for a specific block."""
        block = self.w3.eth.get_block(block_number)
        return block["timestamp"]

    def _rate_limited_call(self, func, *args, **kwargs):
        """Execute RPC call with rate limiting."""
        time.sleep(self._rate_limit_delay)
        return func(*args, **kwargs)

    def _retry_rpc_call(self, func, *args, **kwargs):
        """Execute RPC call with retry logic."""
        retryer = Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError)),
            before_sleep=lambda retry_state: logger.warning(
                f"RPC retry after error: {retry_state.outcome.exception()}"
            ),
        )
        return retryer(func, *args, **kwargs)

    def get_order_filled_events(
        self,
        from_block: int,
        to_block: int,
        contract_address: str = CTF_EXCHANGE,
    ) -> list[BlockchainTrade]:
        """Fetch OrderFilled events from a block range.

        Args:
            from_block: Starting block number (inclusive)
            to_block: Ending block number (inclusive)
            contract_address: CTF Exchange or NegRisk CTF Exchange address

        Returns:
            List of decoded BlockchainTrade instances

        Raises:
            ValueError: If block range is invalid
            ConnectionError: If RPC connection fails
        """
        if from_block > to_block:
            raise ValueError(f"from_block ({from_block}) must be <= to_block ({to_block})")

        logger.debug(f"Fetching events from blocks {from_block}-{to_block}")

        # Query logs with retry
        def _fetch_logs():
            return self.w3.eth.get_logs(
                {
                    "address": Web3.to_checksum_address(contract_address),
                    "topics": [ORDER_FILLED_TOPIC],
                    "fromBlock": from_block,
                    "toBlock": to_block,
                }
            )

        try:
            logs = self._retry_rpc_call(_fetch_logs)
        except Exception as e:
            logger.error(f"Failed to fetch logs for blocks {from_block}-{to_block}: {e}")
            raise

        # Decode each log
        trades = []
        # Cache block timestamps to avoid redundant RPC calls
        block_timestamps = {}
        for log in logs:
            try:
                trade = decode_order_filled(log, self.w3)
                # Add timestamp from block (cached)
                block_num = log["blockNumber"]
                if block_num not in block_timestamps:
                    block_timestamps[block_num] = self.get_block_timestamp(block_num)
                trade.timestamp = datetime.fromtimestamp(block_timestamps[block_num])
                trades.append(trade)
            except Exception as e:
                logger.warning(f"Failed to decode log at block {log.get('blockNumber')}: {e}")
                continue

        logger.debug(f"Fetched {len(trades)} trades from blocks {from_block}-{to_block}")
        return trades

    def get_trades_by_trader(
        self,
        trader_address: str,
        from_block: Optional[int] = None,
        to_block: Optional[int] = None,
        chunk_size: int = 1000,
    ) -> list[BlockchainTrade]:
        """Fetch ALL trades for a specific trader (NO 100-trade limit!).

        This is the key method that replaces the API's limited trader history.
        Queries both CTF Exchange and NegRisk CTF Exchange contracts.

        Args:
            trader_address: Trader wallet address
            from_block: Starting block (default: POLYMARKET_START_BLOCK)
            to_block: Ending block (default: current block)
            chunk_size: Blocks per query (smaller = more queries but less memory)

        Returns:
            Complete list of BlockchainTrade for this trader
        """
        if from_block is None:
            from_block = POLYMARKET_START_BLOCK
        if to_block is None:
            to_block = self.get_block_number()

        logger.info(
            f"Fetching blockchain history for {trader_address[:8]}... "
            f"from block {from_block} to {to_block}"
        )

        # Normalize address
        trader_address = trader_address.lower()

        all_trades = []
        contracts = [
            ("CTF Exchange", CTF_EXCHANGE),
            ("NegRisk CTF Exchange", NEGRISK_CTF_EXCHANGE),
        ]

        # Process block range in chunks
        current = from_block
        total_chunks = (to_block - from_block) // chunk_size + 1
        chunk_count = 0

        while current <= to_block:
            chunk_end = min(current + chunk_size - 1, to_block)
            chunk_count += 1

            logger.debug(f"Processing chunk {chunk_count}/{total_chunks}: blocks {current}-{chunk_end}")

            # Fetch from both contracts
            for contract_name, contract_address in contracts:
                try:
                    trades = self.get_order_filled_events(current, chunk_end, contract_address)

                    # Filter to only this trader's trades (maker or taker)
                    trader_trades = [
                        t
                        for t in trades
                        if t.maker.lower() == trader_address or t.taker.lower() == trader_address
                    ]

                    all_trades.extend(trader_trades)
                    logger.debug(f"Found {len(trader_trades)} trades from {contract_name}")

                except Exception as e:
                    logger.warning(f"Error fetching from {contract_name}: {e}")
                    continue

            current = chunk_end + 1

        logger.info(
            f"Found {len(all_trades)} total trades for {trader_address[:8]}... " f"from blockchain"
        )
        return all_trades

    def get_trades_paginated(
        self,
        from_block: int,
        to_block: int,
        chunk_size: int = 1000,
    ):
        """Generator that yields trades in chunks (for memory-efficient processing).

        Args:
            from_block: Starting block number
            to_block: Ending block number
            chunk_size: Blocks per chunk

        Yields:
            Lists of BlockchainTrade for each chunk
        """
        current = from_block

        while current <= to_block:
            chunk_end = min(current + chunk_size - 1, to_block)

            trades = self.get_order_filled_events(current, chunk_end)
            if trades:
                yield trades

            current = chunk_end + 1
