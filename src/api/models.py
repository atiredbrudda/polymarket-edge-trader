"""Pydantic validation models for Polymarket CLOB API responses."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketResponse(BaseModel):
    """Market data from Polymarket CLOB API.

    Represents a binary prediction market with question, end date,
    category, and resolution outcome.
    """

    condition_id: str
    question: str
    end_date_iso: str | None = None
    category: str
    outcome: str | None = None
    active: bool
    tokens: list[dict] | None = None

    model_config = ConfigDict(populate_by_name=True)


class EventResponse(BaseModel):
    """Event data from Polymarket CLOB API.

    Events contain one or more markets. Often used for tournament
    or multi-market groupings.
    """

    id: str
    title: str
    slug: str
    category: str
    end_date: datetime | None = None
    active: bool
    markets: list[MarketResponse]

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("end_date", mode="before")
    @classmethod
    def parse_end_date(cls, v: Any) -> datetime | None:
        """Parse end_date from Unix timestamp or ISO string.

        Args:
            v: Input value (Unix timestamp int or ISO string)

        Returns:
            datetime object or None
        """
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, int):
            return datetime.fromtimestamp(v)
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class TradeResponse(BaseModel):
    """Trade data from Polymarket CLOB API.

    Represents a single trade execution with trader address, side,
    size, price, and timestamp.
    """

    id: str
    market: str
    trader: str = Field(validation_alias="maker")  # API uses 'maker' or 'taker'
    side: str  # "BUY" or "SELL"
    size: Decimal
    price: Decimal
    timestamp: datetime
    asset_ticker: str | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: Any) -> datetime:
        """Parse timestamp from Unix timestamp or ISO string.

        Args:
            v: Input value (Unix timestamp int or ISO string)

        Returns:
            datetime object

        Raises:
            ValueError: If timestamp format is invalid
        """
        if isinstance(v, datetime):
            return v
        if isinstance(v, int):
            return datetime.fromtimestamp(v)
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        raise ValueError(f"Invalid timestamp format: {v}")

    @field_validator("price")
    @classmethod
    def validate_price_range(cls, v: Decimal) -> Decimal:
        """Validate that price is between 0 and 1 (exclusive).

        Args:
            v: Price value

        Returns:
            Validated price

        Raises:
            ValueError: If price is outside valid range
        """
        if v <= 0 or v >= 1:
            raise ValueError(f"Price must be between 0 and 1 (exclusive), got {v}")
        return v
