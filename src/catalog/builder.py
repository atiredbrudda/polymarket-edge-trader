"""Token catalog builder using Gamma API eSports events.

Fetches all eSports events (tag_id=64) from Gamma API — both active and
closed — and writes every clob token ID to token_catalog with
niche_slug='esports'. Since Gamma's tag is Polymarket's own authoritative
classification, no pattern matching is needed: every token here is
guaranteed eSports.
"""

import json
import time

import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
ESPORTS_TAG_ID = 64
PAGE_SIZE = 50


class TokenCatalogBuilder:
    """Builds token_catalog table from Gamma API eSports events.

    Fetches all events with tag_id=64 (eSports) — both active and closed —
    extracts every clobTokenId, and writes to token_catalog with
    niche_slug='esports'. No pattern matching needed since Gamma's tag is
    authoritative.

    Args:
        *args: Ignored (kept for backwards compatibility with old parquet-based
               constructor that took markets_path and taxonomy_path).
        **kwargs: Ignored.
    """

    def __init__(self, *args, **kwargs):
        pass  # All data comes from Gamma API at build time

    def is_built(self, session: Session) -> bool:
        """Check if catalog has been built (table is non-empty).

        Args:
            session: Active SQLAlchemy session

        Returns:
            True if token_catalog table has at least one row
        """
        from src.db.models import TokenCatalog

        count = session.query(TokenCatalog).limit(1).count()
        return count > 0

    def _fetch_all_events(self, active: bool) -> list[dict]:
        """Fetch all eSports events for one active state from Gamma API.

        Paginates until all results are collected.

        Args:
            active: True for active events, False for closed events

        Returns:
            List of event dicts from Gamma API
        """
        all_events = []
        offset = 0

        while True:
            params = {
                "active": str(active).lower(),
                "tag_id": ESPORTS_TAG_ID,
                "limit": PAGE_SIZE,
                "offset": offset,
                "order": "startDate",
                "ascending": "true",
            }
            try:
                resp = httpx.get(
                    f"{GAMMA_BASE_URL}/events",
                    params=params,
                    timeout=30.0,
                )
                resp.raise_for_status()
                events = resp.json()
                if not events:
                    break
                all_events.extend(events)
                if len(events) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
                time.sleep(0.1)
            except Exception as e:
                logger.warning(
                    f"Gamma API error (active={active}, offset={offset}): {e}"
                )
                break

        return all_events

    def build(self, session: Session) -> int:
        """Fetch all eSports events from Gamma API and write to token_catalog.

        Clears any existing rows first (handles re-runs and corrupt state),
        then fetches active + closed eSports events, extracts all token IDs,
        and bulk-inserts with niche_slug='esports'.

        Args:
            session: Active SQLAlchemy session (caller manages commit)

        Returns:
            Number of token rows inserted
        """
        # Clear existing rows (handles corrupt state or re-runs cleanly)
        session.execute(text("DELETE FROM token_catalog"))
        session.commit()
        logger.info("Cleared existing token_catalog rows")

        logger.info("Fetching active eSports events from Gamma API...")
        active_events = self._fetch_all_events(active=True)
        logger.info(f"  Active events: {len(active_events)}")

        logger.info("Fetching closed eSports events from Gamma API...")
        closed_events = self._fetch_all_events(active=False)
        logger.info(f"  Closed events: {len(closed_events)}")

        all_events = active_events + closed_events
        logger.info(f"Total eSports events fetched: {len(all_events)}")

        # Extract one token_catalog row per unique token ID
        token_rows = []
        seen_token_ids: set[str] = set()

        for event in all_events:
            markets = event.get("markets") or []
            for market in markets:
                condition_id = market.get("conditionId") or market.get("condition_id")
                question = market.get("question", "")
                clob_token_ids = market.get("clobTokenIds")

                if not condition_id or not clob_token_ids:
                    continue

                try:
                    token_ids = (
                        json.loads(clob_token_ids)
                        if isinstance(clob_token_ids, str)
                        else clob_token_ids
                    )
                except (json.JSONDecodeError, TypeError):
                    logger.debug(
                        f"Could not parse clobTokenIds for {condition_id[:8]}..."
                    )
                    continue

                for token_id in token_ids:
                    token_str = str(token_id).strip()
                    if not token_str or token_str == "0":
                        continue
                    if token_str in seen_token_ids:
                        continue
                    seen_token_ids.add(token_str)
                    token_rows.append(
                        {
                            "token_id": token_str,
                            "condition_id": str(condition_id),
                            "question": str(question)[:500],
                            "niche_slug": "esports",
                            "node_path": None,
                            "depth": None,
                            "market_type": None,
                        }
                    )

        logger.info(
            f"Extracted {len(token_rows)} unique eSports token rows, writing to SQLite"
        )

        if not token_rows:
            logger.warning("No token rows extracted — check Gamma API connectivity")
            return 0

        session.execute(
            text(
                """
                INSERT OR IGNORE INTO token_catalog
                  (token_id, condition_id, question, niche_slug, node_path, depth, market_type)
                VALUES
                  (:token_id, :condition_id, :question, :niche_slug, :node_path, :depth, :market_type)
                """
            ),
            token_rows,
        )
        session.commit()
        logger.info(f"Token catalog built: {len(token_rows)} rows written")
        return len(token_rows)
