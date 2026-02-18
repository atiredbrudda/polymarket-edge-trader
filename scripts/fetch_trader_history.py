"""Fetch complete trading history for a trader using blockchain.

This demonstrates the Phase 8 blockchain integration - fetching a trader's
COMPLETE history with NO 100-trade limit.

Usage:
    python fetch_trader_history.py <trader_address>

Example:
    python fetch_trader_history.py 0x1234...
"""

import sys
from sqlalchemy import create_engine

from src.api.client import PolymarketClient
from src.blockchain.client import PolygonBlockchainClient
from src.config.settings import get_settings
from src.db.models import Base
from src.db.session import get_session_factory
from src.pipeline.filters import CategoryFilter
from src.pipeline.ingest import IngestionPipeline
from loguru import logger


def fetch_trader_history_blockchain(trader_address: str):
    """Fetch and display complete trading history for a trader.

    Args:
        trader_address: Trader wallet address (0x...)
    """
    # Setup
    settings = get_settings()

    # Database
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    # API client (needed to fetch market metadata)
    api_client = PolymarketClient(settings=settings)

    # Blockchain client
    blockchain_client = PolygonBlockchainClient(settings=settings)

    # Category filter
    category_filter = CategoryFilter(settings.detail_categories)

    # Pipeline
    pipeline = IngestionPipeline(
        client=api_client,
        session_factory=session_factory,
        category_filter=category_filter,
        blockchain_client=blockchain_client,
    )

    # Ensure trader exists in database
    session = session_factory()
    from src.db.models import Trader
    from datetime import datetime

    existing_trader = session.query(Trader).filter_by(address=trader_address).first()
    if not existing_trader:
        logger.info(f"Creating new trader record for {trader_address[:8]}...")
        new_trader = Trader(
            address=trader_address,
            first_seen=datetime.utcnow(),
            last_active=datetime.utcnow(),
            backfill_complete=False,
        )
        session.add(new_trader)
        session.commit()
    session.close()

    # Fetch complete history from blockchain
    logger.info("="*60)
    logger.info(f"Fetching COMPLETE trading history for {trader_address}")
    logger.info("Using blockchain (NO 100-trade limit!)")
    logger.info("="*60)

    stats = pipeline.ingest_trader_history_blockchain(trader_address)

    # Display results
    logger.info("="*60)
    logger.info("RESULTS:")
    logger.info(f"  Trades found on blockchain: {stats['trades_from_blockchain']}")
    logger.info(f"  Detail trades stored: {stats['detail_count']}")
    logger.info(f"  Summary categories: {stats['summary_count']}")
    logger.info(f"  Already in DB (skipped): {stats['already_in_db']}")
    logger.info(f"  Categories: {', '.join(stats['categories'])}")
    logger.info("="*60)

    # Query database to show stored trades
    session = session_factory()
    from src.db.models import Trade, TraderCategorySummary

    total_trades = session.query(Trade).filter_by(trader_address=trader_address).count()
    summaries = session.query(TraderCategorySummary).filter_by(trader_address=trader_address).all()

    logger.info("DATABASE STATE:")
    logger.info(f"  Total detail trades in DB: {total_trades}")
    logger.info(f"  Category summaries: {len(summaries)}")
    for summary in summaries:
        logger.info(f"    - {summary.category}: {summary.trade_count} trades, ${summary.total_volume:.2f} volume")
    logger.info("="*60)

    session.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_trader_history.py <trader_address>")
        print("\nTo get a trader's address:")
        print("1. Go to their Polymarket profile (e.g., https://polymarket.com/@Xero100i)")
        print("2. Open browser dev tools > Network tab")
        print("3. Look for API calls - the address will be in the URL or response")
        print("\nExample:")
        print("  python fetch_trader_history.py 0x1234567890abcdef...")
        sys.exit(1)

    trader_address = sys.argv[1].strip()

    # Validate address format
    if not trader_address.startswith("0x") or len(trader_address) != 42:
        print(f"Error: Invalid Ethereum address format: {trader_address}")
        print("Expected: 0x followed by 40 hex characters (total 42 chars)")
        sys.exit(1)

    fetch_trader_history_blockchain(trader_address)
