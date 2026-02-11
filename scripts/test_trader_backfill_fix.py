#!/usr/bin/env python3
"""Test the fixed trader history backfill on a single trader."""

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.config.settings import get_settings
from src.pipeline.filters import CategoryFilter
from src.pipeline.ingest import IngestionPipeline

# Setup
settings = get_settings()
engine = create_engine(settings.database_url)
SessionFactory = sessionmaker(bind=engine)
client = PolymarketClient(settings)

# Create category filter (eSports is detail category)
category_filter = CategoryFilter(detail_categories=["eSports"])

# Create pipeline
pipeline = IngestionPipeline(
    client=client,
    session_factory=SessionFactory,
    category_filter=category_filter,
)

# Test with one of the LoL traders
test_trader = "0x0774722ffc23e9d176b77eadcd207ab1f87db1fb"

logger.info(f"Testing trader history backfill for {test_trader[:8]}...")
logger.info("This trader should have:")
logger.info("  - Trades in the LoL market (detail storage)")
logger.info("  - Possibly trades in other markets (summary storage)")

# Run backfill for this trader
stats = pipeline.ingest_trader_history(test_trader)

logger.info("\n" + "=" * 80)
logger.info("BACKFILL COMPLETE")
logger.info("=" * 80)
logger.info(f"Detail trades stored: {stats['detail_count']}")
logger.info(f"Summary categories: {stats['summary_count']}")
logger.info(f"Categories discovered: {sorted(stats['categories'])}")

# Verify the data in database
from sqlalchemy import text

session = SessionFactory()

# Check detail trades (should be eSports)
result = session.execute(
    text("""
        SELECT m.category, m.question, COUNT(*) as trades
        FROM trades t
        JOIN markets m ON t.market_id = m.condition_id
        WHERE t.trader_address = :addr
        GROUP BY m.category, m.question
    """),
    {"addr": test_trader}
)
trades = result.fetchall()

logger.info("\nDetail trades stored:")
for category, question, count in trades:
    logger.info(f"  {category}: {question[:50]}... ({count} trades)")

# Check category summaries
result = session.execute(
    text("""
        SELECT category, total_volume, trade_count
        FROM trader_category_summaries
        WHERE trader_address = :addr
    """),
    {"addr": test_trader}
)
summaries = result.fetchall()

if summaries:
    logger.info("\nCategory summaries:")
    for category, volume, count in summaries:
        logger.info(f"  {category}: {count} trades, {volume} total volume")
else:
    logger.info("\nNo category summaries (all trades were in detail categories)")

session.close()
