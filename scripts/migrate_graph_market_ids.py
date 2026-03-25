#!/usr/bin/env python3
"""Migrate Graph trades from synthetic to real market_ids.

This script updates trades with market_id format 'graph_{txhash}_{asset_id}'
to use real condition_id values from the token_catalog table.

Usage:
    python scripts/migrate_graph_market_ids.py [--batch-size 10000] [--dry-run]
"""

import argparse
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Trade, TokenCatalog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def extract_asset_id(market_id: str) -> str | None:
    """Extract asset_id from graph_{txhash}_{asset_id} format.

    Args:
        market_id: Synthetic market_id like 'graph_0xabc123_123456'

    Returns:
        asset_id string or None if format doesn't match
    """
    parts = market_id.split("_")
    if len(parts) >= 3 and parts[0] == "graph":
        return parts[-1]
    return None


def migrate(batch_size: int = 10000, dry_run: bool = False) -> tuple[int, int, int]:
    """Migrate orphaned Graph trades to real condition_ids.

    Args:
        batch_size: Number of trades to update per commit
        dry_run: If True, only count what would be updated without committing

    Returns:
        Tuple of (total_count, updated_count, not_found_count)
    """
    db_path = Path("data/polymarket.db")
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        logger.info("Loading token_catalog into memory...")
        catalog = {
            row.token_id: row.condition_id
            for row in session.query(
                TokenCatalog.token_id, TokenCatalog.condition_id
            ).all()
        }
        logger.info(f"Loaded {len(catalog)} token mappings")

        logger.info("Counting orphaned trades...")
        total_count = (
            session.query(Trade).filter(Trade.market_id.like("graph_%")).count()
        )
        logger.info(f"Found {total_count} orphaned trades")

        if total_count == 0:
            logger.info("No orphaned trades to migrate")
            return 0, 0, 0

        logger.info(f"Processing trades in batches of {batch_size}...")
        updated = 0
        not_found = 0
        batch = []
        batch_count = 0

        orphaned = (
            session.query(Trade)
            .filter(Trade.market_id.like("graph_%"))
            .yield_per(batch_size)
        )

        for trade in orphaned:
            asset_id = extract_asset_id(trade.market_id)

            if asset_id and asset_id in catalog:
                if not dry_run:
                    trade.market_id = catalog[asset_id]
                    batch.append(trade)
                updated += 1
            else:
                not_found += 1

            # Commit batch
            if len(batch) >= batch_size:
                session.commit()
                batch_count += 1
                logger.info(
                    f"Committed batch {batch_count}: {len(batch)} trades updated"
                )
                batch = []

        # Final commit
        if batch:
            session.commit()
            logger.info(f"Committed final batch: {len(batch)} trades updated")

        if dry_run:
            logger.info(f"DRY RUN - no changes committed")

        logger.info(f"Migration complete:")
        logger.info(f"  Total: {total_count}")
        logger.info(f"  Updated: {updated}")
        logger.info(f"  Not found: {not_found}")
        logger.info(f"  Match rate: {updated / total_count * 100:.1f}%")

        return total_count, updated, not_found

    except Exception as e:
        session.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Graph trades from synthetic to real market_ids"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Number of trades to update per commit (default: 10000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be updated without committing",
    )

    args = parser.parse_args()

    logger.info(
        f"Starting migration (batch_size={args.batch_size}, dry_run={args.dry_run})"
    )

    total, updated, not_found = migrate(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        logger.info(f"DRY RUN complete. Would update {updated} of {total} trades.")
    else:
        logger.info(f"Migration complete. Updated {updated} of {total} trades.")

    return 0 if not_found == 0 or updated > 0 else 1


if __name__ == "__main__":
    exit(main())
