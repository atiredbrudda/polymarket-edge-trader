"""Ingestion pipeline connecting API client, category filter, and database.

IngestionPipeline orchestrates:
1. Fetching active markets from Polymarket API
2. Discovering traders from market activity
3. Backfilling trader history with category-based routing
4. Persisting to SQLite with deduplication

This is the integration layer that fulfills DATA-01 through DATA-06.
"""

import json
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.api.models import MarketResponse, TradeResponse
from src.db.models import Market, Trader, Trade, TraderCategorySummary
from src.pipeline.aggregators import group_and_aggregate
from src.pipeline.filters import CategoryFilter, TradeWithCategory


class IngestionPipeline:
    """Orchestrates data ingestion from Polymarket API to SQLite database.

    Connects:
    - PolymarketClient: API data fetching
    - CategoryFilter: Trade routing logic
    - SQLAlchemy session: Data persistence

    Attributes:
        client: Polymarket API client wrapper
        session_factory: SQLAlchemy session factory
        category_filter: Category-based trade router
    """

    def __init__(
        self,
        client: PolymarketClient,
        session_factory: sessionmaker,
        category_filter: CategoryFilter,
    ):
        """Initialize ingestion pipeline.

        Args:
            client: Configured PolymarketClient instance
            session_factory: SQLAlchemy session factory for database access
            category_filter: CategoryFilter for routing trades
        """
        self.client = client
        self.session_factory = session_factory
        self.category_filter = category_filter

    def ingest_active_markets(self) -> int:
        """Fetch and persist active markets from Polymarket API.

        For each market:
        1. Extract metadata (question, category, end_date, outcome, tokens)
        2. Upsert to markets table (update if condition_id exists)
        3. Batch commit per 100 markets for efficiency

        Returns:
            Count of markets processed

        Raises:
            Exception: If database transaction fails
        """
        logger.info("Starting active market ingestion")

        # TEMPORARY DEBUG MODE: Use hardcoded test market instead of full scan
        # TODO: Remove this after debugging - this is ONLY for testing the pipeline
        # Market: LoL: Dragons Esports vs GnG Amazigh (BO3) - Arabian League
        # https://polymarket.com/event/lol-drg-gng-2026-02-11
        test_condition_ids = [
            "0xd6f59f7f6dd3fa5e30e20b12cb13579dad60f4c61243e4dfd40636c3112fab1d",
        ]

        all_markets: list[MarketResponse] = []

        if test_condition_ids:
            logger.info(f"DEBUG MODE: Testing with {len(test_condition_ids)} hardcoded markets")
            for condition_id in test_condition_ids:
                market = self.client.get_market(condition_id)
                if market:
                    all_markets.append(market)
            logger.info(f"Loaded {len(all_markets)} test markets")
        else:
            # Full scan mode (slow)
            logger.info("Full scan mode - fetching ALL markets (this will be slow)")
            all_markets_full: list[MarketResponse] = self.client.get_markets(active=True)
            esports_markets = [m for m in all_markets_full if m.category == "eSports"]
            logger.info(f"Found {len(all_markets_full)} total markets, {len(esports_markets)} eSports markets")
            all_markets = esports_markets

        # Persist markets in batches
        batch_size = 100
        markets_processed = 0

        session = self.session_factory()
        try:
            for i, market_response in enumerate(all_markets):
                # Check if market already exists
                existing = (
                    session.query(Market)
                    .filter_by(condition_id=market_response.condition_id)
                    .first()
                )

                if existing:
                    # Update existing market
                    existing.question = market_response.question
                    existing.category = market_response.category
                    existing.active = market_response.active
                    existing.outcome = market_response.outcome
                    existing.updated_at = datetime.utcnow()

                    # Parse end_date if available
                    if market_response.end_date_iso:
                        try:
                            existing.end_date = datetime.fromisoformat(
                                market_response.end_date_iso.replace("Z", "+00:00")
                            )
                        except Exception:
                            pass

                    # Store tokens as JSON string
                    if market_response.tokens:
                        existing.tokens = json.dumps(market_response.tokens)
                else:
                    # Create new market
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

                markets_processed += 1

                # Commit every batch_size markets
                if (i + 1) % batch_size == 0:
                    session.commit()
                    logger.debug(f"Committed batch of {batch_size} markets")

            # Commit remaining markets
            session.commit()
            logger.info(f"Ingested {markets_processed} active markets")

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest markets: {e}")
            raise
        finally:
            session.close()

        return markets_processed

    def discover_traders_from_market(self, condition_id: str) -> list[str]:
        """Discover trader addresses from market trades and store their trades.

        Fetches all trades for a market, extracts unique trader addresses,
        creates Trader records, and IMMEDIATELY stores their trades from this market.
        This ensures we capture the trades that led to discovery.

        Args:
            condition_id: Market condition ID

        Returns:
            List of newly discovered trader addresses

        Raises:
            Exception: If database transaction fails
        """
        logger.debug(f"Discovering traders from market {condition_id}")

        # Fetch market trades
        trades: list[TradeResponse] = self.client.get_market_trades(condition_id)

        # Extract unique trader addresses
        trader_addresses = {trade.trader for trade in trades}

        # Get market metadata to determine category
        session = self.session_factory()
        new_traders: list[str] = []

        try:
            # Get market category
            market = session.query(Market).filter_by(condition_id=condition_id).first()
            if not market:
                logger.warning(f"Market {condition_id} not found in database during discovery")
                session.close()
                return []

            market_category = market.category

            # Process each trader
            for address in trader_addresses:
                existing = session.query(Trader).filter_by(address=address).first()

                if not existing:
                    # Create new trader record
                    trader = Trader(
                        address=address,
                        first_seen=datetime.utcnow(),
                        last_active=datetime.utcnow(),
                        backfill_complete=False,
                    )
                    session.add(trader)
                    new_traders.append(address)

                # Store trades from this market for this trader (whether new or existing)
                trader_trades = [t for t in trades if t.trader == address]

                for trade_response in trader_trades:
                    # Check if trade already exists (deduplication)
                    existing_trade = (
                        session.query(Trade).filter_by(trade_id=trade_response.id).first()
                    )

                    if not existing_trade:
                        # Only store if this is a detail category
                        if self.category_filter.requires_detail(market_category):
                            trade = Trade(
                                market_id=trade_response.market,
                                trader_address=trade_response.trader,
                                side=trade_response.side,
                                size=trade_response.size,
                                price=trade_response.price,
                                timestamp=trade_response.timestamp,
                                asset_ticker=trade_response.asset_ticker,
                                trade_id=trade_response.id,
                            )
                            session.add(trade)

            session.commit()
            logger.info(
                f"Discovered {len(new_traders)} new traders from market {condition_id}, "
                f"stored trades for {len(trader_addresses)} total traders"
            )

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to discover traders: {e}")
            raise
        finally:
            session.close()

        return new_traders

    def ingest_trader_history(self, trader_address: str) -> dict:
        """Ingest complete trade history for a trader with category routing.

        This implements the locked decision from 01-CONTEXT.md:
        1. Fetch all markets the trader has participated in
        2. For each trade, look up market category from database
        3. Create TradeWithCategory objects
        4. Use CategoryFilter to split into detail and summary trades
        5. Detail trades: Batch insert into trades table
        6. Summary trades: Aggregate by category, upsert to trader_category_summaries
        7. Mark trader as backfill_complete

        Args:
            trader_address: Trader wallet address

        Returns:
            Stats dict with keys:
            - detail_count: Number of detail trades stored
            - summary_count: Number of category summaries created
            - categories: List of categories processed

        Raises:
            Exception: If database transaction fails
        """
        logger.info(f"Ingesting trade history for trader {trader_address[:8]}...")

        session = self.session_factory()
        stats = {"detail_count": 0, "summary_count": 0, "categories": set()}

        try:
            # FIXED: Fetch ALL trades for this trader from API
            all_trader_trades = self.client.get_trader_trades(trader_address)

            if not all_trader_trades:
                logger.info(f"No trades found for trader {trader_address[:8]}...")
                # Still mark as backfill complete
                trader = session.query(Trader).filter_by(address=trader_address).first()
                if trader:
                    trader.backfill_complete = True
                    trader.last_active = datetime.utcnow()
                session.commit()
                return stats

            # Extract unique market IDs from trades
            market_ids = list(set(trade.market for trade in all_trader_trades))
            logger.debug(f"Trader participated in {len(market_ids)} unique markets")

            # Fetch market metadata for each market (if not already in database)
            market_metadata = {}
            for market_id in market_ids:
                # Check if market exists in database
                existing_market = (
                    session.query(Market).filter_by(condition_id=market_id).first()
                )

                if existing_market:
                    market_metadata[market_id] = existing_market.category
                else:
                    # Fetch market metadata from API
                    try:
                        market_response = self.client.get_market(market_id)
                        if market_response:
                            # Store new market in database
                            new_market = Market(
                                condition_id=market_response.condition_id,
                                question=market_response.question,
                                category=market_response.category,
                                active=market_response.active,
                                outcome=market_response.outcome,
                            )

                            if market_response.end_date_iso:
                                try:
                                    new_market.end_date = datetime.fromisoformat(
                                        market_response.end_date_iso.replace("Z", "+00:00")
                                    )
                                except Exception:
                                    pass

                            if market_response.tokens:
                                new_market.tokens = json.dumps(market_response.tokens)

                            session.add(new_market)
                            market_metadata[market_id] = market_response.category
                            logger.debug(
                                f"Discovered new market: {market_response.question[:40]}... ({market_response.category})"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to fetch market {market_id[:8]}...: {e}")
                        # Skip this market if we can't fetch metadata
                        continue

            # Associate trades with categories
            all_trades_with_category: list[TradeWithCategory] = []
            for trade in all_trader_trades:
                category = market_metadata.get(trade.market)
                if category:
                    all_trades_with_category.append(
                        TradeWithCategory(trade=trade, category=category)
                    )
                    stats["categories"].add(category)

            if not all_trades_with_category:
                logger.info(f"No trades found for trader {trader_address[:8]}...")
                # Still mark as backfill complete
                trader = session.query(Trader).filter_by(address=trader_address).first()
                if trader:
                    trader.backfill_complete = True
                    trader.last_active = datetime.utcnow()
                session.commit()
                return stats

            # Route trades using CategoryFilter
            detail_trades, summary_trades = self.category_filter.route_trades(
                all_trades_with_category
            )

            # Process detail trades - insert into trades table
            for trade_with_cat in detail_trades:
                trade_response = trade_with_cat.trade

                # Check if trade already exists (deduplication)
                existing = (
                    session.query(Trade).filter_by(trade_id=trade_response.id).first()
                )

                if not existing:
                    trade = Trade(
                        market_id=trade_response.market,
                        trader_address=trade_response.trader,
                        side=trade_response.side,
                        size=trade_response.size,
                        price=trade_response.price,
                        timestamp=trade_response.timestamp,
                        asset_ticker=trade_response.asset_ticker,
                        trade_id=trade_response.id,
                    )
                    session.add(trade)
                    stats["detail_count"] += 1

            # Process summary trades - aggregate and upsert
            if summary_trades:
                summaries = group_and_aggregate(summary_trades, trader_address)

                for summary_dict in summaries:
                    # Check if summary already exists
                    existing_summary = (
                        session.query(TraderCategorySummary)
                        .filter_by(
                            trader_address=summary_dict["trader_address"],
                            category=summary_dict["category"],
                        )
                        .first()
                    )

                    if existing_summary:
                        # Update existing summary
                        existing_summary.total_volume += summary_dict["total_volume"]
                        existing_summary.trade_count += summary_dict["trade_count"]

                        # Update date range
                        if summary_dict["first_trade"] < existing_summary.first_trade:
                            existing_summary.first_trade = summary_dict["first_trade"]
                        if summary_dict["last_trade"] > existing_summary.last_trade:
                            existing_summary.last_trade = summary_dict["last_trade"]

                        existing_summary.updated_at = datetime.utcnow()
                    else:
                        # Create new summary
                        summary = TraderCategorySummary(
                            trader_address=summary_dict["trader_address"],
                            category=summary_dict["category"],
                            total_volume=summary_dict["total_volume"],
                            trade_count=summary_dict["trade_count"],
                            first_trade=summary_dict["first_trade"],
                            last_trade=summary_dict["last_trade"],
                        )
                        session.add(summary)

                    stats["summary_count"] += 1

            # Mark trader as backfill complete
            trader = session.query(Trader).filter_by(address=trader_address).first()
            if trader:
                trader.backfill_complete = True
                trader.last_active = datetime.utcnow()

            session.commit()

            logger.info(
                f"Ingested trader {trader_address[:8]}...: "
                f"{stats['detail_count']} detail trades, "
                f"{stats['summary_count']} summary categories"
            )

            # Convert set to list for JSON serialization
            stats["categories"] = list(stats["categories"])

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest trader history: {e}")
            raise
        finally:
            session.close()

        return stats

    def run_full_sweep(self) -> dict:
        """Execute complete ingestion sweep.

        Steps:
        1. Ingest all active markets
        2. Discover traders from markets with detail categories
        3. Backfill history for newly discovered traders

        Returns:
            Overall stats dict with keys:
            - markets_ingested: Count of markets processed
            - traders_discovered: Count of new traders found
            - trades_stored: Total detail trades stored
            - summaries_created: Total category summaries created

        Note:
            Uses per-trader error handling - one trader failure doesn't
            fail entire sweep.
        """
        logger.info("Starting full ingestion sweep")

        overall_stats = {
            "markets_ingested": 0,
            "traders_discovered": 0,
            "trades_stored": 0,
            "summaries_created": 0,
        }

        # Step 1: Ingest active markets
        try:
            overall_stats["markets_ingested"] = self.ingest_active_markets()
        except Exception as e:
            logger.error(f"Market ingestion failed: {e}")
            # Don't proceed if we can't fetch markets
            return overall_stats

        # Step 2: Discover traders from detail category markets
        session = self.session_factory()
        try:
            # Get all active markets in detail categories
            markets = session.query(Market).filter_by(active=True).all()
            detail_markets = [
                m
                for m in markets
                if self.category_filter.requires_detail(m.category)
            ]

            logger.info(
                f"Discovering traders from {len(detail_markets)} detail category markets"
            )

            for market in detail_markets:
                try:
                    new_traders = self.discover_traders_from_market(market.condition_id)
                    overall_stats["traders_discovered"] += len(new_traders)
                except Exception as e:
                    logger.warning(
                        f"Failed to discover traders from market {market.condition_id}: {e}"
                    )
                    continue

        finally:
            session.close()

        # Step 3: Backfill newly discovered traders
        session = self.session_factory()
        try:
            # Get traders that need backfill
            traders_to_backfill = (
                session.query(Trader).filter_by(backfill_complete=False).all()
            )

            logger.info(f"Backfilling {len(traders_to_backfill)} traders")

            for trader in traders_to_backfill:
                try:
                    stats = self.ingest_trader_history(trader.address)
                    overall_stats["trades_stored"] += stats["detail_count"]
                    overall_stats["summaries_created"] += stats["summary_count"]
                except Exception as e:
                    logger.error(
                        f"Failed to backfill trader {trader.address[:8]}...: {e}"
                    )
                    # Continue with next trader
                    continue

        finally:
            session.close()

        logger.info(
            f"Full sweep complete: {overall_stats['markets_ingested']} markets, "
            f"{overall_stats['traders_discovered']} traders discovered, "
            f"{overall_stats['trades_stored']} trades stored"
        )

        return overall_stats
