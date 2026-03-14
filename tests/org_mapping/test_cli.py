"""Integration test for team-stats CLI command (MAP-07).
Uses in-memory SQLite — no real DB or API calls.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.db.models import Base, Position, MarketEntity
from src.org_mapping.models import TraderTeamStats
from src.org_mapping.queries import (
    compute_and_upsert_team_stats,
    get_team_stats_for_trader,
)


@pytest.fixture
def in_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_get_team_stats_returns_correct_data(in_memory_session):
    """MAP-07: verify query layer returns data before testing CLI formatting."""
    s = in_memory_session
    entity = MarketEntity(
        condition_id="cid-cli-1",
        team_a="NaVi",
        team_b="FaZe",
        game="cs2",
        market_type="match",
    )
    pos = Position(
        market_id="cid-cli-1",
        trader_address="0xDEAD",
        size=Decimal("100"),
        direction="LONG",
        resolved=True,
        outcome="win",
        computed_at=datetime.utcnow(),
    )
    s.add(entity)
    s.add(pos)
    s.commit()

    stats = get_team_stats_for_trader(s, "0xDEAD")
    assert len(stats) == 1
    assert stats[0]["team_name"] == "NaVi"
    assert stats[0]["wins"] == 1
    assert stats[0]["losses"] == 0

    count = compute_and_upsert_team_stats(s, "0xDEAD")
    assert count == 1

    from sqlalchemy import select

    rows = (
        s.execute(
            select(TraderTeamStats).where(TraderTeamStats.trader_address == "0xDEAD")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].team_name == "NaVi"
    assert rows[0].wins == 1
