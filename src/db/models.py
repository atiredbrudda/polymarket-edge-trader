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

from sqlalchemy import ForeignKey, Index, Numeric, String
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
    start_date: Mapped[datetime | None] = mapped_column(nullable=True)
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
    proxy_wallet: Mapped[str | None] = mapped_column(String(42), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    has_profile: Mapped[bool] = mapped_column(default=False, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    last_active: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    backfill_complete: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_trader_backfill_complete", "backfill_complete"),)


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


class TaxonomyNode(Base):
    """Taxonomy hierarchy node for market classification.

    Represents a single node in the taxonomy tree (root, game, tournament, team).
    Used to store YAML taxonomy structure in the database for queryable access.
    """

    __tablename__ = "taxonomy_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "esports.cs2.iem-katowice"
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy_nodes.id"), nullable=True)
    depth: Mapped[int] = mapped_column(nullable=False)  # 0=root, 1=game, 2=tournament, 3=team
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)  # root/game/tournament/team
    patterns_json: Mapped[str] = mapped_column(String(2000), nullable=False)  # JSON-encoded list
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_taxonomy_parent", "parent_id"),
        Index("ix_taxonomy_depth", "depth"),
        Index("ix_taxonomy_slug", "slug", unique=True),
    )


class MarketClassification(Base):
    """Market classification result linking markets to taxonomy nodes.

    Stores the classification outcome for each market, including the matched
    taxonomy path, market type, and whether it was flagged for review.
    """

    __tablename__ = "market_classifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)  # condition_id
    taxonomy_node_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy_nodes.id"), nullable=True)
    node_path: Mapped[str | None] = mapped_column(String(300), nullable=True)  # e.g., "eSports.CS2.IEM Katowice.NaVi"
    market_type: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "match" or "prop"
    matched_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)
    flagged_for_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    classified_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_classification_node", "taxonomy_node_id"),
        Index("ix_classification_flagged", "flagged_for_review"),
    )


class Position(Base):
    """Computed trader position in a specific market.

    Stores the result of position calculation from trade history.
    Updated on each position refresh to reflect current state.
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # "LONG", "SHORT", or "FLAT"
    avg_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    first_trade_timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    last_trade_timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    trade_count: Mapped[int] = mapped_column(default=0, nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)  # win/loss/void/flat
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_position_trader_market", "trader_address", "market_id", unique=True),
        Index("ix_position_resolved", "resolved"),
        Index("ix_position_trader", "trader_address"),
        Index("ix_position_market_last_trade", "market_id", "last_trade_timestamp"),
    )


class TraderProfileDB(Base):
    """Trader profile classification result.

    Stores profile type (selective vs active) based on unique market count.
    Named TraderProfileDB to avoid conflict with TraderProfile dataclass in profiles.py.
    """

    __tablename__ = "trader_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), unique=True, nullable=False, index=True)
    profile_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "selective" or "active"
    unique_markets: Mapped[int] = mapped_column(nullable=False)
    total_trades: Mapped[int] = mapped_column(nullable=False)
    threshold_used: Mapped[int] = mapped_column(nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_trader_profile_address", "trader_address", unique=True),)


class PerformanceSnapshot(Base):
    """Performance snapshot for a trader over a specific timeframe.

    Stores realized/unrealized PnL, win rate, volume, and consistency metrics.
    Used for historical evaluation and time-windowed analysis.
    """

    __tablename__ = "performance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)  # "7d", "30d", "90d", "all"
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    total_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    wins: Mapped[int] = mapped_column(nullable=False, default=0)
    losses: Mapped[int] = mapped_column(nullable=False, default=0)
    total_resolved: Mapped[int] = mapped_column(nullable=False, default=0)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    total_volume: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    resolved_markets: Mapped[int] = mapped_column(nullable=False, default=0)
    unresolved_markets: Mapped[int] = mapped_column(nullable=False, default=0)
    is_low_confidence: Mapped[bool] = mapped_column(nullable=False, default=False)
    consistency_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    consistency_signal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    profile_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_snapshot_trader_timeframe", "trader_address", "timeframe", unique=True),
        Index("ix_snapshot_trader", "trader_address"),
        Index("ix_snapshot_timeframe", "timeframe"),
    )


class ExpertiseScore(Base):
    """Expertise score snapshot for a trader in a specific game.

    Stores score history for trend analysis and leaderboard generation.
    Each row is a point-in-time snapshot — new rows inserted on each scoring run.
    """

    __tablename__ = "expertise_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    game_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    taxonomy_depth: Mapped[int] = mapped_column(nullable=False, default=1)
    raw_score: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    percentile_rank: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    win_rate_component: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    concentration_component: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    recency_component: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    sample_size_component: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    consistency_multiplier: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    specialization_label: Mapped[str] = mapped_column(String(50), nullable=False)
    resolved_market_count: Mapped[int] = mapped_column(nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_expertise_trader_game", "trader_address", "game_slug"),
        Index("ix_expertise_game_score", "game_slug", "raw_score"),
        Index("ix_expertise_computed_at", "computed_at"),
        Index("ix_expertise_game_depth", "game_slug", "taxonomy_depth"),
    )


class SignalSnapshot(Base):
    """Signal snapshot representing consensus expert opinion at a point in time.

    Stores the result of consensus detection for a market and direction.
    Each row is a point-in-time snapshot — new rows inserted on each signal computation.
    Follows the append-only pattern established by ExpertiseScore.
    """

    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # "LONG" or "SHORT"
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    expert_count: Mapped[int] = mapped_column(nullable=False)
    total_experts_in_market: Mapped[int] = mapped_column(nullable=False)
    agreement_percentage: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    expert_addresses_json: Mapped[str] = mapped_column(String(5000), nullable=False)
    first_mover_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_signal_market_direction", "market_id", "direction"),
        Index("ix_signal_computed_at", "computed_at"),
        Index("ix_signal_market_computed", "market_id", "computed_at"),
        Index("ix_signal_status", "status"),
    )


class BlockchainSyncState(Base):
    """Tracks blockchain sync progress per trader for incremental updates.

    Stores the last block queried for each trader to avoid re-scanning
    the entire blockchain on subsequent syncs.
    """

    __tablename__ = "blockchain_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), unique=True, nullable=False, index=True)
    last_queried_block: Mapped[int] = mapped_column(nullable=False, default=0)
    last_sync_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    total_trades_found: Mapped[int] = mapped_column(default=0, nullable=False)

    __table_args__ = (Index("ix_sync_state_trader", "trader_address", unique=True),)
