"""Market resolution from Gamma closed events.

Fetches ALL closed events from Gamma API (not just esports) and resolves
markets based on outcomePrices. This covers markets that were created via
Graph/JBecker paths but are not in the Gamma events dataset.
"""

import json
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.api.gamma_client import GammaMarketClient
from src.api.rate_limiter import RateLimiter
from src.db.models import Market


def resolve_markets_from_closed_events(
    session: Session,
    batch_size: int = 200,
) -> dict[str, int]:
    """Resolve markets by fetching ALL closed events from Gamma API.

    Unlike resolve_market_outcomes() which only processes markets linked to
    existing gamma_events rows, this function fetches fresh closed events
    from the Gamma API across ALL categories (not just esports).

    For each closed event:
    1. Extract outcomePrices from each market
    2. Determine winning token (price closest to 1.0, must be > 0.5)
    3. Update market.outcome to "YES" or "NO"
    4. Set market.active = False for resolved markets

    Args:
        session: Active SQLAlchemy session
        batch_size: Events per API request (default 200)

    Returns:
        dict with keys:
            - events_fetched: number of events fetched from API
            - markets_resolved: number of markets resolved
            - markets_updated: number of market rows updated
    """
    client = GammaMarketClient(rate_limiter=RateLimiter(max_per_second=5))

    events_fetched = 0
    markets_resolved = 0
    markets_updated = 0

    logger.info("Fetching closed events from Gamma API (all categories)...")

    offset = 0
    while True:
        events = client.get_events(
            active=False,
            limit=batch_size,
            offset=offset,
        )

        if not events:
            break

        events_fetched += len(events)
        logger.info(f"Fetched {len(events)} events (total: {events_fetched})")

        for event in events:
            event_markets = event.get("markets") or []
            for market_data in event_markets:
                condition_id = market_data.get("conditionId")
                outcome_prices = market_data.get("outcomePrices")

                if not condition_id or not outcome_prices:
                    continue

                winning_token_idx = _determine_winner_index(outcome_prices)
                if winning_token_idx is None:
                    continue

                clob_token_ids = market_data.get("clobTokenIds", [])
                if not clob_token_ids or winning_token_idx >= len(clob_token_ids):
                    continue

                winning_token_id = clob_token_ids[winning_token_idx]

                updated = _update_market_outcome(
                    session, condition_id, winning_token_id, outcome_prices
                )
                markets_resolved += 1
                if updated:
                    markets_updated += 1

        offset += batch_size

    session.commit()

    logger.info(
        f"Resolution complete: {events_fetched} events fetched, "
        f"{markets_resolved} markets processed, {markets_updated} updated"
    )

    return {
        "events_fetched": events_fetched,
        "markets_resolved": markets_resolved,
        "markets_updated": markets_updated,
    }


def _determine_winner_index(outcome_prices: list[str]) -> int | None:
    """Return index of token with outcome_price closest to 1.0 (> 0.5).

    Args:
        outcome_prices: List of price strings (e.g., ["0.85", "0.15"])

    Returns:
        Index of winning token, or None if no clear winner
    """
    if not outcome_prices:
        return None

    best_idx = None
    best_price = 0.5

    for i, price_str in enumerate(outcome_prices):
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            logger.warning(f"Invalid price string: {price_str}")
            continue

        if price > best_price:
            best_price = price
            best_idx = i

    return best_idx


def _update_market_outcome(
    session: Session,
    condition_id: str,
    winning_token_id: str,
    outcome_prices: list[str],
) -> bool:
    """Update a single market's outcome based on winning token.

    Args:
        session: Active SQLAlchemy session
        condition_id: Market condition ID
        winning_token_id: Token ID that won
        outcome_prices: List of outcome prices for logging

    Returns:
        True if market was found and updated, False otherwise
    """
    from decimal import Decimal

    market = (
        session.query(Market).filter(Market.condition_id == condition_id).one_or_none()
    )

    if market is None:
        logger.debug(f"Market {condition_id[:16]}... not found in DB")
        return False

    if market.outcome is not None:
        logger.debug(
            f"Market {condition_id[:16]}... already resolved ({market.outcome})"
        )
        return False

    market.outcome = "YES"
    market.active = False
    market.updated_at = datetime.utcnow()

    logger.debug(
        f"Market {condition_id[:16]}... resolved YES (prices: {outcome_prices[:3]}...)"
    )

    return True
