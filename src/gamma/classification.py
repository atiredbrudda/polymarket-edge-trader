"""Token classification from Gamma event tags."""

import json

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.db.models import GammaEvent, TaxonomyNode


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


def backfill_market_classifications(session: Session) -> dict[str, int]:
    """Update MarketClassification.taxonomy_node_id for rows where
    MarketClassification.node_path exists but taxonomy_node_id
    doesn't point to a game-level node.

    This fixes the classification at tournament/team level to point to
    the correct game-level node (e.g., "eSports.League of Legends.LCS.100 Thieves"
    should point to game node "esports.league of legends", not the tournament or team node).

    Caller must commit after this returns.
    """
    # Get all game-level taxonomy nodes
    game_nodes = {
        n.slug.lower().replace(" ", ""): n.id
        for n in session.query(TaxonomyNode).filter_by(node_type="game").all()
    }
    logger.info(f"Game nodes for backfill: {game_nodes}")

    # Get all MarketClassification rows with node_path (use mc.node_path, not token_catalog)
    mc_rows = session.execute(
        text("""
            SELECT mc.id, mc.market_id, mc.taxonomy_node_id, mc.node_path
            FROM market_classifications mc
            WHERE mc.node_path IS NOT NULL
        """)
    ).fetchall()

    updated = 0
    skipped_no_match = 0
    already_correct = 0

    for mc_id, market_id, current_tax_id, node_path in mc_rows:
        if not node_path:
            skipped_no_match += 1
            continue

        # Extract game slug from node_path
        # Examples:
        #   "eSports" -> need game level
        #   "eSports.League of Legends" -> game: esports.league of legends
        #   "eSports.League of Legends.LCS" -> game: esports.league of legends
        #   "eSports.League of Legends.LCS.100 Thieves" -> game: esports.league of legends

        # Get the game part (first two elements, or just first if only one)
        parts = node_path.split(".")
        if len(parts) < 2:
            skipped_no_match += 1
            continue

        # Build game slug: "esports.<game>"
        # Handle both "eSports" and "esports" prefix
        base = parts[0].lower()
        if base == "esports" or base == "esports":
            game_slug = "esports." + parts[1].lower().split("/")[0]
        else:
            game_slug = base + "." + parts[1].lower().split("/")[0]

        game_slug_normalized = game_slug.replace(" ", "")

        # Find matching game node ID
        target_tax_id = game_nodes.get(game_slug_normalized)

        if target_tax_id is None:
            skipped_no_match += 1
            continue

        # Update if different from current
        if current_tax_id != target_tax_id:
            session.execute(
                text(
                    "UPDATE market_classifications SET taxonomy_node_id = :new_id WHERE id = :mc_id"
                ),
                {"new_id": target_tax_id, "mc_id": mc_id},
            )
            updated += 1
        else:
            already_correct += 1

    logger.info(
        f"Classification backfill: {updated} updated, {already_correct} already correct, {skipped_no_match} skipped"
    )
    return {"updated": updated, "skipped_no_match": skipped_no_match}
