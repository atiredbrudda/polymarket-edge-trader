"""Token catalog builder using Gamma API events.

Fetches all events from Gamma API (across all categories) and extracts
clob token ID to condition_id mappings for the token_catalog table.
Supports both eSports-only mode (tag_id=64) and all-categories mode.
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
    """Builds token_catalog table from Gamma API events.

    Fetches events from Gamma API and extracts token→condition_id mappings.
    Supports two modes:
    - eSports-only (tag_id=64): Legacy mode, only eSports events
    - All-categories: Fetches events from all categories (default for Phase 30)

    Args:
        esports_only: If True, only fetch eSports events (tag_id=64)
                     If False, fetch all events across all categories
    """

    def __init__(self, esports_only: bool = False, **kwargs):
        """Initialize builder.

        Args:
            esports_only: If True, only build eSports catalog (legacy mode)
                         If False, build full catalog from all categories
        """
        self.esports_only = esports_only

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
        """Fetch all events for one active state from Gamma API.

        Paginates until all results are collected. If esports_only mode,
        filters by tag_id=64. Otherwise fetches all categories.

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
                "limit": PAGE_SIZE,
                "offset": offset,
                "order": "startDate",
                "ascending": "true",
            }
            # Only add tag_id filter for eSports-only mode
            if self.esports_only:
                params["tag_id"] = ESPORTS_TAG_ID

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
        """Fetch events from Gamma API and write to token_catalog.

        Clears any existing rows first (handles re-runs and corrupt state),
        then fetches events based on mode (esports_only or all-categories),
        extracts all token IDs with category information, and bulk-inserts.

        Args:
            session: Active SQLAlchemy session (caller manages commit)

        Returns:
            Number of token rows inserted
        """
        mode_str = "eSports-only" if self.esports_only else "all-categories"

        # Clear existing rows (handles corrupt state or re-runs cleanly)
        session.execute(text("DELETE FROM token_catalog"))
        session.commit()
        logger.info(f"Cleared existing token_catalog rows ({mode_str} mode)")

        logger.info(f"Fetching active {mode_str} events from Gamma API...")
        active_events = self._fetch_all_events(active=True)
        logger.info(f"  Active events: {len(active_events)}")

        logger.info(f"Fetching closed {mode_str} events from Gamma API...")
        closed_events = self._fetch_all_events(active=False)
        logger.info(f"  Closed events: {len(closed_events)}")

        all_events = active_events + closed_events
        logger.info(f"Total events fetched: {len(all_events)}")

        # Extract one token_catalog row per unique token ID
        token_rows = []
        seen_token_ids: set[str] = set()

        for event in all_events:
            # Extract category from event tags or category field
            category = self._extract_category(event)

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
                            "niche_slug": category,
                            "node_path": category,  # Store category as node_path for now
                            "depth": 1,  # Category level
                            "market_type": "prop",  # Default market type
                        }
                    )

        logger.info(
            f"Extracted {len(token_rows)} unique token rows ({mode_str}), writing to DB"
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
        logger.info(f"Token catalog built: {len(token_rows)} rows written ({mode_str})")
        return len(token_rows)

    def _extract_category(self, event: dict) -> str:
        """Extract category from event tags or category field.

        Args:
            event: Event dict from Gamma API

        Returns:
            Category string (e.g., 'esports', 'sports', 'politics', 'crypto')
        """
        # Try to get from tags first
        tags = event.get("tags") or []
        if tags and len(tags) > 0:
            # Tags are typically dicts with 'name' or 'slug' field
            tag = tags[0]
            if isinstance(tag, dict):
                tag_name = tag.get("name", tag.get("slug", ""))
                if tag_name:
                    return tag_name.lower().replace(" ", "_")

        # Fallback to category field
        category = event.get("category", "unknown")
        if category:
            return str(category).lower().replace(" ", "_")

        return "unknown"
