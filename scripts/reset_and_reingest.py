#!/usr/bin/env python3
"""Reset database and re-ingest with fixed trader discovery logic."""

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import get_settings
from src.db.models import Base, Market, Trader, Trade, TraderCategorySummary

# Setup
settings = get_settings()
engine = create_engine(settings.database_url)
SessionFactory = sessionmaker(bind=engine)

logger.info("Clearing traders and trades tables...")

session = SessionFactory()
try:
    # Delete all traders and trades (keep markets)
    deleted_trades = session.query(Trade).delete()
    deleted_summaries = session.query(TraderCategorySummary).delete()
    deleted_traders = session.query(Trader).delete()

    session.commit()

    logger.info(f"Deleted {deleted_traders} traders, {deleted_trades} trades, {deleted_summaries} summaries")
    logger.info("Database reset complete - markets table preserved")

except Exception as e:
    session.rollback()
    logger.error(f"Failed to reset database: {e}")
    raise
finally:
    session.close()

logger.info("\nNext step: Run ingestion pipeline with fixed trader discovery")
logger.info("Command: python3 -m src.cli sweep")
