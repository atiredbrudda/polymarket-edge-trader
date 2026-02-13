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
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import sessionmaker

from src.api.client import PolymarketClient
from src.api.gamma_client import GammaMarketClient
from src.api.models import MarketResponse, TradeResponse
from src.pipeline.time_utils import parse_closing_within
from src.db.models import (
    BlockchainSyncState,
    Market,
    Trader,
    Trade,
    TraderCategorySummary,
)
from src.pipeline.aggregators import group_and_aggregate
from src.pipeline.filters import CategoryFilter, TradeWithCategory
from src.graph.client import GraphClient
from src.graph.converters import graph_trade_to_api_response
from src.datasources.converters import jbecker_trade_to_api_response


class IngestionPipeline:
    """Orchestrates data ingestion from Polymarket API to SQLite database.

    Connects:
    - PolymarketClient: API data fetching
    - CategoryFilter: Trade routing logic
    - SQLAlchemy session: Data persistence
    - Optional GraphClient: Complete trader history from The Graph (preferred)
    - Optional PolygonBlockchainClient: Complete trader history from blockchain (backup)

    Attributes:
        client: Polymarket API client wrapper
        session_factory: SQLAlchemy session factory
        category_filter: Category-based trade router
        jbecker_client: Optional JBecker dataset client for historical trades (primary)
        graph_client: Optional Graph client for instant queries (zero storage)
        blockchain_client: Optional blockchain client for complete history (backup)
    """

    def __init__(
        self,
        client: PolymarketClient,
        session_factory: sessionmaker,
        category_filter: CategoryFilter,
        blockchain_client: Optional[Any] = None,
        graph_client: Optional[GraphClient] = None,
        jbecker_client: Optional[Any] = None,
        gamma_client: Optional[GammaMarketClient] = None,
    ):
        """Initialize ingestion pipeline.

        Args:
            client: Configured PolymarketClient instance
            session_factory: SQLAlchemy session factory for database access
            category_filter: CategoryFilter for routing trades
            blockchain_client: Optional PolygonBlockchainClient for complete history (backup)
            graph_client: Optional GraphClient for The Graph queries (if API insufficient)
            jbecker_client: Optional JBeckerDataset for historical trades (primary tier per cost optimization)
            gamma_client: Optional GammaMarketClient for targeted market scanning
        """
        self.client = client
        self.session_factory = session_factory
        self.category_filter = category_filter
        self.blockchain_client = blockchain_client
        self.graph_client = graph_client
        self.jbecker_client = jbecker_client
        self.gamma_client = gamma_client

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
            logger.info(
                f"DEBUG MODE: Testing with {len(test_condition_ids)} hardcoded markets"
            )
            for condition_id in test_condition_ids:
                market = self.client.get_market(condition_id)
                if market:
                    all_markets.append(market)
            logger.info(f"Loaded {len(all_markets)} test markets")
        else:
            # Full scan mode (slow)
            logger.info("Full scan mode - fetching ALL markets (this will be slow)")
            all_markets_full: list[MarketResponse] = self.client.get_markets(
                active=True
            )
            esports_markets = [m for m in all_markets_full if m.category == "eSports"]
            logger.info(
                f"Found {len(all_markets_full)} total markets, {len(esports_markets)} eSports markets"
            )
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

    def ingest_targeted_markets(
        self,
        niches: tuple[str, ...] = (),
        end_date_max: datetime | None = None,
    ) -> int:
        """Fetch and persist markets matching niche and time filters via Gamma API.

        Uses Gamma API for server-side filtering instead of fetching all markets.
        For each niche, queries Gamma API with tag filter. If end_date_max provided,
        includes it as additional filter. Results are unioned (OR semantics).

        Falls back to CLOB API + client-side filtering if Gamma client unavailable.

        Args:
            niches: Tuple of niche category strings (e.g., ("esports", "crypto"))
            end_date_max: Maximum end date for market closing time filter

        Returns:
            Count of markets processed
        """
        if self.gamma_client is None:
            logger.warning(
                "Gamma client not available, falling back to full market ingestion"
            )
            return self.ingest_active_markets()

        logger.info(
            f"Starting targeted market ingestion (niches={niches}, end_date_max={end_date_max})"
        )

        all_markets: list[dict] = []
        seen_condition_ids: set[str] = set()

        if niches:
            for niche in niches:
                logger.info(f"Fetching markets for niche: {niche}")
                try:
                    markets = self.gamma_client.get_markets(
                        tag=niche,
                        end_date_max=end_date_max,
                        closed=False,
                    )
                    for market in markets:
                        condition_id = market.get("condition_id")
                        if condition_id and condition_id not in seen_condition_ids:
                            seen_condition_ids.add(condition_id)
                            all_markets.append(market)
                    logger.info(f"Fetched {len(markets)} markets for niche '{niche}'")
                except Exception as e:
                    logger.error(f"Failed to fetch markets for niche '{niche}': {e}")
                    continue
        elif end_date_max:
            logger.info(f"Fetching markets with end_date_max: {end_date_max}")
            try:
                markets = self.gamma_client.get_markets(
                    end_date_max=end_date_max,
                    closed=False,
                )
                for market in markets:
                    condition_id = market.get("condition_id")
                    if condition_id and condition_id not in seen_condition_ids:
                        seen_condition_ids.add(condition_id)
                        all_markets.append(market)
                logger.info(f"Fetched {len(markets)} markets with time filter")
            except Exception as e:
                logger.error(f"Failed to fetch markets with time filter: {e}")
                all_markets = []

        if not all_markets:
            logger.info("No markets found matching filters")
            return 0

        logger.info(f"Total unique markets to persist: {len(all_markets)}")

        batch_size = 100
        markets_processed = 0

        session = self.session_factory()
        try:
            for i, market_dict in enumerate(all_markets):
                condition_id = market_dict.get("condition_id")
                if not condition_id:
                    continue

                question = market_dict.get("question", "")
                end_date_iso = market_dict.get("end_date")
                closed = market_dict.get("closed", False)
                active = not closed

                tags = market_dict.get("tags", [])
                category = None
                if tags and isinstance(tags, list):
                    first_tag = tags[0]
                    if isinstance(first_tag, dict):
                        category = first_tag.get("label")
                    elif isinstance(first_tag, str):
                        category = first_tag

                tokens = market_dict.get("tokens", [])
                outcome = None
                if tokens and isinstance(tokens, list):
                    outcome_tokens = [
                        t.get("outcome") for t in tokens if isinstance(t, dict)
                    ]
                    outcome = ",".join(outcome_tokens) if outcome_tokens else None

                existing = (
                    session.query(Market).filter_by(condition_id=condition_id).first()
                )

                if existing:
                    existing.question = question
                    existing.category = category
                    existing.active = active
                    existing.outcome = outcome
                    existing.updated_at = datetime.utcnow()

                    if end_date_iso:
                        try:
                            existing.end_date = datetime.fromisoformat(
                                end_date_iso.replace("Z", "+00:00")
                            )
                        except Exception:
                            pass

                    if tokens:
                        existing.tokens = json.dumps(tokens)
                else:
                    market = Market(
                        condition_id=condition_id,
                        question=question,
                        category=category,
                        active=active,
                        outcome=outcome,
                    )

                    if end_date_iso:
                        try:
                            market.end_date = datetime.fromisoformat(
                                end_date_iso.replace("Z", "+00:00")
                            )
                        except Exception:
                            pass

                    if tokens:
                        market.tokens = json.dumps(tokens)

                    session.add(market)

                markets_processed += 1

                if (i + 1) % batch_size == 0:
                    session.commit()
                    logger.debug(f"Committed batch of {batch_size} markets")

            session.commit()
            logger.info(f"Ingested {markets_processed} targeted markets")

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest targeted markets: {e}")
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
                logger.warning(
                    f"Market {condition_id} not found in database during discovery"
                )
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
                        session.query(Trade)
                        .filter_by(trade_id=trade_response.id)
                        .first()
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
                                        market_response.end_date_iso.replace(
                                            "Z", "+00:00"
                                        )
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
                        logger.warning(
                            f"Failed to fetch market {market_id[:8]}...: {e}"
                        )
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

    def ingest_trader_history_blockchain(
        self,
        trader_address: str,
        use_incremental: bool = True,
    ) -> dict:
        """Ingest complete trader history using blockchain (no 100-trade limit!).

        This is the blockchain-powered alternative to ingest_trader_history().
        Fetches ALL trades from blockchain, not just the 100 most recent.

        Args:
            trader_address: Trader wallet address
            use_incremental: If True, resume from last queried block

        Returns:
            Stats dict with keys:
            - detail_count: Number of detail trades stored
            - summary_count: Number of category summaries created
            - categories: List of categories processed
            - trades_from_blockchain: Total trades found on blockchain
            - already_in_db: Trades skipped due to deduplication
        """
        if not self.blockchain_client:
            raise ValueError(
                "Blockchain client not configured. Pass blockchain_client to __init__."
            )

        # Import here to avoid circular dependency
        from src.blockchain.client import POLYMARKET_START_BLOCK
        from src.blockchain.models import BlockchainTrade

        logger.info(f"Ingesting blockchain history for trader {trader_address[:8]}...")

        session = self.session_factory()
        stats = {
            "detail_count": 0,
            "summary_count": 0,
            "categories": set(),
            "trades_from_blockchain": 0,
            "already_in_db": 0,
        }

        try:
            # Get sync state for incremental updates
            sync_state = (
                session.query(BlockchainSyncState)
                .filter_by(trader_address=trader_address)
                .first()
            )

            if use_incremental and sync_state:
                from_block = sync_state.last_queried_block + 1
                logger.info(f"Resuming sync from block {from_block}")
            else:
                from_block = POLYMARKET_START_BLOCK
                logger.info(f"Starting full sync from block {from_block}")

            # Fetch ALL trades from blockchain
            blockchain_trades = self.blockchain_client.get_trades_by_trader(
                trader_address=trader_address,
                from_block=from_block,
            )

            stats["trades_from_blockchain"] = len(blockchain_trades)

            if not blockchain_trades:
                logger.info(
                    f"No blockchain trades found for trader {trader_address[:8]}..."
                )
                # Mark backfill complete even if no trades
                trader = session.query(Trader).filter_by(address=trader_address).first()
                if trader:
                    trader.backfill_complete = True
                    trader.last_active = datetime.utcnow()
                session.commit()
                return stats

            # Get latest block from trades
            latest_block = max(t.block_number for t in blockchain_trades)

            # Process trades: fetch market metadata and categorize
            market_metadata = {}
            all_trades_with_category: list[TradeWithCategory] = []

            for trade in blockchain_trades:
                # Extract condition ID from trade
                condition_id = trade.extract_condition_id()
                if not condition_id:
                    continue

                # Fetch market metadata if not cached
                if condition_id not in market_metadata:
                    existing_market = (
                        session.query(Market)
                        .filter_by(condition_id=condition_id)
                        .first()
                    )

                    if existing_market:
                        market_metadata[condition_id] = existing_market.category
                    else:
                        # Fetch from API (blockchain doesn't have market metadata)
                        try:
                            market_response = self.client.get_market(condition_id)
                            if market_response:
                                # Store new market
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
                                            market_response.end_date_iso.replace(
                                                "Z", "+00:00"
                                            )
                                        )
                                    except Exception:
                                        pass
                                if market_response.tokens:
                                    new_market.tokens = json.dumps(
                                        market_response.tokens
                                    )

                                session.add(new_market)
                                market_metadata[condition_id] = market_response.category
                            else:
                                market_metadata[condition_id] = None
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch market {condition_id[:8]}...: {e}"
                            )
                            market_metadata[condition_id] = None

                category = market_metadata.get(condition_id)
                if category:
                    # Convert BlockchainTrade to TradeWithCategory
                    # We use the to_api_response() method to get TradeResponse-compatible dict
                    api_dict = trade.to_api_response()
                    api_dict["market"] = condition_id  # Ensure market ID is set
                    api_dict["trader"] = trader_address  # Ensure trader is set

                    try:
                        trade_response = TradeResponse(**api_dict)
                        all_trades_with_category.append(
                            TradeWithCategory(trade=trade_response, category=category)
                        )
                        stats["categories"].add(category)
                    except Exception as e:
                        logger.warning(f"Failed to validate trade: {e}")
                        continue

            if not all_trades_with_category:
                logger.info(
                    f"No valid trades to process for trader {trader_address[:8]}..."
                )
                trader = session.query(Trader).filter_by(address=trader_address).first()
                if trader:
                    trader.backfill_complete = True
                session.commit()
                return stats

            # Route trades using CategoryFilter (same as API-based ingestion)
            detail_trades, summary_trades = self.category_filter.route_trades(
                all_trades_with_category
            )

            # Process detail trades with deduplication
            for trade_with_cat in detail_trades:
                trade_response = trade_with_cat.trade

                # Deduplication check by trade_id
                existing = (
                    session.query(Trade).filter_by(trade_id=trade_response.id).first()
                )

                if existing:
                    stats["already_in_db"] += 1
                    continue

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

            # Process summary trades
            if summary_trades:
                summaries = group_and_aggregate(summary_trades, trader_address)

                for summary_dict in summaries:
                    existing_summary = (
                        session.query(TraderCategorySummary)
                        .filter_by(
                            trader_address=summary_dict["trader_address"],
                            category=summary_dict["category"],
                        )
                        .first()
                    )

                    if existing_summary:
                        existing_summary.total_volume += summary_dict["total_volume"]
                        existing_summary.trade_count += summary_dict["trade_count"]
                        if summary_dict["first_trade"] < existing_summary.first_trade:
                            existing_summary.first_trade = summary_dict["first_trade"]
                        if summary_dict["last_trade"] > existing_summary.last_trade:
                            existing_summary.last_trade = summary_dict["last_trade"]
                        existing_summary.updated_at = datetime.utcnow()
                    else:
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

            # Update or create sync state
            if sync_state:
                sync_state.last_queried_block = latest_block
                sync_state.last_sync_at = datetime.utcnow()
                sync_state.total_trades_found += len(blockchain_trades)
            else:
                sync_state = BlockchainSyncState(
                    trader_address=trader_address,
                    last_queried_block=latest_block,
                    total_trades_found=len(blockchain_trades),
                )
                session.add(sync_state)

            # Mark trader as backfill complete
            trader = session.query(Trader).filter_by(address=trader_address).first()
            if trader:
                trader.backfill_complete = True
                trader.last_active = datetime.utcnow()

            session.commit()

            logger.info(
                f"Blockchain ingestion for {trader_address[:8]}...: "
                f"{stats['detail_count']} detail trades, "
                f"{stats['summary_count']} summaries, "
                f"{stats['already_in_db']} duplicates skipped"
            )

            stats["categories"] = list(stats["categories"])

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest blockchain history: {e}")
            raise
        finally:
            session.close()

        return stats

    def ingest_trader_history_graph(self, trader_address: str) -> dict:
        """Ingest complete trader history using The Graph (INSTANT, ZERO STORAGE).

        This is the PREFERRED method for fetching complete trader histories.
        Uses The Graph's indexed blockchain data instead of scanning 49M blocks.

        Advantages over blockchain scanning:
        - Instant queries (seconds vs 6-7 hours)
        - Zero storage (no local data)
        - Always up-to-date (real-time indexing)
        - No RPC rate limits

        Args:
            trader_address: Trader wallet address

        Returns:
            Stats dict with keys:
            - detail_count: Number of detail trades stored
            - summary_count: Number of category summaries created
            - categories: List of categories processed
            - trades_from_graph: Total trades found from The Graph
            - already_in_db: Trades skipped due to deduplication
        """
        if not self.graph_client:
            raise ValueError(
                "Graph client not configured. Pass graph_client to __init__."
            )

        logger.info(f"Ingesting history for {trader_address[:8]}... from The Graph")

        session = self.session_factory()
        stats = {
            "detail_count": 0,
            "summary_count": 0,
            "categories": set(),
            "trades_from_graph": 0,
            "already_in_db": 0,
        }

        try:
            # Fetch ALL trades from The Graph (instant!)
            graph_trades = self.graph_client.get_trader_trades(trader_address)
            stats["trades_from_graph"] = len(graph_trades)

            if not graph_trades:
                logger.info(f"No Graph trades found for {trader_address[:8]}...")
                # Mark backfill complete even if no trades
                trader = session.query(Trader).filter_by(address=trader_address).first()
                if trader:
                    trader.backfill_complete = True
                    trader.last_active = datetime.utcnow()
                session.commit()
                return stats

            # Convert Graph trades to API format
            # Note: Graph gives us blockchain trades, we need to enrich with market metadata
            market_metadata = {}
            all_trades_with_category = []

            for graph_trade in graph_trades:
                # Extract asset IDs to find markets
                # For now, we'll need to fetch market metadata from API
                # The Graph gives us trades but not market details

                # TODO: Map assetId to condition_id properly
                # For now, skip market classification and store all as detail trades
                # This is a temporary limitation - we could enhance Graph queries
                # or maintain a local asset_id -> condition_id mapping

                try:
                    # Convert to API format
                    trade_response = graph_trade_to_api_response(
                        graph_trade, trader_address
                    )

                    # Check if trade already exists (deduplication by trade ID)
                    existing = (
                        session.query(Trade)
                        .filter_by(trade_id=trade_response.id)
                        .first()
                    )

                    if existing:
                        stats["already_in_db"] += 1
                        continue

                    # Store as detail trade (no categorization for now)
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

                except Exception as e:
                    logger.warning(f"Failed to process Graph trade: {e}")
                    continue

            # Mark trader as backfill complete
            trader = session.query(Trader).filter_by(address=trader_address).first()
            if trader:
                trader.backfill_complete = True
                trader.last_active = datetime.utcnow()

            session.commit()

            logger.info(
                f"Graph ingestion for {trader_address[:8]}...: "
                f"{stats['detail_count']} detail trades, "
                f"{stats['already_in_db']} duplicates skipped"
            )

            stats["categories"] = list(stats["categories"])

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest from Graph: {e}")
            raise
        finally:
            session.close()

        return stats

    def ingest_trader_history_jbecker(self, trader_address: str) -> dict:
        """Ingest trader history from JBecker Parquet dataset.

        Uses DuckDB for instant queries against 33.5GB Parquet dataset.
        This is the PRIMARY tier: free, complete historical data (2020-2026).

        Priority in 4-tier cost-optimized hierarchy (per 09-CONTEXT.md Decision 1):
        JBecker (free, historical) > API (free, recent) > Graph (costs units) > Blockchain (hours)

        Args:
            trader_address: Trader wallet address

        Returns:
            Stats dict with keys:
            - detail_count: Number of detail trades stored
            - trades_from_jbecker: Total trades found from JBecker dataset
            - already_in_db: Trades skipped due to deduplication
            - skipped_invalid: Trades skipped due to conversion/validation errors

        Raises:
            ValueError: If jbecker_client not configured
            FileNotFoundError: If JBecker dataset not available
        """
        if not self.jbecker_client:
            raise ValueError(
                "JBecker client not configured. Pass jbecker_client to __init__."
            )

        logger.info(
            f"Ingesting history for {trader_address[:8]}... from JBecker dataset"
        )

        session = self.session_factory()
        stats = {
            "detail_count": 0,
            "trades_from_jbecker": 0,
            "already_in_db": 0,
            "skipped_invalid": 0,
        }

        try:
            # Query all trades from JBecker dataset
            jbecker_trades = self.jbecker_client.query_trader_history(trader_address)
            stats["trades_from_jbecker"] = len(jbecker_trades)

            if not jbecker_trades:
                logger.info(f"No JBecker trades found for {trader_address[:8]}...")
                # Mark backfill complete even if no trades
                trader = (
                    session.query(Trader)
                    .filter_by(address=trader_address.lower())
                    .first()
                )
                if trader:
                    trader.backfill_complete = True
                    trader.last_active = datetime.utcnow()
                session.commit()
                return stats

            # Convert and store trades with batch deduplication
            batch_size = 1000
            batch = []

            for jbecker_trade in jbecker_trades:
                try:
                    # Convert to API format
                    trade_response = jbecker_trade_to_api_response(
                        jbecker_trade, trader_address
                    )

                    # Check if trade already exists (deduplication by trade ID)
                    existing = (
                        session.query(Trade)
                        .filter_by(trade_id=trade_response.id)
                        .first()
                    )

                    if existing:
                        stats["already_in_db"] += 1
                        continue

                    # Add to batch
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
                    batch.append(trade)
                    stats["detail_count"] += 1

                    # Commit batch if full
                    if len(batch) >= batch_size:
                        for trade in batch:
                            session.add(trade)
                        session.commit()
                        batch = []

                except Exception as e:
                    # Skip invalid trades (e.g., price validation failures)
                    logger.warning(f"Failed to process JBecker trade: {e}")
                    stats["skipped_invalid"] += 1
                    continue

            # Commit remaining batch
            if batch:
                for trade in batch:
                    session.add(trade)
                session.commit()

            # Mark trader as backfill complete
            trader = (
                session.query(Trader).filter_by(address=trader_address.lower()).first()
            )
            if trader:
                trader.backfill_complete = True
                trader.last_active = datetime.utcnow()

            session.commit()

            logger.info(
                f"JBecker ingestion for {trader_address[:8]}...: "
                f"{stats['detail_count']} detail trades, "
                f"{stats['already_in_db']} duplicates skipped, "
                f"{stats['skipped_invalid']} invalid skipped"
            )

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to ingest from JBecker: {e}")
            raise
        finally:
            session.close()

        return stats

    def _get_latest_trade_timestamp(self, trader_address: str) -> Optional[datetime]:
        """Get the most recent trade timestamp for a trader from DB.

        Used for timestamp-based gap filling between JBecker snapshot and current.

        Args:
            trader_address: Trader wallet address

        Returns:
            Most recent trade timestamp or None if no trades found
        """
        session = self.session_factory()
        try:
            from sqlalchemy import func

            result = (
                session.query(func.max(Trade.timestamp))
                .filter_by(trader_address=trader_address.lower())
                .scalar()
            )
            return result
        finally:
            session.close()

    def ingest_trader_history_hybrid(
        self,
        trader_address: str,
        prefer_jbecker: bool = True,
        fill_gap_with_api: bool = True,
        fallback_to_graph: bool = True,
        fallback_to_blockchain: bool = True,
    ) -> dict:
        """Ingest trader history using cost-optimized source hierarchy.

        Priority order (per 09-CONTEXT.md Decision 1 - cost optimization):
        1. JBecker Dataset (free, complete historical 2020-2026) - PRIMARY
        2. API (free, recent trades, <=100 limit) - GAP FILL
        3. The Graph (costs API units, fast) - ONLY IF API INSUFFICIENT
        4. Blockchain (free but 6-7 hours) - LAST RESORT

        Rationale: Bulk analysis of 1,000+ traders should minimize Graph API
        unit consumption. JBecker + API covers most traders for free.

        Args:
            trader_address: Trader wallet address
            prefer_jbecker: Whether to use JBecker dataset as primary source (default: True)
            fill_gap_with_api: Whether to fill gap between JBecker and current with API (default: True)
            fallback_to_graph: Whether to use Graph if API insufficient (default: True)
            fallback_to_blockchain: Whether to use blockchain as last resort (default: True)

        Returns:
            Combined stats dict with keys:
            - source: "hybrid"
            - tiers_used: List of data sources used (in order)
            - Plus all stats from individual ingestion methods
        """
        combined_stats = {"source": "hybrid", "tiers_used": []}
        jbecker_trades_found = False
        latest_timestamp = None

        # Tier 1: JBecker Dataset (PRIMARY - free, complete historical)
        if prefer_jbecker and self.jbecker_client:
            try:
                logger.info(
                    f"Using JBecker dataset for {trader_address[:8]}... (PRIMARY - free)"
                )
                stats = self.ingest_trader_history_jbecker(trader_address)
                combined_stats.update(stats)
                combined_stats["tiers_used"].append("jbecker")
                jbecker_trades_found = stats.get("trades_from_jbecker", 0) > 0

                # Get latest timestamp for gap filling
                if jbecker_trades_found:
                    latest_timestamp = self._get_latest_trade_timestamp(trader_address)
            except Exception as e:
                logger.warning(f"JBecker ingestion failed: {e}")

        # Tier 2: API gap fill (free, recent trades after JBecker snapshot)
        if fill_gap_with_api and jbecker_trades_found and latest_timestamp:
            try:
                logger.info(
                    f"Filling gap with API after {latest_timestamp} for {trader_address[:8]}..."
                )
                api_stats = self.ingest_trader_history(
                    trader_address
                )  # existing method
                combined_stats["tiers_used"].append("api")
                api_trade_count = api_stats.get("detail_count", 0)

                # Tier 3: Graph ONLY if API maxed out (100 trades = likely more exist)
                if api_trade_count >= 100 and fallback_to_graph and self.graph_client:
                    try:
                        logger.info(
                            f"API maxed out (100 trades), using Graph for remaining gap"
                        )
                        graph_stats = self.ingest_trader_history_graph(trader_address)
                        combined_stats["tiers_used"].append("graph")
                    except Exception as e:
                        logger.warning(f"Graph ingestion failed: {e}")
            except Exception as e:
                logger.warning(f"API gap fill failed: {e}")

        # If JBecker had no data, try API directly
        if not jbecker_trades_found and not combined_stats["tiers_used"]:
            try:
                logger.info(f"No JBecker data, trying API for {trader_address[:8]}...")
                api_stats = self.ingest_trader_history(trader_address)
                combined_stats.update(api_stats)
                combined_stats["tiers_used"].append("api")
            except Exception as e:
                logger.warning(f"API ingestion failed: {e}")

        # Tier 4: Blockchain (LAST RESORT - free but 6-7 hours per trader)
        if (
            not combined_stats["tiers_used"]
            and fallback_to_blockchain
            and self.blockchain_client
        ):
            logger.info(f"Using blockchain for {trader_address[:8]}... (LAST RESORT)")
            blockchain_stats = self.ingest_trader_history_blockchain(trader_address)
            combined_stats.update(blockchain_stats)
            combined_stats["tiers_used"].append("blockchain")

        # Ultimate fallback: API without gap context
        if not combined_stats["tiers_used"]:
            logger.info(
                f"All sources exhausted, using API for {trader_address[:8]}... (100 trade limit)"
            )
            combined_stats.update(self.ingest_trader_history(trader_address))
            combined_stats["tiers_used"].append("api")

        return combined_stats

    def run_full_sweep(
        self,
        use_jbecker: bool = True,
        use_blockchain_fallback: bool = True,
        niches: tuple[str, ...] = (),
        closing_within: str | None = None,
    ) -> dict:
        """Execute complete ingestion sweep.

        Steps:
        1. Ingest active markets (targeted or full based on filters)
        2. Discover traders from markets with detail categories
        3. Backfill history for newly discovered traders

        Args:
            use_jbecker: If True and jbecker_client configured, use JBecker dataset as primary (default: True)
            use_blockchain_fallback: If True, fallback to blockchain as last resort (default: True)
            niches: Tuple of niche category strings for targeted scanning
            closing_within: Duration string for time-based filtering (e.g., "48h", "2d")

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

        # Step 1: Ingest markets (targeted or full)
        try:
            if niches or closing_within:
                end_date_max = None
                if closing_within:
                    end_date_max = parse_closing_within(closing_within)
                    logger.info(f"Filtering markets closing before {end_date_max}")

                overall_stats["markets_ingested"] = self.ingest_targeted_markets(
                    niches=niches,
                    end_date_max=end_date_max,
                )
            else:
                overall_stats["markets_ingested"] = self.ingest_active_markets()
        except Exception as e:
            logger.error(f"Market ingestion failed: {e}")
            return overall_stats

        # Step 2: Discover traders from detail category markets
        session = self.session_factory()
        try:
            # Get all active markets in detail categories
            markets = session.query(Market).filter_by(active=True).all()
            detail_markets = [
                m for m in markets if self.category_filter.requires_detail(m.category)
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
                    # Use hybrid method (JBecker -> API -> Graph -> Blockchain)
                    stats = self.ingest_trader_history_hybrid(
                        trader.address,
                        prefer_jbecker=use_jbecker,
                        fallback_to_blockchain=use_blockchain_fallback,
                    )

                    overall_stats["trades_stored"] += stats.get("detail_count", 0)
                    overall_stats["summaries_created"] += stats.get("summary_count", 0)
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
