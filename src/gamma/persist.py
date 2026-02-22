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
        event_id = str(event.get("id", ""))
        if not event_id:
            logger.warning(f"Skipping event with empty id: {event.get('title', 'unknown')}")
            continue

        title = str(event.get("title", "") or "")[:500]
        slug = str(event.get("slug", "") or "")[:200]

        outcome_prices = json.dumps(event.get("outcomePrices") or [])
        tags = json.dumps(event.get("tags") or [])

        clob_token_ids = _extract_token_ids(event)
        clob_token_ids_json = json.dumps(sorted(set(clob_token_ids)))

        start_date = _parse_datetime(event.get("startDate"))
        end_date = _parse_datetime(event.get("endDate"))

        rows.append({
            "event_id": event_id,
            "title": title,
            "slug": slug,
            "outcome_prices": outcome_prices,
            "clob_token_ids": clob_token_ids_json,
            "tags": tags,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "now": now,
        })

    if rows:
        session.execute(
            text("""
                INSERT OR REPLACE INTO gamma_events
                  (event_id, title, slug, outcome_prices, clob_token_ids, tags,
                   start_date, end_date, created_at, updated_at)
                VALUES
                  (:event_id, :title, :slug, :outcome_prices, :clob_token_ids, :tags,
                   :start_date, :end_date, :now, :now)
            """),
            rows,
        )

    logger.info(f"Upserted {len(rows)} gamma events into gamma_events table")
    return len(rows)


def _extract_token_ids(event: dict) -> list[str]:
    """Extract all clobTokenIds from nested markets in an event.

    Args:
        event: Raw event dict from Gamma API

    Returns:
        Flat list of all token ID strings from all markets in the event
    """
    token_ids = []

    for market in event.get("markets") or []:
        raw_ids = market.get("clobTokenIds")
        if raw_ids is None:
            continue

        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                continue

        if isinstance(raw_ids, list):
            for tid in raw_ids:
                if isinstance(tid, str) and tid:
                    token_ids.append(tid)

    return token_ids


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
