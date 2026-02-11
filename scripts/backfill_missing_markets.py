#!/usr/bin/env python3
"""Backfill market metadata for markets that exist in trades but not in markets table."""

import json
from datetime import datetime

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.config.settings import get_settings
from src.db.models import Base, Market, Trade

# Setup
settings = get_settings()
engine = create_engine(settings.database_url)
SessionFactory = sessionmaker(bind=engine)
client = PolymarketClient(settings)

logger.info("Starting market metadata backfill...")

session = SessionFactory()

try:
    # Get all unique market_ids from trades table
    result = session.execute(
        select(Trade.market_id).distinct()
    ).fetchall()

    trade_market_ids = [row[0] for row in result]
    logger.info(f"Found {len(trade_market_ids)} unique markets in trades table")

    # Get market_ids that already exist in markets table
    existing_markets = session.query(Market.condition_id).all()
    existing_market_ids = [m[0] for m in existing_markets]
    logger.info(f"Found {len(existing_market_ids)} markets already in markets table")

    # Find missing markets
    missing_market_ids = [mid for mid in trade_market_ids if mid not in existing_market_ids]
    logger.info(f"Need to backfill {len(missing_market_ids)} markets")

    # Fetch and insert missing markets
    backfilled = 0
    esports_count = 0
    resolved_count = 0

    for market_id in missing_market_ids:
        try:
            # Fetch market metadata from API
            market_response = client.get_market(market_id)

            if not market_response:
                logger.warning(f"Could not fetch market {market_id[:8]}...")
                continue

            # Create market record
            market = Market(
                condition_id=market_response.condition_id,
                question=market_response.question,
                category=market_response.category,
                active=market_response.active,
                outcome=market_response.outcome,
            )

            # Parse end_date if available
            if market_response.end_date_iso:
                try:
                    market.end_date = datetime.fromisoformat(
                        market_response.end_date_iso.replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            # Store tokens as JSON string
            if market_response.tokens:
                market.tokens = json.dumps(market_response.tokens)

            session.add(market)
            backfilled += 1

            # Track stats
            if market_response.category == "eSports":
                esports_count += 1
                logger.info(f"✓ eSports: {market_response.question[:60]}...")

            if market_response.outcome is not None:
                resolved_count += 1
                logger.info(f"  → RESOLVED (outcome: {market_response.outcome})")

            # Commit every 10 markets
            if backfilled % 10 == 0:
                session.commit()
                logger.info(f"Committed {backfilled} markets...")

        except Exception as e:
            logger.error(f"Failed to backfill market {market_id[:8]}...: {e}")
            continue

    # Final commit
    session.commit()

    logger.info("\n" + "="*80)
    logger.info("BACKFILL COMPLETE")
    logger.info("="*80)
    logger.info(f"Total markets backfilled: {backfilled}")
    logger.info(f"eSports markets: {esports_count}")
    logger.info(f"Resolved markets: {resolved_count}")
    logger.info(f"Active markets: {backfilled - resolved_count}")

except Exception as e:
    session.rollback()
    logger.error(f"Backfill failed: {e}")
    raise
finally:
    session.close()

logger.info("\nNext step: Run scoring on resolved eSports markets")
