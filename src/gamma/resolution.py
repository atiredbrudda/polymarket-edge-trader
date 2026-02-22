"""Market outcome resolution from Gamma event data.

Determines which side won for each resolved market using outcome_prices
from the gamma_events table, then populates markets.outcome.
"""
import json
from decimal import Decimal, InvalidOperation

from loguru import logger
from sqlalchemy.orm import Session

from src.db.models import GammaEvent, Market


def determine_winner(
    clob_token_ids: list[str],
    outcome_prices: list[str],
) -> str | None:
    """Return the token_id with outcome_price closest to 1.0 (> 0.5).

    Returns None if inputs are malformed or no clear winner (all prices <= 0.5).
    """
    if not clob_token_ids or not outcome_prices:
        return None
    if len(clob_token_ids) != len(outcome_prices):
        logger.warning(
            f"clob_token_ids length {len(clob_token_ids)} != "
            f"outcome_prices length {len(outcome_prices)} — skipping"
        )
        return None

    best_token = None
    best_price = Decimal("0.5")

    for token_id, price_str in zip(clob_token_ids, outcome_prices):
        try:
            price = Decimal(price_str)
        except InvalidOperation:
            logger.warning(f"Invalid price string {price_str!r} for token {token_id[:8]}...")
            continue
        if price > best_price:
            best_price = price
            best_token = token_id

    return best_token


def classify_token_outcome(token_id: str, winning_token_id: str) -> str:
    """Return 'YES' if token_id is the winning token, 'NO' otherwise."""
    return "YES" if token_id == winning_token_id else "NO"


def resolve_market_outcomes(session: Session) -> dict[str, int]:
    """Populate markets.outcome for all markets linked to gamma_events.

    Join strategy: scan markets.tokens JSON field to build an in-memory
    {token_id: Market} lookup dict. This covers ~99.8% of markets
    (vs token_catalog which covers only ~37%).

    Returns:
        {"resolved": N, "skipped_events": M, "skipped_tokens": K}
    """
    resolved = 0
    skipped_events = 0
    skipped_tokens = 0

    token_to_market: dict[str, Market] = {}
    markets_scanned = 0
    for market in session.query(Market).filter(Market.tokens.is_not(None)).all():
        markets_scanned += 1
        try:
            for t in json.loads(market.tokens):
                tid = t.get("token_id")
                if tid:
                    token_to_market[tid] = market
        except (json.JSONDecodeError, TypeError):
            continue
    logger.info(
        f"Built token lookup: {len(token_to_market)} tokens from "
        f"{markets_scanned} markets"
    )

    events = session.query(GammaEvent).all()
    logger.info(f"Processing {len(events)} gamma events for outcome resolution")

    for event in events:
        try:
            token_ids = json.loads(event.clob_token_ids) if event.clob_token_ids else []
            prices = json.loads(event.outcome_prices) if event.outcome_prices else []
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Event {event.event_id}: JSON parse error: {e} — skipping")
            skipped_events += 1
            continue

        winning_token = determine_winner(token_ids, prices)
        if winning_token is None:
            logger.debug(f"Event {event.event_id}: no clear winner (prices={prices[:3]}) — skipping")
            skipped_events += 1
            continue

        for token_id in token_ids:
            market = token_to_market.get(token_id)
            if market is None:
                skipped_tokens += 1
                continue

            market.outcome = classify_token_outcome(token_id, winning_token)
            resolved += 1

    logger.info(
        f"Resolution complete: {resolved} resolved, "
        f"{skipped_events} events skipped, {skipped_tokens} tokens skipped"
    )
    return {"resolved": resolved, "skipped_events": skipped_events, "skipped_tokens": skipped_tokens}
