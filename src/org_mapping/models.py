"""TraderTeamStats ORM model for pre-computed per-team win/loss stats.

Convention for direction mapping (established Phase 22, used by Phase 23):
  LONG position = trader bet on team_a (the "YES" side of the market)
  SHORT position = trader bet on team_b (the "NO" side of the market)
"""

from datetime import datetime
from decimal import Decimal
from sqlalchemy import Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from src.db.models import Base


class TraderTeamStats(Base):
    __tablename__ = "trader_team_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    team_name: Mapped[str] = mapped_column(String(200), nullable=False)
    game: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wins: Mapped[int] = mapped_column(default=0, nullable=False)
    losses: Mapped[int] = mapped_column(default=0, nullable=False)
    total_resolved: Mapped[int] = mapped_column(default=0, nullable=False)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_team_stats_trader_team_game",
            "trader_address",
            "team_name",
            "game",
            unique=True,
        ),
        Index("ix_team_stats_team", "team_name"),
        Index("ix_team_stats_trader", "trader_address"),
    )
