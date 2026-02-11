#!/usr/bin/env python3
"""Run full sweep with fixed trader history backfill - limit to first 5 traders for testing."""

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.config.settings import get_settings
from src.db.models import Trader
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

logger.info("=" * 80)
logger.info("STARTING FULL SWEEP WITH FIXED TRADER BACKFILL")
logger.info("=" * 80)

# Step 1: Ingest markets
logger.info("\nStep 1: Ingesting active markets...")
markets_count = pipeline.ingest_active_markets()
logger.info(f"✓ Ingested {markets_count} markets")

# Step 2: Discover traders from LoL market
lol_market = "0xd6f59f7f6dd3fa5e30e20b12cb13579dad60f4c61243e4dfd40636c3112fab1d"
logger.info(f"\nStep 2: Discovering traders from LoL market...")
new_traders = pipeline.discover_traders_from_market(lol_market)
logger.info(f"✓ Discovered {len(new_traders)} traders")

# Step 3: Backfill first 5 traders (for testing)
logger.info(f"\nStep 3: Backfilling FIRST 5 traders (testing)...")

session = SessionFactory()
traders_to_backfill = (
    session.query(Trader).filter_by(backfill_complete=False).limit(5).all()
)
session.close()

total_detail_trades = 0
total_summaries = 0

for i, trader in enumerate(traders_to_backfill, 1):
    logger.info(f"\n[{i}/5] Backfilling trader {trader.address[:8]}...")
    try:
        stats = pipeline.ingest_trader_history(trader.address)
        total_detail_trades += stats["detail_count"]
        total_summaries += stats["summary_count"]
        logger.info(
            f"  ✓ {stats['detail_count']} detail trades, "
            f"{stats['summary_count']} category summaries, "
            f"{len(stats['categories'])} total categories"
        )
    except Exception as e:
        logger.error(f"  ✗ Failed: {e}")
        continue

logger.info("\n" + "=" * 80)
logger.info("SWEEP COMPLETE (5 traders)")
logger.info("=" * 80)
logger.info(f"Markets ingested: {markets_count}")
logger.info(f"Traders discovered: {len(new_traders)}")
logger.info(f"Traders backfilled: 5")
logger.info(f"Detail trades stored: {total_detail_trades}")
logger.info(f"Category summaries created: {total_summaries}")
