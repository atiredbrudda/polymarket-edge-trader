"""
Trader discovery and position computation for eSports markets.

Provides functions to:
1. Discover eSports traders based on activity thresholds
2. Compute and store positions from trade history
3. Refresh positions for discovered traders
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Trade, MarketClassification, Position, TaxonomyNode
from src.discovery.position_tracker import calculate_position


def discover_esports_traders(
    session: Session,
    min_trades: int = 5,
    min_volume: Decimal = Decimal("500"),
) -> list[str]:
    """
    Discover traders active in eSports-classified markets.

    Filters traders by:
    - At least min_trades distinct trades in eSports markets
    - At least min_volume USD total volume (sum of size * price)

    Args:
        session: SQLAlchemy session
        min_trades: Minimum distinct trades required
        min_volume: Minimum total volume in USD

    Returns:
        List of trader addresses meeting thresholds

    Query joins:
        trades -> market_classifications -> taxonomy_nodes
    Filters for markets classified under eSports taxonomy.
    """
    # Query for traders with eSports activity
    # Join trades -> market_classifications to filter eSports-only markets
    results = (
        session.query(Trade.trader_address)
        .join(
            MarketClassification,
            Trade.market_id == MarketClassification.market_id,
        )
        .join(
            TaxonomyNode,
            MarketClassification.taxonomy_node_id == TaxonomyNode.id,
        )
        .filter(TaxonomyNode.slug.like("esports%"))  # All eSports nodes start with "esports"
        .group_by(Trade.trader_address)
        .having(
            func.count(func.distinct(Trade.trade_id)) >= min_trades,
            func.sum(Trade.size * Trade.price) >= min_volume,
        )
        .all()
    )

    # Extract addresses from result tuples
    trader_addresses = [result[0] for result in results]

    return trader_addresses


def compute_and_store_positions(
    session: Session, trader_address: str
) -> list[Position]:
    """
    Compute and store positions for a trader across all eSports markets.

    For each (trader, market) pair:
    1. Get all trades
    2. Call calculate_position from position_tracker
    3. Upsert Position row (update if exists, insert if new)

    Args:
        session: SQLAlchemy session
        trader_address: Trader's address

    Returns:
        List of Position objects (both new and updated)

    Upsert logic:
        Uses SQLAlchemy merge() which updates if pk exists, inserts otherwise.
        Unique constraint on (trader_address, market_id) ensures no duplicates.
    """
    positions = []

    # Get all eSports markets this trader has traded in
    market_ids = (
        session.query(Trade.market_id.distinct())
        .join(
            MarketClassification,
            Trade.market_id == MarketClassification.market_id,
        )
        .join(
            TaxonomyNode,
            MarketClassification.taxonomy_node_id == TaxonomyNode.id,
        )
        .filter(
            Trade.trader_address == trader_address,
            TaxonomyNode.slug.like("esports%"),
        )
        .all()
    )

    # Process each market
    for (market_id,) in market_ids:
        # Get all trades for this (trader, market) pair
        trades = (
            session.query(Trade)
            .filter_by(trader_address=trader_address, market_id=market_id)
            .order_by(Trade.timestamp)
            .all()
        )

        if not trades:
            continue

        # Calculate position using position_tracker
        position_data = calculate_position(trades)

        # Check if position already exists
        existing_position = (
            session.query(Position)
            .filter_by(trader_address=trader_address, market_id=market_id)
            .first()
        )

        if existing_position:
            # Update existing position
            existing_position.size = position_data.size
            existing_position.direction = position_data.direction
            existing_position.avg_entry_price = position_data.avg_entry_price
            existing_position.entry_timestamp = position_data.entry_timestamp
            existing_position.first_trade_timestamp = position_data.first_trade_timestamp
            existing_position.last_trade_timestamp = position_data.last_trade_timestamp
            existing_position.trade_count = position_data.trade_count
            positions.append(existing_position)
        else:
            # Create new position
            new_position = Position(
                market_id=market_id,
                trader_address=trader_address,
                size=position_data.size,
                direction=position_data.direction,
                avg_entry_price=position_data.avg_entry_price,
                entry_timestamp=position_data.entry_timestamp,
                first_trade_timestamp=position_data.first_trade_timestamp,
                last_trade_timestamp=position_data.last_trade_timestamp,
                trade_count=position_data.trade_count,
            )
            session.add(new_position)
            positions.append(new_position)

    session.commit()

    return positions


def refresh_all_positions(
    session: Session, trader_addresses: Optional[list[str]] = None
) -> dict:
    """
    Refresh positions for multiple traders.

    Args:
        session: SQLAlchemy session
        trader_addresses: List of trader addresses (if None, discovers all eSports traders)

    Returns:
        Statistics dict with:
            - traders_processed: number of traders
            - positions_computed: total positions
            - positions_open: positions with non-zero size
            - positions_flat: positions with zero size

    If trader_addresses is None, calls discover_esports_traders() to get list.
    """
    # If no traders provided, discover them
    if trader_addresses is None:
        from src.config.settings import get_settings

        settings = get_settings()
        trader_addresses = discover_esports_traders(
            session,
            min_trades=settings.trader_min_trades,
            min_volume=settings.trader_min_volume,
        )

    stats = {
        "traders_processed": 0,
        "positions_computed": 0,
        "positions_open": 0,
        "positions_flat": 0,
    }

    # Process each trader
    for trader_address in trader_addresses:
        positions = compute_and_store_positions(session, trader_address)

        stats["traders_processed"] += 1
        stats["positions_computed"] += len(positions)

        # Count open vs flat positions
        for position in positions:
            if position.direction == "FLAT":
                stats["positions_flat"] += 1
            else:
                stats["positions_open"] += 1

    return stats
