"""Gamma Events persistence — upserts raw API event dicts to gamma_events table."""

import json
from datetime import datetime

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_gamma_events(events: list[dict], session: Session) -> int:
    """Upsert Gamma API event dicts into the gamma_events table.

    Args:
        events: Raw event dicts from GammaMarketClient.get_closed_esports_events()
        session: Active SQLAlchemy session (caller manages commit)

    Returns:
        Number of rows upserted (inserted or updated)
    """
    rows = []
    now = datetime.utcnow().isoformat()

    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            logger.warning(f"Skipping event with empty id: {event.get('title', 'unknown')}")
            continue

        title = str(event.get("title", "") or "")[:500]
        slug = str(event.get("slug", "") or "")[:200]

        clob_token_ids, outcome_prices = _extract_tokens_and_prices(event)
        clob_token_ids_json = json.dumps(clob_token_ids)
        outcome_prices_json = json.dumps(outcome_prices)
        tags = json.dumps(event.get("tags") or [])

        start_date = _parse_datetime(event.get("startDate"))
        end_date = _parse_datetime(event.get("endDate"))

        rows.append({
            "event_id": event_id,
            "title": title,
            "slug": slug,
            "outcome_prices": outcome_prices_json,
            "clob_token_ids": clob_token_ids_json,
            "tags": tags,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "now": now,
        })

    if rows:
        session.execute(
            text("""
                INSERT INTO gamma_events
                  (event_id, title, slug, outcome_prices, clob_token_ids, tags,
                   start_date, end_date, created_at, updated_at)
                VALUES
                  (:event_id, :title, :slug, :outcome_prices, :clob_token_ids, :tags,
                   :start_date, :end_date, :now, :now)
                ON CONFLICT(event_id) DO UPDATE SET
                  title=excluded.title,
                  slug=excluded.slug,
                  outcome_prices=excluded.outcome_prices,
                  clob_token_ids=excluded.clob_token_ids,
                  tags=excluded.tags,
                  start_date=excluded.start_date,
                  end_date=excluded.end_date,
                  updated_at=excluded.updated_at
            """),
            rows,
        )

    logger.info(f"Upserted {len(rows)} gamma events into gamma_events table")
    return len(rows)


def _extract_tokens_and_prices(event: dict) -> tuple[list[str], list[str]]:
    """Extract clobTokenIds and outcomePrices from nested markets in an event.

    Maintains positional correspondence between tokens and prices by processing
    each market in order and appending token-price pairs together.

    Args:
        event: Raw event dict from Gamma API

    Returns:
        Tuple of (token_ids, prices) where token_ids[i] corresponds to prices[i]
    """
    token_ids = []
    prices = []

    for market in event.get("markets") or []:
        raw_ids = market.get("clobTokenIds")
        raw_prices = market.get("outcomePrices")

        if raw_ids is None:
            continue

        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                continue

        if isinstance(raw_prices, str):
            try:
                raw_prices = json.loads(raw_prices)
            except json.JSONDecodeError:
                raw_prices = None

        if isinstance(raw_ids, list):
            if isinstance(raw_prices, list) and len(raw_prices) == len(raw_ids):
                for tid, price in zip(raw_ids, raw_prices):
                    if isinstance(tid, str) and tid:
                        token_ids.append(tid)
                        prices.append(str(price) if price is not None else "0")
            else:
                for tid in raw_ids:
                    if isinstance(tid, str) and tid:
                        token_ids.append(tid)
                        prices.append("0")

    seen = set()
    unique_token_ids = []
    unique_prices = []
    for tid, price in zip(token_ids, prices):
        if tid not in seen:
            seen.add(tid)
            unique_token_ids.append(tid)
            unique_prices.append(price)

    return unique_token_ids, unique_prices


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string from Gamma API.

    Args:
        value: ISO datetime string (may have Z suffix)

    Returns:
        datetime object or None if value is None/empty
    """
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
