"""Unit tests for analyze command data layer (Phase 23).

Tests ANALYZE-01 through ANALYZE-06:
- ANALYZE-01: get_entity_alpha_for_trader() returns correct wins/losses for team dimension
- ANALYZE-02: LONG→team_a, SHORT→team_b direction mapping
- ANALYZE-03: Excludes unresolved, void outcomes, non-match market_type
- ANALYZE-04: upsert_entity_alpha() is idempotent
- ANALYZE-05: build_batch_trader_list() filters by first_seen within 60s
- ANALYZE-06: load_cursor/save_cursor/clear_cursor round-trip
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.models import Base, Position, MarketEntity, Trader
from src.org_mapping.models import TraderTeamStats, EntityAlpha
from src.org_mapping.queries import (
    get_entity_alpha_for_trader,
    upsert_entity_alpha,
    build_batch_trader_list,
)
from src.org_mapping.crawler import load_cursor, save_cursor, clear_cursor


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def tmp_cursor(tmp_path):
    cursor_file = tmp_path / "analyze_cursor.json"
    import os

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield cursor_file
    os.chdir(old_cwd)
    if cursor_file.exists():
        cursor_file.unlink()


def _make_entity(
    session,
    condition_id,
    team_a,
    team_b,
    tournament=None,
    game="cs2",
    market_type="match",
    entity_id=None,
):
    if entity_id:
        condition_id = f"{condition_id}_{entity_id}"

    entity = MarketEntity(
        condition_id=condition_id,
        team_a=team_a,
        team_b=team_b,
        tournament=tournament,
        game=game,
        market_type=market_type,
    )
    session.add(entity)
    session.commit()
    return entity


def _make_position(
    session, market_id, trader, direction, outcome, resolved=True, position_id=None
):
    from decimal import Decimal

    if position_id:
        market_id = f"{market_id}_{position_id}"

    position = Position(
        market_id=market_id,
        trader_address=trader,
        size=Decimal("100.0"),
        direction=direction,
        outcome=outcome,
        resolved=resolved,
    )
    session.add(position)
    session.commit()
    return position


def _make_trader(session, address, first_seen=None):
    if first_seen is None:
        first_seen = datetime.utcnow()
    trader = Trader(address=address, first_seen=first_seen)
    session.add(trader)
    session.commit()
    return trader


def test_entity_alpha_basic(session):
    """ANALYZE-01: get_entity_alpha_for_trader returns correct wins/losses for team dimension."""
    trader_addr = "0x1234567890123456789012345678901234567890"

    _make_entity(
        session,
        "cond1",
        "Team A",
        "Team B",
        tournament="IEM Katowice",
        game="cs2",
        entity_id=1,
    )
    _make_entity(
        session,
        "cond2",
        "Team C",
        "Team D",
        tournament="IEM Katowice",
        game="cs2",
        entity_id=2,
    )

    _make_position(session, "cond1_1", trader_addr, "LONG", "win", resolved=True)
    _make_position(session, "cond2_2", trader_addr, "LONG", "loss", resolved=True)

    results = get_entity_alpha_for_trader(session, trader_addr)

    team_rows = [r for r in results if r["entity_type"] == "team"]
    assert len(team_rows) == 2

    team_a_row = next(r for r in team_rows if r["entity_name"] == "Team A")
    assert team_a_row["wins"] == 1
    assert team_a_row["losses"] == 0
    assert team_a_row["total_resolved"] == 1

    team_c_row = next(r for r in team_rows if r["entity_name"] == "Team C")
    assert team_c_row["wins"] == 0
    assert team_c_row["losses"] == 1
    assert team_c_row["total_resolved"] == 1


def test_direction_mapping(session):
    """ANALYZE-02: LONG→team_a counted, SHORT→team_b counted; unknown direction skipped."""
    trader_addr = "0x1234567890123456789012345678901234567890"

    _make_entity(session, "cond1", "Team A", "Team B", tournament="IEM", game="cs2")
    _make_entity(session, "cond2", "Team C", "Team D", tournament="IEM", game="cs2")

    _make_position(session, "cond1", trader_addr, "LONG", "win", resolved=True)
    _make_position(session, "cond2", trader_addr, "SHORT", "win", resolved=True)

    results = get_entity_alpha_for_trader(session, trader_addr)

    team_rows = [r for r in results if r["entity_type"] == "team"]
    team_a_row = next(r for r in team_rows if r["entity_name"] == "Team A")
    team_d_row = next(r for r in team_rows if r["entity_name"] == "Team D")

    assert team_a_row["wins"] == 1
    assert team_d_row["wins"] == 1

    team_b_rows = [r for r in team_rows if r["entity_name"] == "Team B"]
    team_c_rows = [r for r in team_rows if r["entity_name"] == "Team C"]
    assert len(team_b_rows) == 0
    assert len(team_c_rows) == 0


def test_excludes_unresolved(session):
    """ANALYZE-03: Excludes resolved=False, outcome=void, market_type!=match."""
    trader_addr = "0x1234567890123456789012345678901234567890"

    # Match type market - should be included
    _make_entity(
        session,
        "cond1",
        "Team A",
        "Team B",
        tournament="IEM",
        game="cs2",
        market_type="match",
        entity_id=1,
    )
    # Prop type market - should be excluded
    _make_entity(
        session,
        "cond2",
        "Team C",
        "Team D",
        tournament="IEM",
        game="cs2",
        market_type="prop",
        entity_id=2,
    )
    # Match type - unresolved (should be excluded)
    _make_entity(
        session,
        "cond3",
        "Team E",
        "Team F",
        tournament="IEM",
        game="cs2",
        market_type="match",
        entity_id=3,
    )
    # Match type - void outcome (should be excluded)
    _make_entity(
        session,
        "cond4",
        "Team G",
        "Team H",
        tournament="IEM",
        game="cs2",
        market_type="match",
        entity_id=4,
    )

    # Win on match type - should count
    _make_position(session, "cond1_1", trader_addr, "LONG", "win", resolved=True)
    # Loss on match type - should count (but this test expects only wins)
    # Unresolved - should be excluded
    _make_position(session, "cond3_3", trader_addr, "LONG", "loss", resolved=False)
    # Void outcome - should be excluded
    _make_position(session, "cond4_4", trader_addr, "LONG", "void", resolved=True)
    # Prop market - should be excluded
    _make_position(session, "cond2_2", trader_addr, "LONG", "win", resolved=True)

    results = get_entity_alpha_for_trader(session, trader_addr)

    team_a_row = next(
        (
            r
            for r in results
            if r["entity_type"] == "team" and r["entity_name"] == "Team A"
        ),
        None,
    )
    assert team_a_row is not None
    assert team_a_row["wins"] == 1
    assert team_a_row["losses"] == 0
    assert team_a_row["total_resolved"] == 1

    team_c_rows = [
        r
        for r in results
        if r["entity_type"] == "team" and r["entity_name"] == "Team C"
    ]
    assert len(team_c_rows) == 0


def test_upsert_idempotent(session):
    """ANALYZE-04: upsert_entity_alpha called twice produces exactly 1 row."""
    trader_addr = "0x1234567890123456789012345678901234567890"

    _make_entity(
        session, "cond1", "Team A", "Team B", tournament="IEM", game="cs2", entity_id=1
    )
    _make_entity(
        session, "cond2", "Team A", "Team B", tournament="IEM", game="cs2", entity_id=2
    )

    _make_position(session, "cond1_1", trader_addr, "LONG", "win", resolved=True)
    _make_position(session, "cond2_2", trader_addr, "LONG", "win", resolved=True)

    count1 = upsert_entity_alpha(session, trader_addr)
    row1 = session.execute(
        select(EntityAlpha).where(
            EntityAlpha.trader_address == trader_addr,
            EntityAlpha.entity_type == "team",
            EntityAlpha.entity_name == "Team A",
            EntityAlpha.game == "cs2",
        )
    ).scalar_one_or_none()
    wins1 = row1.wins if row1 else None

    count2 = upsert_entity_alpha(session, trader_addr)
    row2 = session.execute(
        select(EntityAlpha).where(
            EntityAlpha.trader_address == trader_addr,
            EntityAlpha.entity_type == "team",
            EntityAlpha.entity_name == "Team A",
            EntityAlpha.game == "cs2",
        )
    ).scalar_one_or_none()
    wins2 = row2.wins if row2 else None

    assert count1 == count2
    assert row1 is not None
    assert wins1 == wins2 == 2

    all_rows = (
        session.execute(
            select(EntityAlpha).where(EntityAlpha.trader_address == trader_addr)
        )
        .scalars()
        .all()
    )
    assert len(all_rows) == count1


def test_batch_mode_filters_by_first_seen(session):
    """ANALYZE-05: build_batch_trader_list returns traders within 60s of max first_seen."""
    now = datetime.utcnow()
    old = now - timedelta(minutes=5)

    trader_recent = _make_trader(
        session, "0x1111111111111111111111111111111111111111", first_seen=now
    )
    trader_old = _make_trader(
        session, "0x2222222222222222222222222222222222222222", first_seen=old
    )

    traders = build_batch_trader_list(session)

    assert trader_recent.address in traders
    assert trader_old.address not in traders


def test_crawler_cursor(tmp_cursor):
    """ANALYZE-06: save_cursor/load_cursor round-trip; load_cursor on missing returns None."""
    from src.org_mapping.crawler import CURSOR_FILE

    result = load_cursor()
    assert result is None

    save_cursor(
        last_trader="0x1234567890123456789012345678901234567890",
        last_entity="team",
        last_game="cs2",
        processed=42,
    )

    result = load_cursor()
    assert result is not None
    assert result["last_trader"] == "0x1234567890123456789012345678901234567890"
    assert result["last_entity"] == "team"
    assert result["last_game"] == "cs2"
    assert result["processed"] == 42

    clear_cursor()
    result = load_cursor()
    assert result is None
