"""Integration tests for scoring pipeline.

Tests the full pipeline from positions to leaderboard generation.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import (
    Base,
    ExpertiseScore,
    MarketClassification,
    PerformanceSnapshot,
    Position,
    TaxonomyNode,
)
from src.pipeline.queries import get_game_leaderboard, get_trader_score_history
from src.pipeline.scoring_pipeline import compute_game_scores, compute_all_game_scores


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


@pytest.fixture
def scoring_db(in_memory_db):
    """Create database with scoring test data.

    Creates:
    - TaxonomyNode entries for "esports" (root) and "esports.cs2" (game)
    - MarketClassification entries linking markets to taxonomy nodes
    - Position entries for multiple traders with varying win rates and activity
    - PerformanceSnapshot entries with consistency data for SOME traders
    - Some traders WITHOUT PerformanceSnapshot (to test default fallback)
    - Some positions with avg_entry_price=None (to test volume proxy fallback)
    """
    _, session_factory = in_memory_db
    session: Session = session_factory()

    now = datetime.utcnow()

    # Create taxonomy nodes
    esports_root = TaxonomyNode(
        name="eSports",
        slug="esports",
        parent_id=None,
        depth=0,
        node_type="root",
        patterns_json='["esports", "gaming"]',
    )
    session.add(esports_root)
    session.flush()

    cs2_game = TaxonomyNode(
        name="Counter-Strike 2",
        slug="esports.cs2",
        parent_id=esports_root.id,
        depth=1,
        node_type="game",
        patterns_json='["cs2", "counter-strike 2", "counter strike 2"]',
    )
    session.add(cs2_game)
    session.flush()

    dota2_game = TaxonomyNode(
        name="Dota 2",
        slug="esports.dota2",
        parent_id=esports_root.id,
        depth=1,
        node_type="game",
        patterns_json='["dota 2", "dota2"]',
    )
    session.add(dota2_game)
    session.flush()

    # Create market classifications
    for i in range(1, 11):
        classification = MarketClassification(
            market_id=f"market{i}",
            taxonomy_node_id=cs2_game.id,
            node_path="eSports.CS2",
            market_type="match",
            matched_pattern="cs2",
            flagged_for_review=False,
        )
        session.add(classification)

    # Create market classifications for Dota 2
    for i in range(11, 16):
        classification = MarketClassification(
            market_id=f"market{i}",
            taxonomy_node_id=dota2_game.id,
            node_path="eSports.Dota2",
            market_type="match",
            matched_pattern="dota2",
            flagged_for_review=False,
        )
        session.add(classification)

    session.commit()

    # Trader 1: High performer (8 wins, 2 losses) with consistency data
    for i in range(1, 9):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader1",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.6"),
            entry_timestamp=now - timedelta(days=30),
            first_trade_timestamp=now - timedelta(days=30),
            last_trade_timestamp=now - timedelta(days=i),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("40"),
        )
        session.add(position)

    for i in range(9, 11):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader1",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.6"),
            entry_timestamp=now - timedelta(days=30),
            first_trade_timestamp=now - timedelta(days=30),
            last_trade_timestamp=now - timedelta(days=i - 8),
            trade_count=1,
            resolved=True,
            outcome="loss",
            pnl=Decimal("-60"),
        )
        session.add(position)

    # Add performance snapshot for Trader1 (with consistency data)
    snapshot1 = PerformanceSnapshot(
        trader_address="0xTrader1",
        timeframe="all",
        realized_pnl=Decimal("200"),
        unrealized_pnl=Decimal("0"),
        total_pnl=Decimal("200"),
        wins=8,
        losses=2,
        total_resolved=10,
        win_rate=Decimal("80"),
        total_volume=Decimal("1000"),
        resolved_markets=10,
        unresolved_markets=0,
        is_low_confidence=False,
        consistency_score=Decimal("85"),
        consistency_signal="stable",
        profile_type="active",
    )
    session.add(snapshot1)

    # Trader 2: Medium performer (3 wins, 2 losses) WITHOUT PerformanceSnapshot
    for i in range(1, 4):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader2",
            size=Decimal("50"),
            direction="LONG",
            avg_entry_price=Decimal("0.5"),
            entry_timestamp=now - timedelta(days=60),
            first_trade_timestamp=now - timedelta(days=60),
            last_trade_timestamp=now - timedelta(days=20 + i),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("25"),
        )
        session.add(position)

    for i in range(4, 6):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader2",
            size=Decimal("50"),
            direction="LONG",
            avg_entry_price=Decimal("0.5"),
            entry_timestamp=now - timedelta(days=60),
            first_trade_timestamp=now - timedelta(days=60),
            last_trade_timestamp=now - timedelta(days=20 + i),
            trade_count=1,
            resolved=True,
            outcome="loss",
            pnl=Decimal("-50"),
        )
        session.add(position)

    # Trader 3: Low sample size (3 markets only) - should be excluded
    for i in range(1, 4):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader3",
            size=Decimal("30"),
            direction="LONG",
            avg_entry_price=Decimal("0.4"),
            entry_timestamp=now - timedelta(days=10),
            first_trade_timestamp=now - timedelta(days=10),
            last_trade_timestamp=now - timedelta(days=i),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("20"),
        )
        session.add(position)

    # Trader 4: Positions with avg_entry_price=None (volume proxy fallback test)
    for i in range(1, 6):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader4",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=None,  # Test fallback to abs(size)
            entry_timestamp=now - timedelta(days=15),
            first_trade_timestamp=now - timedelta(days=15),
            last_trade_timestamp=now - timedelta(days=i),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("50"),
        )
        session.add(position)

    # Trader 5: Dota 2 positions (to test get_all_game_slugs_with_positions)
    for i in range(11, 16):
        position = Position(
            market_id=f"market{i}",
            trader_address="0xTrader5",
            size=Decimal("80"),
            direction="LONG",
            avg_entry_price=Decimal("0.7"),
            entry_timestamp=now - timedelta(days=20),
            first_trade_timestamp=now - timedelta(days=20),
            last_trade_timestamp=now - timedelta(days=i - 10),
            trade_count=1,
            resolved=True,
            outcome="win",
            pnl=Decimal("30"),
        )
        session.add(position)

    # Add performance snapshot for Trader5
    snapshot5 = PerformanceSnapshot(
        trader_address="0xTrader5",
        timeframe="all",
        realized_pnl=Decimal("150"),
        unrealized_pnl=Decimal("0"),
        total_pnl=Decimal("150"),
        wins=5,
        losses=0,
        total_resolved=5,
        win_rate=Decimal("100"),
        total_volume=Decimal("400"),
        resolved_markets=5,
        unresolved_markets=0,
        is_low_confidence=False,
        consistency_score=Decimal("90"),
        consistency_signal="stable",
        profile_type="selective",
    )
    session.add(snapshot5)

    session.commit()

    yield session, now

    session.close()


def test_compute_game_scores_returns_sorted_leaderboard(scoring_db):
    """Test that compute_game_scores returns leaderboard sorted by percentile_rank."""
    session, now = scoring_db

    leaderboard = compute_game_scores(session, "esports.cs2", now=now)

    # Should include Trader1, Trader2, Trader4 (all have >= 5 resolved markets)
    # Should exclude Trader3 (only 3 markets)
    assert len(leaderboard) == 3

    # Should be sorted by percentile_rank descending
    assert leaderboard[0].percentile_rank >= leaderboard[1].percentile_rank
    assert leaderboard[1].percentile_rank >= leaderboard[2].percentile_rank

    # Ranks should be sequential 1, 2, 3
    assert leaderboard[0].rank == 1
    assert leaderboard[1].rank == 2
    assert leaderboard[2].rank == 3


def test_compute_game_scores_excludes_low_sample_size(scoring_db):
    """Test that traders with < 5 resolved markets are excluded."""
    session, now = scoring_db

    leaderboard = compute_game_scores(session, "esports.cs2", now=now)

    trader_addresses = [entry.trader_address for entry in leaderboard]

    # Trader3 has only 3 markets, should be excluded
    assert "0xTrader3" not in trader_addresses

    # Others should be included
    assert "0xTrader1" in trader_addresses
    assert "0xTrader2" in trader_addresses
    assert "0xTrader4" in trader_addresses


def test_leaderboard_entry_includes_all_required_fields(scoring_db):
    """Test that LeaderboardEntry includes all required fields."""
    session, now = scoring_db

    leaderboard = compute_game_scores(session, "esports.cs2", now=now)

    entry = leaderboard[0]

    # Check all required fields are present
    assert isinstance(entry.rank, int)
    assert isinstance(entry.trader_address, str)
    assert isinstance(entry.game_slug, str)
    assert isinstance(entry.raw_score, Decimal)
    assert isinstance(entry.percentile_rank, Decimal)
    assert entry.win_rate is None or isinstance(entry.win_rate, Decimal)
    assert isinstance(entry.realized_pnl, Decimal)
    assert isinstance(entry.trade_count, int)
    assert isinstance(entry.unique_markets, int)
    assert entry.last_active is None or isinstance(entry.last_active, datetime)
    assert isinstance(entry.specialization_label, str)


def test_expertise_score_rows_persisted_to_database(scoring_db):
    """Test that ExpertiseScore rows are persisted after scoring."""
    session, now = scoring_db

    # Run scoring
    compute_game_scores(session, "esports.cs2", now=now)

    # Query ExpertiseScore rows
    from sqlalchemy import select

    query = select(ExpertiseScore).where(ExpertiseScore.game_slug == "esports.cs2")
    result = session.execute(query)
    scores = list(result.scalars().all())

    # Should have 3 scores (Trader1, Trader2, Trader4)
    assert len(scores) == 3

    # Check fields are populated
    for score in scores:
        assert score.trader_address in ["0xTrader1", "0xTrader2", "0xTrader4"]
        assert score.game_slug == "esports.cs2"
        assert score.raw_score >= Decimal("0")
        assert score.percentile_rank is not None
        assert score.win_rate_component >= Decimal("0")
        assert score.concentration_component >= Decimal("0")
        assert score.recency_component >= Decimal("0")
        assert score.sample_size_component >= Decimal("0")
        assert score.consistency_multiplier >= Decimal("1.0")
        assert score.specialization_label != ""
        assert score.resolved_market_count >= 5
        assert score.computed_at is not None


def test_second_scoring_run_creates_new_rows(scoring_db):
    """Test that second scoring run creates new ExpertiseScore rows (append-only)."""
    session, now = scoring_db

    # First run
    compute_game_scores(session, "esports.cs2", now=now)

    # Query count
    from sqlalchemy import select, func

    query = select(func.count(ExpertiseScore.id)).where(ExpertiseScore.game_slug == "esports.cs2")
    first_count = session.execute(query).scalar()

    # Second run (1 day later)
    later = now + timedelta(days=1)
    compute_game_scores(session, "esports.cs2", now=later)

    # Query count again
    second_count = session.execute(query).scalar()

    # Should have doubled (3 traders * 2 runs = 6 rows)
    assert second_count == first_count * 2


def test_empty_game_returns_empty_leaderboard(scoring_db):
    """Test that empty game returns empty leaderboard."""
    session, now = scoring_db

    # Query for a game with no positions
    leaderboard = compute_game_scores(session, "esports.valorant", now=now)

    assert len(leaderboard) == 0


def test_volume_proxy_handles_none_avg_entry_price(scoring_db):
    """Test that volume proxy handles positions with avg_entry_price=None."""
    session, now = scoring_db

    # Trader4 has positions with avg_entry_price=None
    leaderboard = compute_game_scores(session, "esports.cs2", now=now)

    trader4_entry = next(
        (entry for entry in leaderboard if entry.trader_address == "0xTrader4"), None
    )

    # Should be included (has 5 markets)
    assert trader4_entry is not None
    # Should have a valid score
    assert trader4_entry.raw_score > Decimal("0")


def test_get_game_leaderboard_retrieves_latest_scores(scoring_db):
    """Test that get_game_leaderboard retrieves latest scores correctly."""
    session, now = scoring_db

    # Run scoring twice
    compute_game_scores(session, "esports.cs2", now=now)
    later = now + timedelta(days=1)
    compute_game_scores(session, "esports.cs2", now=later)

    # Query latest scores
    latest = get_game_leaderboard(session, "esports.cs2", top_n=10)

    # Should get 3 scores (one per trader)
    assert len(latest) == 3

    # All should have the later computed_at timestamp
    for score in latest:
        assert score.computed_at == later


def test_get_game_leaderboard_with_min_score_filters(scoring_db):
    """Test that get_game_leaderboard filters by min_score."""
    session, now = scoring_db

    # Run scoring
    compute_game_scores(session, "esports.cs2", now=now)

    # Get all scores to find a reasonable threshold
    all_scores = get_game_leaderboard(session, "esports.cs2", top_n=10)
    assert len(all_scores) == 3

    # Find median score
    scores_list = sorted([s.raw_score for s in all_scores])
    median_score = scores_list[1]

    # Filter by score > median
    filtered = get_game_leaderboard(session, "esports.cs2", top_n=10, min_score=median_score)

    # Should get <= 2 results (median and above)
    assert len(filtered) <= 2
    assert all(s.raw_score >= median_score for s in filtered)


def test_get_trader_score_history_returns_chronological(scoring_db):
    """Test that get_trader_score_history returns chronological score history."""
    session, now = scoring_db

    # Run scoring three times
    timestamps = [now, now + timedelta(days=1), now + timedelta(days=2)]
    for ts in timestamps:
        compute_game_scores(session, "esports.cs2", now=ts)

    # Get Trader1's history
    history = get_trader_score_history(session, "0xTrader1", game_slug="esports.cs2")

    # Should have 3 snapshots
    assert len(history) == 3

    # Should be ordered by computed_at DESC
    assert history[0].computed_at >= history[1].computed_at
    assert history[1].computed_at >= history[2].computed_at


def test_trader_with_performance_snapshot_uses_stored_consistency(scoring_db):
    """Test that trader WITH PerformanceSnapshot uses stored consistency data."""
    session, now = scoring_db

    # Trader1 has PerformanceSnapshot with consistency_score=85, signal="stable"
    # This should trigger 1.05x multiplier (score >= 80 AND signal == "stable")
    leaderboard = compute_game_scores(session, "esports.cs2", now=now)

    trader1_entry = next(
        (entry for entry in leaderboard if entry.trader_address == "0xTrader1"), None
    )

    assert trader1_entry is not None

    # Query the ExpertiseScore to check consistency_multiplier
    from sqlalchemy import select

    query = (
        select(ExpertiseScore)
        .where(ExpertiseScore.trader_address == "0xTrader1")
        .where(ExpertiseScore.game_slug == "esports.cs2")
        .order_by(ExpertiseScore.computed_at.desc())
    )
    result = session.execute(query)
    score = result.scalar_one()

    # Should have 1.05x multiplier (consistency bonus)
    assert score.consistency_multiplier == Decimal("1.05")


def test_trader_without_performance_snapshot_gets_defaults(scoring_db):
    """Test that trader WITHOUT PerformanceSnapshot gets default consistency values."""
    session, now = scoring_db

    # Trader2 has NO PerformanceSnapshot
    # Should get defaults: consistency_score=50, signal="insufficient_data"
    # This gives 1.0x multiplier (no bonus)
    leaderboard = compute_game_scores(session, "esports.cs2", now=now)

    trader2_entry = next(
        (entry for entry in leaderboard if entry.trader_address == "0xTrader2"), None
    )

    assert trader2_entry is not None

    # Query the ExpertiseScore to check consistency_multiplier
    from sqlalchemy import select

    query = (
        select(ExpertiseScore)
        .where(ExpertiseScore.trader_address == "0xTrader2")
        .where(ExpertiseScore.game_slug == "esports.cs2")
        .order_by(ExpertiseScore.computed_at.desc())
    )
    result = session.execute(query)
    score = result.scalar_one()

    # Should have 1.0x multiplier (no bonus)
    assert score.consistency_multiplier == Decimal("1.0")


def test_compute_all_game_scores_processes_multiple_games(scoring_db):
    """Test that compute_all_game_scores processes all games."""
    session, now = scoring_db

    # Run scoring for all games
    results = compute_all_game_scores(session, now=now)

    # Should have 2 games (esports.cs2 and esports.dota2)
    assert len(results) == 2
    assert "esports.cs2" in results
    assert "esports.dota2" in results

    # CS2 should have 3 traders
    assert len(results["esports.cs2"]) == 3

    # Dota 2 should have 1 trader
    assert len(results["esports.dota2"]) == 1
