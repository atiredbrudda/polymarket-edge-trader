"""Unit tests for org_mapping query functions (MAP-01..MAP-06)."""

import pytest
from decimal import Decimal
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.db.models import Base, Position, MarketEntity
from src.org_mapping.models import TraderTeamStats
from src.org_mapping.queries import (
    get_team_stats_for_trader,
    compute_and_upsert_team_stats,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _make_entity(
    session, condition_id, team_a, team_b, game="cs2", market_type="match"
):
    e = MarketEntity(
        condition_id=condition_id,
        team_a=team_a,
        team_b=team_b,
        game=game,
        market_type=market_type,
    )
    session.add(e)


def _make_position(session, market_id, trader, direction, outcome, resolved=True):
    p = Position(
        market_id=market_id,
        trader_address=trader,
        size=Decimal("100"),
        direction=direction,
        resolved=resolved,
        outcome=outcome,
        computed_at=datetime.utcnow(),
    )
    session.add(p)


# MAP-01: basic wins/losses aggregation
def test_team_stats_basic(session):
    _make_entity(session, "cid-1", "NaVi", "FaZe")
    _make_position(session, "cid-1", "0xABC", "LONG", "win")
    session.commit()
    results = get_team_stats_for_trader(session, "0xABC")
    navi = next(r for r in results if r["team_name"] == "NaVi")
    assert navi["wins"] == 1 and navi["losses"] == 0


# MAP-02: LONG=team_a, SHORT=team_b direction mapping
def test_direction_mapping(session):
    _make_entity(session, "cid-2", "NaVi", "FaZe")
    _make_position(
        session, "cid-2", "0xABC", "SHORT", "win"
    )  # SHORT = bet on team_b = FaZe
    session.commit()
    results = get_team_stats_for_trader(session, "0xABC")
    team_names = [r["team_name"] for r in results]
    assert "FaZe" in team_names
    assert "NaVi" not in team_names  # trader did not bet on NaVi


# MAP-03: unresolved, void, flat excluded
def test_excludes_unresolved(session):
    _make_entity(session, "cid-3", "NaVi", "FaZe")
    _make_position(session, "cid-3", "0xABC", "LONG", "void", resolved=True)
    _make_entity(session, "cid-4", "G2", "Astralis")
    _make_position(session, "cid-4", "0xABC", "LONG", None, resolved=False)
    session.commit()
    results = get_team_stats_for_trader(session, "0xABC")
    assert results == []


# MAP-04: prop-type markets excluded
def test_excludes_prop_markets(session):
    _make_entity(session, "cid-5", "NaVi", "FaZe", market_type="prop")
    _make_position(session, "cid-5", "0xABC", "LONG", "win")
    session.commit()
    results = get_team_stats_for_trader(session, "0xABC")
    assert results == []


# MAP-05: upsert idempotency
def test_upsert_idempotent(session):
    _make_entity(session, "cid-6", "NaVi", "FaZe")
    _make_position(session, "cid-6", "0xABC", "LONG", "win")
    session.commit()
    count1 = compute_and_upsert_team_stats(session, "0xABC")
    count2 = compute_and_upsert_team_stats(session, "0xABC")
    from sqlalchemy import select

    rows = (
        session.execute(
            select(TraderTeamStats).where(TraderTeamStats.trader_address == "0xABC")
        )
        .scalars()
        .all()
    )
    assert len(rows) == count1 == count2


# MAP-06: canonical team names stored (not aliases)
def test_canonical_team_names(session):
    # market_entities already stores canonical names (normalizer ran in Phase 21)
    # so team_name in stats must match exactly what's in team_a/team_b fields
    _make_entity(session, "cid-7", "Natus Vincere", "FaZe Clan")
    _make_position(session, "cid-7", "0xABC", "LONG", "win")
    session.commit()
    results = get_team_stats_for_trader(session, "0xABC")
    assert results[0]["team_name"] == "Natus Vincere"
