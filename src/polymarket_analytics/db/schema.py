"""Database schema with all 9 core tables, foreign keys, and indexes."""

from pathlib import Path

from src.polymarket_analytics.db.connection import get_db


def create_core_tables(db):
    """Create all 9 core tables with foreign keys.

    Tables are created in dependency order to satisfy foreign key constraints.
    """
    # 1. traders - base table for all trader data
    db.table("traders").create(
        {
            "address": str,  # Primary key - wallet address
            "first_seen": str,  # ISO timestamp
            "last_seen": str,  # ISO timestamp
            "backfill_complete": bool,  # Whether historical backfill is done
            "created_at": str,  # ISO timestamp
        },
        pk="address",
        if_not_exists=True,
    )

    # 2. markets - market metadata
    db.table("markets").create(
        {
            "condition_id": str,  # Primary key - Polymarket condition ID
            "question": str,  # Market question text
            "outcome": str,  # YES/NO/null after resolution
            "resolved": bool,  # Whether market is resolved
            "niche_slug": str,  # e.g., "esports", "politics"
            "created_at": str,  # ISO timestamp
        },
        pk="condition_id",
        if_not_exists=True,
    )

    # 3. market_entities - extracted entities from market questions
    db.table("market_entities").create(
        {
            "id": str,  # Primary key - hash of entity data
            "market_id": str,  # FK to markets.condition_id
            "game": str,  # e.g., "CS2", "LoL"
            "team": str,  # Team name
            "player": str,  # Player name
            "role": str,  # Player role (nullable)
            "niche_slug": str,  # e.g., "esports"
        },
        pk="id",
        foreign_keys=[("market_id", "markets", "condition_id")],
        if_not_exists=True,
    )

    # 4. gamma_events - market-moving events
    db.table("gamma_events").create(
        {
            "id": str,  # Primary key - hash
            "event_type": str,  # Type of event
            "market_condition_id": str,  # Associated market
            "data": str,  # JSON blob
            "timestamp": str,  # ISO timestamp
        },
        pk="id",
        if_not_exists=True,
    )

    # 5. token_catalog - mapping of tokens to conditions
    db.table("token_catalog").create(
        {
            "token_id": str,  # Primary key - Polymarket token ID
            "condition_id": str,  # FK to markets.condition_id
            "question": str,  # Market question
            "niche_slug": str,  # e.g., "esports"
            "node_path": str,  # Hierarchy path
            "created_at": str,  # ISO timestamp
        },
        pk="token_id",
        foreign_keys=[("condition_id", "markets", "condition_id")],
        if_not_exists=True,
    )

    # 6. trades - individual trade records
    db.table("trades").create(
        {
            "trade_id": str,  # Primary key - unique trade ID
            "token_id": str,  # FK to token_catalog.token_id
            "timestamp": str,  # ISO timestamp
            "side": str,  # YES or NO
            "price": float,  # Trade price
            "size": float,  # Trade size
            "market_id": str,  # Denormalized for queries
        },
        pk="trade_id",
        foreign_keys=[("token_id", "token_catalog", "token_id")],
        if_not_exists=True,
    )

    # 7. positions - trader positions aggregated from trades
    db.table("positions").create(
        {
            "id": str,  # Primary key - hash
            "trader_address": str,  # FK to traders.address
            "market_id": str,  # Market reference
            "direction": str,  # LONG/SHORT/FLAT
            "size": float,  # Position size
            "avg_entry_price": float,  # Average entry price
            "entry_timestamp": str,  # ISO timestamp
            "last_trade_timestamp": str,  # ISO timestamp
            "pnl": float,  # Nullable - calculated on resolution
            "resolved": bool,  # Whether position is resolved
        },
        pk="id",
        foreign_keys=[("trader_address", "traders", "address")],
        if_not_exists=True,
    )

    # 8. lift_scores - trader performance scores
    db.table("lift_scores").create(
        {
            "id": str,  # Primary key - hash
            "trader_address": str,  # FK to traders.address
            "clv": float,  # Closed-loop value
            "roi": float,  # Return on investment
            "sharpe": float,  # Sharpe ratio
            "z_clv": float,  # Z-score for CLV
            "z_roi": float,  # Z-score for ROI
            "z_sharpe": float,  # Z-score for Sharpe
            "composite": float,  # Composite score
            "quintile": int,  # 1-5 ranking
            "window_start": str,  # ISO timestamp
            "window_end": str,  # ISO timestamp
        },
        pk="id",
        foreign_keys=[("trader_address", "traders", "address")],
        if_not_exists=True,
    )

    # 9. signals - smart money consensus signals
    db.table("signals").create(
        {
            "id": str,  # Primary key - hash
            "market_id": str,  # Associated market
            "direction": str,  # LONG/SHORT
            "q5_count": int,  # Number of Q5 traders
            "avg_score": float,  # Average composite score
            "first_seen": str,  # ISO timestamp
            "last_updated": str,  # ISO timestamp
            "alerted": bool,  # Whether alert was sent
        },
        pk="id",
        if_not_exists=True,
    )


def create_indexes(db):
    """Create indexes for common query patterns."""
    # token_catalog indexes
    db["token_catalog"].create_index(
        ["condition_id"], if_not_exists=True, index_name="idx_token_condition"
    )
    db["token_catalog"].create_index(
        ["niche_slug"], if_not_exists=True, index_name="idx_token_niche"
    )

    # trades indexes
    db["trades"].create_index(
        ["token_id"], if_not_exists=True, index_name="idx_trades_token"
    )
    db["trades"].create_index(
        ["market_id"], if_not_exists=True, index_name="idx_trades_market"
    )
    db["trades"].create_index(
        ["timestamp"], if_not_exists=True, index_name="idx_trades_timestamp"
    )

    # positions indexes
    db["positions"].create_index(
        ["trader_address"], if_not_exists=True, index_name="idx_positions_trader"
    )
    db["positions"].create_index(
        ["market_id"], if_not_exists=True, index_name="idx_positions_market"
    )
    db["positions"].create_index(
        ["resolved"], if_not_exists=True, index_name="idx_positions_resolved"
    )

    # lift_scores indexes
    db["lift_scores"].create_index(
        ["trader_address"], if_not_exists=True, index_name="idx_lift_trader"
    )
    db["lift_scores"].create_index(
        ["quintile"], if_not_exists=True, index_name="idx_lift_quintile"
    )


def init_database(db_path: Path):
    """Initialize database with all tables and indexes.

    Args:
        db_path: Path to SQLite database file

    Returns:
        sqlite_utils.Database instance with all tables created
    """
    db = get_db(db_path)
    create_core_tables(db)
    create_indexes(db)
    return db
