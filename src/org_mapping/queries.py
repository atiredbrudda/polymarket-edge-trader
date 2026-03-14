"""Query functions for org/team mapping statistics.

Direction convention (Phase 22, consumed by Phase 23):
  LONG position = trader bet on team_a (YES side of binary market)
  SHORT position = trader bet on team_b (NO side of binary market)

Only match-type markets with resolved win/loss outcomes are included.
Void, flat, unresolved, and prop markets are excluded from all calculations.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Position, MarketEntity
from src.evaluation.metrics import calculate_win_rate
from src.org_mapping.models import TraderTeamStats


def get_team_stats_for_trader(session: Session, trader_address: str) -> list[dict]:
    """Return per-team win/loss stats for a trader from resolved match positions.

    Direction mapping:
      LONG = trader bet on team_a (YES side)
      SHORT = trader bet on team_b (NO side)

    Returns:
        List of dicts: {team_name, game, wins, losses, total_resolved, win_rate}
        win_rate is Decimal (0-100) or None if no resolved positions.
        Empty list if trader has no qualifying positions.
    """
    stmt = (
        select(Position, MarketEntity)
        .join(MarketEntity, Position.market_id == MarketEntity.condition_id)
        .where(
            Position.trader_address == trader_address,
            Position.resolved == True,
            Position.outcome.in_(["win", "loss"]),
            MarketEntity.market_type == "match",
        )
    )
    rows = session.execute(stmt).all()

    stats: dict[tuple[str, str | None], dict[str, Any]] = {}
    for pos, entity in rows:
        if pos.direction == "LONG":
            team_name = entity.team_a
        elif pos.direction == "SHORT":
            team_name = entity.team_b
        else:
            continue

        if team_name is None:
            continue

        key = (team_name, entity.game)
        if key not in stats:
            stats[key] = {
                "team_name": team_name,
                "game": entity.game,
                "wins": 0,
                "losses": 0,
            }

        if pos.outcome == "win":
            stats[key]["wins"] += 1
        elif pos.outcome == "loss":
            stats[key]["losses"] += 1

    class _Pos:
        def __init__(self, outcome):
            self.resolved = True
            self.outcome = outcome

    results = []
    for (team_name, game), s in stats.items():
        synthetic = [_Pos("win")] * s["wins"] + [_Pos("loss")] * s["losses"]
        rate_result = calculate_win_rate(synthetic)
        total = s["wins"] + s["losses"]
        results.append(
            {
                "team_name": team_name,
                "game": game,
                "wins": s["wins"],
                "losses": s["losses"],
                "total_resolved": total,
                "win_rate": rate_result["win_rate"],
            }
        )

    return results


def compute_and_upsert_team_stats(session: Session, trader_address: str) -> int:
    """Compute team stats for a trader and upsert into trader_team_stats table.

    Idempotent: running twice produces same row count with updated values.
    Uses SELECT-then-UPDATE pattern (existing project convention).

    Returns:
        Number of rows upserted (= number of distinct team+game combinations).
    """
    stats = get_team_stats_for_trader(session, trader_address)

    for s in stats:
        existing = session.execute(
            select(TraderTeamStats).where(
                TraderTeamStats.trader_address == trader_address,
                TraderTeamStats.team_name == s["team_name"],
                TraderTeamStats.game == s["game"],
            )
        ).scalar_one_or_none()

        if existing:
            existing.wins = s["wins"]
            existing.losses = s["losses"]
            existing.total_resolved = s["total_resolved"]
            existing.win_rate = s["win_rate"]
            existing.computed_at = datetime.utcnow()
        else:
            row = TraderTeamStats(
                trader_address=trader_address,
                team_name=s["team_name"],
                game=s["game"],
                wins=s["wins"],
                losses=s["losses"],
                total_resolved=s["total_resolved"],
                win_rate=s["win_rate"],
                computed_at=datetime.utcnow(),
            )
            session.add(row)

    session.commit()
    return len(stats)
