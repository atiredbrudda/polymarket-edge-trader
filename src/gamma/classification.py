"""Token classification from Gamma event tags."""

import json

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.db.models import GammaEvent


def _extract_classification(tags: list[dict]) -> tuple[str | None, int | None]:
    """Extract node_path and depth from Gamma event tags.

    Args:
        tags: List of tag dicts with 'slug' keys.

    Returns:
        Tuple of (node_path, depth) or (None, None) if no sub-classification.
    """
    tag_slugs = [t.get("slug", "").strip() for t in tags if t.get("slug", "").strip()]
    non_esports = [s for s in tag_slugs if s != "esports"]
    if not non_esports:
        return None, None
    depth = min(len(non_esports), 3)
    path_parts = ["esports"] + non_esports[:depth]
    node_path = "/".join(path_parts)
    return node_path, depth


def classify_tokens_from_gamma_events(session: Session) -> dict[str, int]:
    """Classify tokens in token_catalog using Gamma event tags.

    Reads gamma_events table and updates token_catalog with node_path
    and depth for each token linked to a Gamma event with sub-classification
    tags (game, tournament, team).

    Args:
        session: SQLAlchemy session (caller manages commit).

    Returns:
        Dict with counts: token_update_attempts, skipped_no_tags, skipped_no_tokens, skipped_shallow.
        Note: token_update_attempts is the number of token IDs submitted for classification;
        actual DB rows updated may be lower (idempotency guard skips tokens already at
        equal or deeper depth, and tokens absent from token_catalog are unaffected).
    """
    token_update_attempts = 0
    skipped_no_tags = 0
    skipped_no_tokens = 0
    skipped_shallow = 0

    events = session.query(GammaEvent).all()
    logger.info(f"Processing {len(events)} gamma events for token classification")

    update_rows = []

    for event in events:
        if not event.tags:
            skipped_no_tags += 1
            continue

        try:
            tags = json.loads(event.tags)
        except (json.JSONDecodeError, TypeError):
            skipped_no_tags += 1
            continue

        node_path, depth = _extract_classification(tags)
        if node_path is None:
            skipped_shallow += 1
            continue

        if not event.clob_token_ids:
            skipped_no_tokens += 1
            continue

        try:
            token_ids = json.loads(event.clob_token_ids)
        except (json.JSONDecodeError, TypeError):
            skipped_no_tokens += 1
            continue

        for token_id in token_ids:
            if token_id:
                update_rows.append(
                    {"token_id": token_id, "node_path": node_path, "depth": depth}
                )

    if update_rows:
        session.execute(
            text(
                """
                UPDATE token_catalog
                SET node_path = :node_path,
                    depth = :depth
                WHERE token_id = :token_id
                  AND niche_slug = 'esports'
                  AND (depth IS NULL OR depth < :depth)
            """
            ),
            update_rows,
        )
        token_update_attempts = len(update_rows)

    logger.info(
        f"Classification complete: {token_update_attempts} token classification attempts, "
        f"{skipped_shallow} shallow, {skipped_no_tags} no_tags, "
        f"{skipped_no_tokens} no_tokens"
    )
    return {
        "token_update_attempts": token_update_attempts,
        "skipped_no_tags": skipped_no_tags,
        "skipped_no_tokens": skipped_no_tokens,
        "skipped_shallow": skipped_shallow,
    }
