"""Catalog recovery: populate markets.tokens for null-token eSports gap markets.

Fetches eSports events from Gamma API (tag_id=64), extracts token IDs for
markets with NULL tokens, populates markets.tokens, then chains into
patch_missing_catalog_entries() to run Tier 1 classification.

Purpose: Unblock 3,633 trades from 1,451 traders that are currently
unclassifiable because their markets have tokens=NULL.
"""

import json

import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.db.models import Market


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
ESPORTS_TAG_ID = 64
PAGE_SIZE = 200


def _fetch_esports_events_index() -> dict[str, list[dict]]:
    """Fetch all eSports events from Gamma API and build condition_id -> tokens index.

    Queries Gamma API with tag_id=64 (eSports), paginating through all pages.
    Extracts conditionId and clobTokenIds from each event's markets array.

    Returns:
        Dict mapping condition_id -> list of token dicts in format:
        [{"token_id": tid, "outcome": ""}, ...]
    """
    events_index: dict[str, list[dict]] = {}
    offset = 0

    while True:
        params = {
            "active": "false",
            "tag_id": ESPORTS_TAG_ID,
            "limit": PAGE_SIZE,
            "offset": offset,
            "order": "endDate",
            "ascending": "true",
        }

        resp = httpx.get(
            f"{GAMMA_BASE_URL}/events",
            params=params,
            timeout=60.0,
        )
        resp.raise_for_status()
        events = resp.json()

        if not events:
            break

        for event in events:
            markets = event.get("markets", [])
            for market in markets:
                condition_id = market.get("conditionId")
                if not condition_id:
                    continue

                clob_token_ids = market.get("clobTokenIds")
                if not clob_token_ids:
                    continue

                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except json.JSONDecodeError:
                        continue

                if not isinstance(clob_token_ids, list):
                    continue

                tokens = []
                for tid in clob_token_ids:
                    if tid and str(tid) != "0":
                        tokens.append({"token_id": str(tid), "outcome": ""})

                if tokens:
                    events_index[condition_id] = tokens

        if len(events) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    logger.debug(
        f"RECOVER-CATALOG: Fetched {len(events_index)} eSports markets from Gamma API"
    )
    return events_index


def recover_esports_token_gaps(session: Session) -> dict[str, int]:
    """Populate markets.tokens for null-token eSports gap markets, then patch catalog.

    1. Query for eSports markets with NULL tokens that have associated trades
    2. Fetch eSports events from Gamma API to build token lookup
    3. Populate markets.tokens for gap markets found in the index
    4. Call patch_missing_catalog_entries() to run Tier 1 classification

    Args:
        session: SQLAlchemy session (caller manages commit).

    Returns:
        Dict with counts:
        - found: number of gap markets with trades
        - populated: markets where tokens were newly set
        - already_done: markets already having tokens
        - patched: markets patched by catalog patcher
        - local: resolved via Tier 1
        - api: resolved via Tier 2
        - fallback: resolved via Tier 3
    """
    stats = {
        "found": 0,
        "populated": 0,
        "already_done": 0,
        "patched": 0,
        "local": 0,
        "api": 0,
        "fallback": 0,
    }

    gap_markets = (
        session.execute(
            text("""
        SELECT DISTINCT m.condition_id
        FROM markets m
        JOIN trades t ON t.market_id = m.condition_id
        WHERE m.tokens IS NULL AND LOWER(m.category) = 'esports'
    """)
        )
        .scalars()
        .all()
    )

    stats["found"] = len(gap_markets)

    if not gap_markets:
        logger.info("RECOVER-CATALOG: No null-token eSports gap markets found")
        return stats

    logger.info(f"RECOVER-CATALOG: Found {len(gap_markets)} gap markets to recover")

    events_index = _fetch_esports_events_index()

    # Batch the IN clause query to avoid SQLite parameter limit
    markets_to_update = []
    batch_size = 500
    for i in range(0, len(gap_markets), batch_size):
        batch = gap_markets[i : i + batch_size]
        batch_markets = (
            session.query(Market).filter(Market.condition_id.in_(batch)).all()
        )
        markets_to_update.extend(batch_markets)
        if i % 5000 == 0:
            logger.debug(
                f"  Loaded {len(markets_to_update)}/{len(gap_markets)} markets"
            )

    for market in markets_to_update:
        tokens = events_index.get(market.condition_id)
        if tokens:
            if market.tokens is None:
                market.tokens = json.dumps(tokens)
                stats["populated"] += 1
            else:
                stats["already_done"] += 1

    session.commit()

    from src.catalog.patcher import patch_missing_catalog_entries

    patch_stats = patch_missing_catalog_entries(session, gamma_client=None)
    stats["patched"] = patch_stats.get("patched", 0)
    stats["local"] = patch_stats.get("local", 0)
    stats["api"] = patch_stats.get("api", 0)
    stats["fallback"] = patch_stats.get("fallback", 0)

    logger.info(
        f"RECOVER-CATALOG: found={stats['found']}, populated={stats['populated']}, "
        f"already_done={stats['already_done']}, patched={stats['patched']}"
    )

    return stats
