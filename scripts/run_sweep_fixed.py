#!/usr/bin/env python3
"""Run ingestion sweep with fixed trader discovery."""

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

logger.info("Starting full sweep with fixed trader discovery...")

# Run full sweep
stats = pipeline.run_full_sweep()

logger.info("\n" + "=" * 80)
logger.info("SWEEP COMPLETE")
logger.info("=" * 80)
logger.info(f"Markets ingested: {stats['markets_ingested']}")
logger.info(f"Traders discovered: {stats['traders_discovered']}")
logger.info(f"Trades stored: {stats['trades_stored']}")
logger.info(f"Summaries created: {stats['summaries_created']}")
