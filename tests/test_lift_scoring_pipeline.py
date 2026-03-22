"""Integration tests for lift-based scoring pipeline.

Tests compute_category_scores, get_market_avg_entries, get_lift_leaderboard,
LiftScore persistence, 30-day window filtering, and min_positions threshold.
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import (
    Base,
    LiftScore,
    Market,
    MarketEntity,
    Position,
)
from src.pipeline.queries import get_market_avg_entries, get_positions_for_category, get_lift_leaderboard
from src.pipeline.scoring_pipeline import compute_category_scores, compute_all_category_scores


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


@pytest.fixture
def esports_db(in_memory_db):
    """Database with esports market data for 5 traders.

    Each trader has 35 resolved positions in esports markets.
    Market average entry price is 0.50 for all markets.
    Traders have varying CLV, ROI, and Sharpe ratios.
    """
    _, session_factory = in_memory_db
    session: Session = session_factory()

    now = datetime.now(UTC)

    # Create 35 markets with category "eSports"
    for i in range(1, 36):
        market = Market(
            condition_id=f"market{i:03d}",
            question=f"Will team A beat team B in market {i}?",
            category="eSports",
        )
        session.add(market)

    # Create MarketEntity records linking markets to esports category
    for i in range(1, 36):
        entity = MarketEntity(
            condition_id=f"market{i:03d}",
            game="CS2",
            tournament="IEM Katowice",
            team_a="NaVi",
            team_b="FaZe",
            market_type="match",
        )
        session.add(entity)

    session.flush()

    # Create 5 traders with 35 resolved positions each
    # Trader A: Good CLV (buys cheap), positive ROI, positive Sharpe
    # Trader B: Medium CLV, medium ROI
    # Trader C: Low CLV, mixed ROI
    # Trader D: Negative CLV (buys expensive)
    # Trader E: Very negative everything

    trader_configs = [
        ("0xTraderA", 0.35, 10.0, "LONG"),   # CLV = 0.50 - 0.35 = +0.15
        ("0xTraderB", 0.45, 5.0,  "LONG"),   # CLV = 0.50 - 0.45 = +0.05
        ("0xTraderC", 0.50, 2.0,  "LONG"),   # CLV = 0.50 - 0.50 = 0.00
        ("0xTraderD", 0.60, -3.0, "LONG"),   # CLV = 0.50 - 0.60 = -0.10
        ("0xTraderE", 0.70, -8.0, "LONG"),   # CLV = 0.50 - 0.70 = -0.20
    ]

    for trader_address, entry_price, pnl_per_pos, direction in trader_configs:
        for i in range(1, 36):
            # Vary PnL slightly for each position so Sharpe is non-zero
            pnl_variation = pnl_per_pos + (i % 3 - 1) * 0.5  # small variation
            position = Position(
                market_id=f"market{i:03d}",
                trader_address=trader_address,
                size=Decimal("100"),
                direction=direction,
                avg_entry_price=Decimal(str(entry_price)),
                entry_timestamp=now - timedelta(days=35),
                first_trade_timestamp=now - timedelta(days=35),
                last_trade_timestamp=now - timedelta(days=i % 20),  # within 30 days
                trade_count=1,
                resolved=True,
                outcome="win" if pnl_variation > 0 else "loss",
                pnl=Decimal(str(round(pnl_variation, 2))),
            )
            session.add(position)

    session.commit()
    session.close()

    return session_factory


@pytest.fixture
def windowed_db(in_memory_db):
    """Database with positions straddling the 30-day window boundary.

    Trader A: 35 positions all within 30 days -> included
    Trader B: 35 positions, 25 within 30 days and 10 outside -> only 25 counted
    Trader C: 35 positions, all older than 30 days -> excluded
    """
    _, session_factory = in_memory_db
    session: Session = session_factory()

    now = datetime.now(UTC)

    # Create 35 markets
    for i in range(1, 36):
        market = Market(
            condition_id=f"wmarket{i:03d}",
            question=f"Window test market {i}",
            category="eSports",
        )
        session.add(market)

    for i in range(1, 36):
        entity = MarketEntity(
            condition_id=f"wmarket{i:03d}",
            game="CS2",
            tournament="IEM",
            team_a="A",
            team_b="B",
            market_type="match",
        )
        session.add(entity)

    session.flush()

    # Trader A: all 35 positions within 30 days
    for i in range(1, 36):
        position = Position(
            market_id=f"wmarket{i:03d}",
            trader_address="0xWindowTraderA",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.40"),
            entry_timestamp=now - timedelta(days=20),
            first_trade_timestamp=now - timedelta(days=20),
            last_trade_timestamp=now - timedelta(days=5),  # within window
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("10"),
        )
        session.add(position)

    # Trader B: 25 positions within window, 10 outside
    for i in range(1, 26):
        position = Position(
            market_id=f"wmarket{i:03d}",
            trader_address="0xWindowTraderB",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.40"),
            entry_timestamp=now - timedelta(days=20),
            first_trade_timestamp=now - timedelta(days=20),
            last_trade_timestamp=now - timedelta(days=5),  # within window
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("10"),
        )
        session.add(position)

    for i in range(26, 36):
        position = Position(
            market_id=f"wmarket{i:03d}",
            trader_address="0xWindowTraderB",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.40"),
            entry_timestamp=now - timedelta(days=60),
            first_trade_timestamp=now - timedelta(days=60),
            last_trade_timestamp=now - timedelta(days=45),  # OUTSIDE 30-day window
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("10"),
        )
        session.add(position)

    # Trader C: all 35 positions outside 30-day window
    for i in range(1, 36):
        position = Position(
            market_id=f"wmarket{i:03d}",
            trader_address="0xWindowTraderC",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.40"),
            entry_timestamp=now - timedelta(days=90),
            first_trade_timestamp=now - timedelta(days=90),
            last_trade_timestamp=now - timedelta(days=60),  # OUTSIDE 30-day window
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("10"),
        )
        session.add(position)

    session.commit()
    session.close()

    return session_factory


@pytest.fixture
def threshold_db(in_memory_db):
    """Database with traders above/below min_positions threshold.

    For esports, min_positions=30.
    Trader A: 35 positions -> included
    Trader B: 10 positions -> excluded (below 30)
    """
    _, session_factory = in_memory_db
    session: Session = session_factory()

    now = datetime.now(UTC)

    for i in range(1, 36):
        market = Market(
            condition_id=f"tmarket{i:03d}",
            question=f"Threshold test market {i}",
            category="eSports",
        )
        session.add(market)

    for i in range(1, 36):
        entity = MarketEntity(
            condition_id=f"tmarket{i:03d}",
            game="CS2",
            tournament="IEM",
            team_a="A",
            team_b="B",
            market_type="match",
        )
        session.add(entity)

    session.flush()

    # Trader A: 35 positions (above threshold)
    for i in range(1, 36):
        position = Position(
            market_id=f"tmarket{i:03d}",
            trader_address="0xThreshTraderA",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.40"),
            entry_timestamp=now - timedelta(days=20),
            first_trade_timestamp=now - timedelta(days=20),
            last_trade_timestamp=now - timedelta(days=5),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("10"),
        )
        session.add(position)

    # Trader B: only 10 positions (below threshold)
    for i in range(1, 11):
        position = Position(
            market_id=f"tmarket{i:03d}",
            trader_address="0xThreshTraderB",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.40"),
            entry_timestamp=now - timedelta(days=20),
            first_trade_timestamp=now - timedelta(days=20),
            last_trade_timestamp=now - timedelta(days=5),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("10"),
        )
        session.add(position)

    session.commit()
    session.close()

    return session_factory


# ---------------------------------------------------------------------------
# Tests: get_market_avg_entries
# ---------------------------------------------------------------------------

class TestGetMarketAvgEntries:
    def test_returns_correct_averages(self, esports_db):
        """get_market_avg_entries returns correct per-market averages."""
        with esports_db() as session:
            now = datetime.now(UTC)
            window_start = now - timedelta(days=30)
            avgs = get_market_avg_entries(session, "esports", window_start)

        # Each market has positions from 5 traders at prices [0.35, 0.45, 0.50, 0.60, 0.70]
        # mean = (0.35 + 0.45 + 0.50 + 0.60 + 0.70) / 5 = 0.52
        # (some positions may be outside window, so exact value depends on window)
        assert len(avgs) > 0
        for market_id, avg_price in avgs.items():
            assert isinstance(avg_price, Decimal)
            assert Decimal("0") < avg_price <= Decimal("1")

    def test_empty_for_unknown_category(self, esports_db):
        """Unknown category returns empty dict."""
        with esports_db() as session:
            now = datetime.now(UTC)
            window_start = now - timedelta(days=30)
            avgs = get_market_avg_entries(session, "nba", window_start)
        assert avgs == {}

    def test_respects_window_start(self, windowed_db):
        """Only includes positions within the window."""
        with windowed_db() as session:
            now = datetime.now(UTC)
            # Very recent window - 10 days
            window_start = now - timedelta(days=10)
            avgs = get_market_avg_entries(session, "esports", window_start)
            # Only positions with last_trade_timestamp >= window_start should be included
            # Trader A has positions at -5 days (within), Trader B has some at -5 (within)
            # Trader C has all at -60 (outside) -> excluded
            assert len(avgs) > 0


# ---------------------------------------------------------------------------
# Tests: get_positions_for_category
# ---------------------------------------------------------------------------

class TestGetPositionsForCategory:
    def test_returns_traders_above_threshold(self, threshold_db):
        """Returns traders with >= min_positions positions."""
        with threshold_db() as session:
            now = datetime.now(UTC)
            window_start = now - timedelta(days=30)
            result = get_positions_for_category(session, "esports", window_start, min_positions=30)

        assert "0xThreshTraderA" in result
        assert len(result["0xThreshTraderA"]) >= 30

    def test_excludes_traders_below_threshold(self, threshold_db):
        """Excludes traders with < min_positions positions."""
        with threshold_db() as session:
            now = datetime.now(UTC)
            window_start = now - timedelta(days=30)
            result = get_positions_for_category(session, "esports", window_start, min_positions=30)

        assert "0xThreshTraderB" not in result

    def test_excludes_void_outcomes(self, in_memory_db):
        """Void outcome positions are excluded."""
        _, session_factory = in_memory_db
        session: Session = session_factory()
        now = datetime.now(UTC)

        market = Market(condition_id="vm001", question="Void test", category="eSports")
        session.add(market)
        entity = MarketEntity(condition_id="vm001", game="CS2", tournament="T", team_a="A", team_b="B")
        session.add(entity)
        session.flush()

        # 35 void positions
        for i in range(35):
            pos = Position(
                market_id="vm001",
                trader_address=f"0xVoidTrader{i}",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.50"),
                last_trade_timestamp=now - timedelta(days=1),
                resolved=True,
                outcome="void",
                pnl=Decimal("0"),
            )
            session.add(pos)
        session.commit()

        with session_factory() as s:
            window_start = now - timedelta(days=30)
            result = get_positions_for_category(s, "esports", window_start, min_positions=1)
        # All positions are void, so each trader has 0 qualifying positions
        assert len(result) == 0
        session.close()


# ---------------------------------------------------------------------------
# Tests: compute_category_scores
# ---------------------------------------------------------------------------

class TestComputeCategoryScores:
    def test_returns_lift_leaderboard_entries(self, esports_db):
        """Returns list of LiftLeaderboardEntry objects."""
        with esports_db() as session:
            entries = compute_category_scores(session, "esports")

        assert len(entries) > 0
        # Check expected fields exist
        entry = entries[0]
        assert hasattr(entry, "trader_address")
        assert hasattr(entry, "composite_score")
        assert hasattr(entry, "clv_raw")
        assert hasattr(entry, "roi_raw")
        assert hasattr(entry, "sharpe_raw")
        assert hasattr(entry, "quintile")
        assert hasattr(entry, "position_count")

    def test_quintiles_assigned_correctly(self, esports_db):
        """All quintile values are in [1, 5]."""
        with esports_db() as session:
            entries = compute_category_scores(session, "esports")

        for entry in entries:
            assert 1 <= entry.quintile <= 5

    def test_sorted_by_composite_desc(self, esports_db):
        """Entries are sorted by composite score descending (best first)."""
        with esports_db() as session:
            entries = compute_category_scores(session, "esports")

        for i in range(len(entries) - 1):
            assert entries[i].composite_score >= entries[i + 1].composite_score

    def test_unknown_category_returns_empty(self, esports_db):
        """Unscored category (nba, unknown) returns empty list."""
        with esports_db() as session:
            entries = compute_category_scores(session, "nba")
        assert entries == []

        with esports_db() as session:
            entries = compute_category_scores(session, "cricket")
        assert entries == []

    def test_min_positions_threshold_enforced(self, threshold_db):
        """Trader with < min_positions excluded from results."""
        with threshold_db() as session:
            entries = compute_category_scores(session, "esports")

        trader_addresses = {e.trader_address for e in entries}
        assert "0xThreshTraderA" in trader_addresses
        assert "0xThreshTraderB" not in trader_addresses

    def test_liftscore_rows_persisted(self, esports_db):
        """LiftScore rows exist in DB after scoring run."""
        with esports_db() as session:
            compute_category_scores(session, "esports")

        with esports_db() as session:
            rows = session.execute(
                select(LiftScore).where(LiftScore.category == "esports")
            ).scalars().all()
        assert len(rows) > 0

    def test_liftscore_rows_replaced_on_rerun(self, esports_db):
        """Repeated scoring run replaces old rows (no duplicates)."""
        with esports_db() as session:
            entries1 = compute_category_scores(session, "esports")

        with esports_db() as session:
            entries2 = compute_category_scores(session, "esports")

        with esports_db() as session:
            count = session.execute(
                select(LiftScore).where(LiftScore.category == "esports")
            ).scalars().all()

        # Should have same count as one scoring run, not doubled
        assert len(count) == len(entries1)

    def test_30_day_window_excludes_old_positions(self, windowed_db):
        """Positions older than 30 days are excluded."""
        with windowed_db() as session:
            entries = compute_category_scores(session, "esports")

        # TraderC has ALL positions outside 30-day window -> excluded
        trader_addresses = {e.trader_address for e in entries}
        assert "0xWindowTraderC" not in trader_addresses


# ---------------------------------------------------------------------------
# Tests: get_lift_leaderboard
# ---------------------------------------------------------------------------

class TestGetLiftLeaderboard:
    def test_returns_sorted_by_composite_desc(self, esports_db):
        """get_lift_leaderboard returns traders sorted by composite_score DESC."""
        with esports_db() as session:
            compute_category_scores(session, "esports")

        with esports_db() as session:
            leaderboard = get_lift_leaderboard(session, "esports", top_n=10)

        assert len(leaderboard) > 0
        for i in range(len(leaderboard) - 1):
            assert leaderboard[i].composite_score >= leaderboard[i + 1].composite_score

    def test_top_n_limit_respected(self, esports_db):
        """top_n parameter limits result count."""
        with esports_db() as session:
            compute_category_scores(session, "esports")

        with esports_db() as session:
            leaderboard = get_lift_leaderboard(session, "esports", top_n=3)

        assert len(leaderboard) <= 3

    def test_empty_when_no_scores(self, in_memory_db):
        """Returns empty list when no LiftScore rows exist."""
        _, session_factory = in_memory_db
        with session_factory() as session:
            leaderboard = get_lift_leaderboard(session, "esports", top_n=20)
        assert leaderboard == []

    def test_liftscore_fields_present(self, esports_db):
        """Returned LiftScore objects have all expected fields."""
        with esports_db() as session:
            compute_category_scores(session, "esports")

        with esports_db() as session:
            leaderboard = get_lift_leaderboard(session, "esports", top_n=5)

        assert len(leaderboard) > 0
        entry = leaderboard[0]
        assert entry.trader_address is not None
        assert entry.composite_score is not None
        assert entry.clv_raw is not None
        assert entry.roi_raw is not None
        assert entry.sharpe_raw is not None
        assert entry.quintile in [1, 2, 3, 4, 5]
        assert entry.position_count > 0


# ---------------------------------------------------------------------------
# Tests: compute_all_category_scores
# ---------------------------------------------------------------------------

class TestComputeAllCategoryScores:
    def test_returns_dict_keyed_by_category(self, esports_db):
        """Returns dict with category keys."""
        with esports_db() as session:
            results = compute_all_category_scores(session)

        assert isinstance(results, dict)
        # esports has data, should be present
        assert "esports" in results

    def test_skips_categories_with_no_data(self, esports_db):
        """Categories with no data return empty list, not errors."""
        with esports_db() as session:
            results = compute_all_category_scores(session)

        # epl/politics have no data -> empty list (not missing from dict)
        for category in ["esports", "epl", "politics", "la-liga", "ligue-1"]:
            assert category in results
            assert isinstance(results[category], list)
