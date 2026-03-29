"""Database schema with all 9 core tables, foreign keys, and indexes."""

from pathlib import Path

from src.polymarket_analytics.db.connection import get_db


def create_core_tables(db):
    """Create all 9 core tables with foreign keys.

    Tables are created in dependency order to satisfy foreign key constraints.
    For tables requiring NUMERIC affinity on price/size columns, raw SQL is used
    after initial table creation to enforce proper column types.
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
            "end_date": str,  # Market end date (ISO timestamp) - for 30-day scoring window
            "category": str,  # Market category (e.g., "esports")
            "active": bool,  # Whether market is currently active
            "tokens": str,  # JSON blob of token IDs
        },
        pk="condition_id",
        if_not_exists=True,
    )

    # 3. market_entities - extracted entities from market questions
    db.table("market_entities").create(
        {
            "id": str,  # Primary key - hash of entity data
            "condition_id": str,  # UNIQUE - FK to markets.condition_id (per GUIDE.md)
            "game": str,  # e.g., "CS2", "LoL"
            "team_a": str,  # Team/player A name (per GUIDE.md)
            "team_b": str,  # Team/player B name (per GUIDE.md)
            "tournament": str,  # Tournament name (per GUIDE.md)
            "market_type": str,  # Type of market (per GUIDE.md)
        },
        pk="id",
        foreign_keys=[("condition_id", "markets", "condition_id")],
        if_not_exists=True,
    )

    # 4. gamma_events - raw market data from Gamma API
    # Normalized columns for resolve-outcomes to read outcome field directly
    db.table("gamma_events").create(
        {
            "id": str,  # Primary key - hash
            "condition_id": str,  # Market condition ID (FK to markets.condition_id)
            "question": str,  # Market question text
            "outcome": str,  # YES/NO/null after resolution
            "end_date": str,  # ISO timestamp - when market closes
            "tags": str,  # JSON array of tags from Gamma API
            "active": bool,  # Whether market is currently active
            "niche_slug": str,  # e.g., "esports" - set during ingest
            "created_at": str,  # ISO timestamp - when ingested
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
            "market_type": str,  # Type of market (e.g., "binary", "categorical")
            "created_at": str,  # ISO timestamp
        },
        pk="token_id",
        foreign_keys=[("condition_id", "markets", "condition_id")],
        if_not_exists=True,
    )

    # 6. trades - individual trade records
    # Use raw SQL for NUMERIC affinity on price/size columns
    db.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            token_id TEXT REFERENCES token_catalog(token_id),
            timestamp TEXT,
            side TEXT,
            price NUMERIC(10,6),
            size NUMERIC(20,6),
            market_id TEXT,
            trader_address TEXT
        )
    """)

    # 7. positions - trader positions aggregated from trades
    # Use raw SQL for NUMERIC affinity on price/size/pnl columns
    db.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            trader_address TEXT REFERENCES traders(address),
            market_id TEXT,
            direction TEXT,
            size NUMERIC(20,6),
            avg_entry_price NUMERIC(10,6),
            entry_timestamp TEXT,
            last_trade_timestamp TEXT,
            trade_count INTEGER,
            resolved INTEGER,
            outcome TEXT,
            pnl NUMERIC(20,6)
        )
    """)

    # 8. lift_scores - trader performance scores
    # Use raw SQL for NUMERIC columns
    db.execute("""
        CREATE TABLE IF NOT EXISTS lift_scores (
            id TEXT PRIMARY KEY,
            trader_address TEXT REFERENCES traders(address),
            category TEXT,
            composite_score NUMERIC,
            clv_raw NUMERIC,
            clv_zscore NUMERIC,
            roi_raw NUMERIC,
            roi_zscore NUMERIC,
            sharpe_raw NUMERIC,
            sharpe_zscore NUMERIC,
            quintile INTEGER,
            position_count INTEGER,
            total_pnl NUMERIC,
            window_start TEXT,
            window_end TEXT,
            computed_at TEXT
        )
    """)

    # 9. signals - smart money consensus signals
    # Use raw SQL for NUMERIC affinity on avg_score column
    db.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            market_id TEXT,
            direction TEXT,
            q5_count INTEGER,
            avg_score NUMERIC(10,6),
            first_seen TEXT,
            last_updated TEXT,
            alerted INTEGER
        )
    """)


def create_indexes(db):
    """Create indexes for common query patterns."""
    # token_catalog indexes
    db["token_catalog"].create_index(
        ["condition_id"], if_not_exists=True, index_name="idx_token_condition"
    )
    db["token_catalog"].create_index(
        ["niche_slug"], if_not_exists=True, index_name="idx_token_niche"
    )

    # gamma_events indexes
    db["gamma_events"].create_index(
        ["condition_id"], if_not_exists=True, index_name="idx_gamma_condition"
    )
    db["gamma_events"].create_index(
        ["niche_slug"], if_not_exists=True, index_name="idx_gamma_niche"
    )
    db["gamma_events"].create_index(
        ["end_date"], if_not_exists=True, index_name="idx_gamma_end_date"
    )
    db["gamma_events"].create_index(
        ["active"], if_not_exists=True, index_name="idx_gamma_active"
    )

    # trades indexes - includes trader_address for build-positions aggregation
    db["trades"].create_index(
        ["token_id"], if_not_exists=True, index_name="idx_trades_token"
    )
    db["trades"].create_index(
        ["market_id"], if_not_exists=True, index_name="idx_trades_market"
    )
    db["trades"].create_index(
        ["timestamp"], if_not_exists=True, index_name="idx_trades_timestamp"
    )
    db["trades"].create_index(
        ["trader_address"], if_not_exists=True, index_name="idx_trades_trader_address"
    )
    # Composite index for build-positions query pattern
    db["trades"].create_index(
        ["trader_address", "market_id"],
        if_not_exists=True,
        index_name="idx_trades_trader_market",
    )

    # market_entities - UNIQUE constraint on condition_id via unique index
    db["market_entities"].create_index(
        ["condition_id"],
        if_not_exists=True,
        index_name="idx_market_entities_condition_unique",
        unique=True,
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
