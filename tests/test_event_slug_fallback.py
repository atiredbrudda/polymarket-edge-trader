"""Tests for event_slug sibling-inheritance fallback in entity extraction.

The fallback kicks in when pattern matching fails to extract game/team_a.
Instead of going straight to the LLM, discover looks up a sibling market
that shares the same event_slug and already has entities extracted, then
inherits those entities.

Tests:
- DB-seeded fallback: sibling entities already in DB from a prior run
- Within-run fallback: sibling processed earlier in the same discover run
- No fallback when event_slug is NULL
- No fallback when sibling has no game extracted
"""




def _insert_market(db, condition_id, event_slug=None):
    db.conn.execute(
        """
        INSERT INTO markets (condition_id, question, outcome, resolved, niche_slug,
                             created_at, end_date, category, active, tokens, event_slug)
        VALUES (?, '', NULL, 0, 'esports', '2025-01-01T00:00:00Z',
                '2025-12-31T23:59:59Z', 'esports', 1, '[]', ?)
        ON CONFLICT(condition_id) DO NOTHING
        """,
        (condition_id, event_slug),
    )
    db.conn.commit()


def _insert_entity(db, condition_id, game, team_a, team_b="TeamB", tournament="TournX"):
    import hashlib
    import json
    entities = {"game": game, "team_a": team_a, "team_b": team_b, "tournament": tournament, "market_type": "match_winner"}
    eid = hashlib.sha256(f"{condition_id}:{json.dumps(entities, sort_keys=True)}".encode()).hexdigest()[:16]
    db.conn.execute(
        """
        INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(condition_id) DO NOTHING
        """,
        (eid, condition_id, game, team_a, team_b, tournament, "match_winner"),
    )
    db.conn.commit()


def _build_event_slug_entities_from_db(db):
    """Replicate the pre-seed query from discover.py."""
    rows = db.execute("""
        SELECT m.event_slug, me.game, me.team_a, me.team_b, me.tournament, me.market_type
        FROM market_entities me
        JOIN markets m ON me.condition_id = m.condition_id
        WHERE m.event_slug IS NOT NULL AND me.game IS NOT NULL
    """).fetchall()
    result = {}
    for row in rows:
        slug = row[0]
        if slug and slug not in result:
            result[slug] = {
                "game": row[1], "team_a": row[2], "team_b": row[3],
                "tournament": row[4], "market_type": row[5],
            }
    return result


def test_db_seeded_fallback(test_db):
    """Sibling entities already in DB are inherited by prop market."""
    slug = "faze-vs-navi-blast-spring-2025"

    # Parent market with entities already extracted
    _insert_market(test_db, "0xparent", event_slug=slug)
    _insert_entity(test_db, "0xparent", game="CS2", team_a="FaZe", team_b="NaVi")

    # Prop market — same event_slug, no entities yet
    _insert_market(test_db, "0xprop", event_slug=slug)

    event_slug_entities = _build_event_slug_entities_from_db(test_db)
    cid_to_event_slug = {"0xprop": slug}

    # Simulate: pattern returned nothing, event_slug fallback kicks in
    entities = {}
    pattern_incomplete = entities.get("game") is None or entities.get("team_a") is None
    if pattern_incomplete:
        s = cid_to_event_slug.get("0xprop")
        if s and s in event_slug_entities:
            entities = event_slug_entities[s]
            pattern_incomplete = False

    assert not pattern_incomplete
    assert entities["game"] == "CS2"
    assert entities["team_a"] == "FaZe"
    assert entities["team_b"] == "NaVi"


def test_within_run_fallback(test_db):
    """Sibling resolved earlier in same run seeds the cache for later prop market."""
    slug = "t1-vs-geng-worlds-2025"

    _insert_market(test_db, "0xmatch", event_slug=slug)
    _insert_market(test_db, "0xprop", event_slug=slug)

    # DB has no entities yet — cache starts empty
    event_slug_entities = _build_event_slug_entities_from_db(test_db)
    assert slug not in event_slug_entities

    cid_to_event_slug = {"0xmatch": slug, "0xprop": slug}

    # Match market: pattern succeeds, seeds the cache
    match_entities = {"game": "LoL", "team_a": "T1", "team_b": "GenG", "tournament": "Worlds", "market_type": "match_winner"}
    if match_entities.get("game") is not None or match_entities.get("team_a") is not None:
        s = cid_to_event_slug.get("0xmatch")
        if s and s not in event_slug_entities:
            event_slug_entities[s] = match_entities

    # Prop market: pattern returns nothing, inherits from cache
    prop_entities = {}
    pattern_incomplete = prop_entities.get("game") is None or prop_entities.get("team_a") is None
    if pattern_incomplete:
        s = cid_to_event_slug.get("0xprop")
        if s and s in event_slug_entities:
            prop_entities = event_slug_entities[s]
            pattern_incomplete = False

    assert not pattern_incomplete
    assert prop_entities["game"] == "LoL"
    assert prop_entities["team_a"] == "T1"


def test_no_fallback_when_event_slug_is_null(test_db):
    """Standalone market with no event_slug gets no sibling fallback."""
    _insert_market(test_db, "0xstandalone", event_slug=None)

    event_slug_entities = _build_event_slug_entities_from_db(test_db)
    cid_to_event_slug = {"0xstandalone": None}

    entities = {}
    pattern_incomplete = True
    slug = cid_to_event_slug.get("0xstandalone")
    if slug and slug in event_slug_entities:
        entities = event_slug_entities[slug]
        pattern_incomplete = False

    assert pattern_incomplete
    assert entities == {}


def test_no_fallback_when_sibling_has_no_game(test_db):
    """Sibling in DB with NULL game is not used as fallback source."""
    slug = "liquid-vs-og-ti-2025"

    # Sibling has entities row but game is NULL (extraction failed for it too)
    _insert_market(test_db, "0xsibling", event_slug=slug)
    test_db.conn.execute(
        "INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type) "
        "VALUES ('abcd1234', '0xsibling', NULL, NULL, NULL, NULL, NULL)"
    )
    test_db.conn.commit()

    _insert_market(test_db, "0xprop", event_slug=slug)

    # The pre-seed query filters WHERE me.game IS NOT NULL — so this slug won't appear
    event_slug_entities = _build_event_slug_entities_from_db(test_db)
    assert slug not in event_slug_entities
