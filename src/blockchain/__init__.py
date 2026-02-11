"""Blockchain indexing layer for Polymarket.

Provides direct Polygon blockchain queries to get complete trader histories
without the 100-trade API limitation.
"""

from src.blockchain.client import (
    PolygonBlockchainClient,
)
from src.blockchain.decoder import (
    CTF_EXCHANGE,
    NEGRISK_CTF_EXCHANGE,
    ORDER_FILLED_ABI,
    ORDER_FILLED_TOPIC,
    POLYMARKET_START_BLOCK,
)
from src.blockchain.models import BlockchainTrade

__all__ = [
    "CTF_EXCHANGE",
    "NEGRISK_CTF_EXCHANGE",
    "POLYMARKET_START_BLOCK",
    "PolygonBlockchainClient",
    "ORDER_FILLED_ABI",
    "ORDER_FILLED_TOPIC",
    "BlockchainTrade",
]
