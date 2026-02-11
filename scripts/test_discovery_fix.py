#!/usr/bin/env python3
"""Test the fixed trader discovery that stores trades immediately."""

from loguru import logger
from sqlalchemy import create_engine, text
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

logger.info("Step 1: Ingest LoL market")
markets_count = pipeline.ingest_active_markets()
logger.info(f"✓ Ingested {markets_count} market(s)")

logger.info("\nStep 2: Discover traders from LoL market (with immediate trade storage)")
lol_market = "0xd6f59f7f6dd3fa5e30e20b12cb13579dad60f4c61243e4dfd40636c3112fab1d"
new_traders = pipeline.discover_traders_from_market(lol_market)
logger.info(f"✓ Discovered {len(new_traders)} new traders")

# Check database state
session = SessionFactory()

# Count trades
result = session.execute(text("SELECT COUNT(*), COUNT(DISTINCT trader_address) FROM trades"))
trade_count, trader_count = result.fetchone()

logger.info(f"\nDatabase state after discovery:")
logger.info(f"  Trades stored: {trade_count}")
logger.info(f"  Unique traders with trades: {trader_count}")

# Check specific traders
result = session.execute(text("""
    SELECT t.trader_address, COUNT(*) as trade_count
    FROM trades t
    GROUP BY t.trader_address
    ORDER BY trade_count DESC
    LIMIT 5
"""))
top_traders = result.fetchall()

logger.info(f"\nTop 5 traders by trade count:")
for addr, count in top_traders:
    logger.info(f"  {addr[:8]}...: {count} trades")
    logger.info(f"  Profile: https://polymarket.com/profile/{addr}")

session.close()

logger.info("\n" + "="*80)
logger.info("VERIFICATION")
logger.info("="*80)
if trade_count > 0:
    logger.info(f"✓ SUCCESS: {trade_count} LoL market trades were stored during discovery!")
else:
    logger.error(f"✗ FAIL: No trades stored - bug still exists!")
