"""Catalog patcher: detects and patches token_catalog gaps after backfill.

Runs automatically at the end of every backfill command. Also callable
standalone via `polymarket patch-catalog`.

3-tier lookup:
  Tier 1: Local join — markets.tokens -> gamma_events.clob_token_ids -> tags
  Tier 2: Gamma API /markets?conditionId= -> tags (batch size 20)
  Tier 3: Fallback — insert with category from markets.category, node_path=NULL
"""

import json
from collections import defaultdict

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.db.models import GammaEvent, Market
from src.gamma.classification import _extract_classification


BATCH_SIZE = 20
API_SLEEP = 0.05
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


def patch_missing_catalog_entries(
    session: Session,
    gamma_client=None,
) -> dict[str, int]:
    """Detect and patch token_catalog gaps.

    Finds trades.market_id values with no token_catalog entry and patches
    them via local gamma_events join, Gamma API, or category-only fallback.

    Args:
        session: SQLAlchemy session (caller manages commit).
        gamma_client: GammaMarketClient instance or None (skips Tier 2).

    Returns:
        Dict with counts: patched, local, api, fallback.
        - patched: total markets where at least 1 row was inserted
        - local: resolved via Tier 1 (gamma_events local lookup)
        - api: resolved via Tier 2 (Gamma API)
        - fallback: resolved via Tier 3 (category-only)
    """
    stats = {"patched": 0, "local": 0, "api": 0, "fallback": 0}

    missing = session.execute(text("""
        SELECT DISTINCT t.market_id
        FROM trades t
        LEFT JOIN token_catalog tc ON t.market_id = tc.condition_id
        WHERE tc.condition_id IS NULL
    """)).scalars().all()

    if not missing:
        logger.info("PATCH-CATALOG: No catalog gaps detected")
        return stats

    logger.info(f"PATCH-CATALOG: Found {len(missing)} gaps to patch")

    markets_map = {
        m.condition_id: m
        for m in session.query(Market).filter(Market.condition_id.in_(missing)).all()
    }

    gamma_index = _build_gamma_event_index(session)

    tier1_resolved = set()
    tier2_batch = []
    tier3_fallback = []

    for condition_id in missing:
        market = markets_map.get(condition_id)
        if not market:
            tier3_fallback.append(condition_id)
            continue

        tier1_result = _try_tier1_local(session, market, gamma_index)
        if tier1_result:
            tier1_resolved.add(condition_id)
        else:
            tier2_batch.append(condition_id)

    if tier1_resolved:
        stats["local"] = len(tier1_resolved)
        stats["patched"] += stats["local"]
        logger.debug(f"Tier 1 resolved {len(tier1_resolved)} via gamma_events")

    tier2_api_resolved, tier2_failed = _try_tier2_api(session, tier2_batch, gamma_client)

    for cid in tier2_api_resolved:
        stats["api"] += 1
        stats["patched"] += 1

    tier3_fallback.extend(tier2_failed)

    if tier3_fallback:
        fallback_count = _try_tier3_fallback(session, tier3_fallback, markets_map, gamma_index)
        stats["fallback"] = fallback_count
        stats["patched"] += fallback_count

    logger.info(
        f"PATCH-CATALOG: patched={stats['patched']} "
        f"local={stats['local']} api={stats['api']} fallback={stats['fallback']}"
    )

    return stats


def _build_gamma_event_index(session: Session) -> dict[str, GammaEvent]:
    """Build token_id -> GammaEvent index for fast Tier 1 lookup."""
    index = {}
    events = session.query(GammaEvent).all()
    for event in events:
        if not event.clob_token_ids:
            continue
        try:
            token_ids = json.loads(event.clob_token_ids)
            if isinstance(token_ids, list):
                for tid in token_ids:
                    index[tid] = event
        except (json.JSONDecodeError, TypeError):
            continue
    return index


def _try_tier1_local(
    session: Session,
    market: Market,
    gamma_index: dict[str, GammaEvent],
) -> bool:
    """Try to resolve gap via local gamma_events lookup (Tier 1)."""
    if not market.tokens:
        return False

    try:
        tokens_data = json.loads(market.tokens)
    except (json.JSONDecodeError, TypeError):
        return False

    if not isinstance(tokens_data, list):
        return False

    rows_to_insert = []
    for token_entry in tokens_data:
        token_id = token_entry.get("token_id")
        if not token_id or token_id == "0":
            continue

        event = gamma_index.get(token_id)
        if not event or not event.tags:
            continue

        try:
            tags = json.loads(event.tags)
        except (json.JSONDecodeError, TypeError):
            continue

        node_path, depth = _extract_classification(tags)
        niche_slug = _derive_niche_slug(market.category, node_path)

        rows_to_insert.append({
            "token_id": token_id,
            "condition_id": market.condition_id,
            "question": market.question,
            "niche_slug": niche_slug,
            "node_path": node_path,
            "depth": depth,
            "market_type": None,
        })

    if rows_to_insert:
        _insert_rows(session, rows_to_insert)
        return True

    return False


def _try_tier2_api(
    session: Session,
    condition_ids: list[str],
    gamma_client,
) -> tuple[list[str], list[str]]:
    """Try to resolve gaps via Gamma API (Tier 2)."""
    if not condition_ids or not gamma_client:
        return [], condition_ids

    resolved = []
    failed = []

    for i in range(0, len(condition_ids), BATCH_SIZE):
        batch = condition_ids[i:i + BATCH_SIZE]
        try:
            if gamma_client.rate_limiter is not None:
                gamma_client.rate_limiter.acquire()
            import httpx
            resp = httpx.get(
                f"{GAMMA_API_BASE}/markets",
                params=[("conditionId", cid) for cid in batch],
                timeout=10,
            )
            resp.raise_for_status()
            markets_data = resp.json()
        except Exception as e:
            logger.debug(f"Tier 2 API batch failed: {e}")
            failed.extend(batch)
            continue

        for market_data in markets_data:
            cid = market_data.get("conditionId")
            if not cid:
                continue

            clob_token_ids = market_data.get("clobTokenIds", [])
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, TypeError):
                    clob_token_ids = []

            if not clob_token_ids:
                failed.append(cid)
                continue

            tags = market_data.get("tags", [])
            
            first_tag = tags[0].get("slug", "").lower() if tags else ""
            is_esports = first_tag == "esports"

            if is_esports:
                node_path, depth = _extract_classification(tags)
                niche_slug = "esports"
            else:
                node_path = None
                depth = None
                niche_slug = first_tag if first_tag else "unknown"

            question = market_data.get("question", "Unknown")

            rows_to_insert = []
            for token_id in clob_token_ids:
                if not token_id or token_id == "0":
                    continue
                rows_to_insert.append({
                    "token_id": token_id,
                    "condition_id": cid,
                    "question": question,
                    "niche_slug": niche_slug,
                    "node_path": node_path,
                    "depth": depth,
                    "market_type": None,
                })

            if rows_to_insert:
                _insert_rows(session, rows_to_insert)
                resolved.append(cid)
            else:
                failed.append(cid)

        import time
        time.sleep(API_SLEEP)

    return resolved, failed


def _try_tier3_fallback(
    session: Session,
    condition_ids: list[str],
    markets_map: dict[str, Market],
    gamma_index: dict[str, GammaEvent],
) -> int:
    """Try to resolve gaps via category-only fallback (Tier 3)."""
    inserted = 0

    for cid in condition_ids:
        market = markets_map.get(cid)
        if not market:
            continue

        if not market.tokens:
            continue

        try:
            tokens_data = json.loads(market.tokens)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(tokens_data, list):
            continue

        niche_slug = _derive_niche_slug(market.category, None)
        rows = []
        for token_entry in tokens_data:
            token_id = token_entry.get("token_id")
            if not token_id or token_id == "0":
                continue
            rows.append({
                "token_id": token_id,
                "condition_id": cid,
                "question": market.question,
                "niche_slug": niche_slug,
                "node_path": None,
                "depth": None,
                "market_type": None,
            })

        if rows:
            _insert_rows(session, rows)
            inserted += 1

    return inserted


def _derive_niche_slug(category: str | None, node_path: str | None) -> str:
    """Derive niche_slug from category or node_path."""
    if node_path and node_path.startswith("esports"):
        return "esports"
    if category:
        return category.lower().strip() or "unknown"
    return "unknown"



def _insert_rows(session: Session, rows: list[dict]) -> None:
    """Insert rows into token_catalog with idempotent INSERT OR IGNORE."""
    if not rows:
        return

    session.execute(
        text("""
            INSERT OR IGNORE INTO token_catalog
              (token_id, condition_id, question, niche_slug, node_path, depth, market_type)
            VALUES (:token_id, :condition_id, :question, :niche_slug, :node_path, :depth, :market_type)
        """),
        rows,
    )
    session.commit()
