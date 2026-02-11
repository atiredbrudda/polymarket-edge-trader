"""Blockchain trade models."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class BlockchainTrade:
    """A trade decoded from Polygon blockchain OrderFilled event.

    Maps to TradeResponse for compatibility with existing pipeline.
    """

    block_number: int
    transaction_hash: str
    log_index: int
    order_hash: str
    maker: str  # Maker address (trader who created order)
    taker: str  # Taker address (trader who filled order)
    maker_asset_id: int
    taker_asset_id: int
    maker_amount: int  # In USDC wei (6 decimals)
    taker_amount: int
    fee: int
    timestamp: Optional[datetime] = None  # Block timestamp

    @property
    def is_buy(self) -> bool:
        """True if maker is providing USDC (buying outcome tokens)."""
        return self.maker_asset_id == 0

    @property
    def price(self) -> Decimal:
        """Calculate price as USDC per token (0-1 range)."""
        if self.is_buy:
            if self.taker_amount > 0:
                return Decimal(self.maker_amount) / Decimal(self.taker_amount)
        else:
            if self.maker_amount > 0:
                return Decimal(self.taker_amount) / Decimal(self.maker_amount)
        return Decimal("0")

    @property
    def size(self) -> Decimal:
        """Number of tokens traded (in USDC units)."""
        if self.is_buy:
            return Decimal(self.taker_amount) / Decimal(1e6)
        return Decimal(self.maker_amount) / Decimal(1e6)

    @property
    def side(self) -> str:
        """BUY or SELL from maker's perspective."""
        return "BUY" if self.is_buy else "SELL"

    def to_trade_id(self) -> str:
        """Generate unique trade ID matching API format."""
        return f"{self.transaction_hash}_{self.log_index}"

    def to_api_response(self) -> dict:
        """Convert to TradeResponse-compatible dict for pipeline integration."""
        return {
            "id": self.to_trade_id(),
            "market": self.extract_condition_id(),
            "maker": self.maker,
            "side": self.side,
            "size": str(self.size),
            "price": str(self.price),
            "timestamp": self.timestamp.timestamp() if self.timestamp else 0,
            "asset_ticker": self.extract_outcome_name(),
        }

    def extract_condition_id(self) -> str:
        """Extract condition ID from asset ID (for market identification).

        Position ID = keccak256(collateralToken, conditionId, partition)
        First 32 bytes of position ID after 0x prefix is condition ID.
        """
        asset_id = self.taker_asset_id if self.is_buy else self.maker_asset_id
        if asset_id == 0:
            return ""
        # Convert to hex and extract condition ID
        hex_str = hex(asset_id)[2:]  # Remove 0x prefix
        if len(hex_str) >= 64:
            return "0x" + hex_str[:64]
        return ""

    def extract_outcome_name(self) -> str:
        """Extract outcome name from asset ID (simplified)."""
        # This is a placeholder - full implementation would decode from position ID
        return ""
