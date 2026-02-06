"""SQLAlchemy ORM models for Polymarket data storage.

Schema design follows category-agnostic principles:
- Markets: All market metadata from Polymarket
- Traders: Discovered trader addresses and backfill status
- Trades: Full detail for target categories (config-driven)
- TraderCategorySummary: Aggregates for non-target categories

All models use SQLAlchemy 2.0 declarative style with Mapped[] type hints.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Market(Base):
    """Market metadata from Polymarket.

    Stores question, category, end date, and resolution outcome.
    Used for classification and display across all phases.
    """

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    condition_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    end_date: Mapped[datetime | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    tokens: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_market_category", "category"),
        Index("ix_market_active", "active"),
    )


class Trader(Base):
    """Trader wallet addresses discovered from market participation.

    Tracks first seen, last active, and backfill completion status.
    """

    __tablename__ = "traders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(42), unique=True, nullable=False, index=True)
    first_seen: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    last_active: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    backfill_complete: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)


class Trade(Base):
    """Trade records for target categories (full detail storage).

    Category filtering is config-driven via detail_categories setting.
    Composite indexes optimize time-series queries by trader and market.

    Uses Numeric for financial precision (no float rounding errors).
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # "BUY" or "SELL"
    size: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    asset_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trade_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_trade_trader_timestamp", "trader_address", "timestamp"),
        Index("ix_trade_category_timestamp", "market_id", "timestamp"),
        Index("ix_trade_market_trader", "market_id", "trader_address"),
    )


class TraderCategorySummary(Base):
    """Aggregate summaries for non-target categories.

    Stores total volume and trade count per trader per category.
    Updated incrementally as new trades are discovered.

    This avoids storing full detail for all categories while maintaining
    visibility into trader cross-category activity.
    """

    __tablename__ = "trader_category_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    total_volume: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    trade_count: Mapped[int] = mapped_column(default=0, nullable=False)
    first_trade: Mapped[datetime] = mapped_column(nullable=False)
    last_trade: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (Index("ix_summary_trader_category", "trader_address", "category", unique=True),)
