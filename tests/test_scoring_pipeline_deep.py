"""Tests for deep scoring pipeline.

Tests for:
- compute_taxonomy_scores at different depths
- compute_all_taxonomy_scores
- identify_hidden_specialists
"""

import pytest
from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import (
    Base,
    ExpertiseScore,
    Market,
    MarketEntity,
    PerformanceSnapshot,
    Position,
)
from src.pipeline.scoring_pipeline import (
    compute_all_taxonomy_scores,
    compute_taxonomy_scores,
    identify_hidden_specialists,
)


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


@pytest.fixture
def test_session(in_memory_db):
    """Create a new database session for each test."""
    session: Session = in_memory_db()
    yield session
    session.close()


@pytest.fixture
def taxonomy_hierarchy(test_session):
    """Create MarketEntity entries for test markets at different depths."""
    # Create market entities for different entity levels
    entity_game = MarketEntity(
        condition_id="market-game",
        game="CS2",
        tournament=None,
        team_a=None,
        team_b=None,
        market_type="match",
    )
    entity_tournament = MarketEntity(
        condition_id="market-tournament",
        game="CS2",
        tournament="IEM Katowice",
        team_a=None,
        team_b=None,
        market_type="match",
    )
    entity_team = MarketEntity(
        condition_id="market-team",
        game="CS2",
        tournament="IEM Katowice",
        team_a="NaVi",
        team_b="FaZe",
        market_type="match",
    )
    test_session.add_all([entity_game, entity_tournament, entity_team])
    test_session.commit()

    return {"game": entity_game, "tournament": entity_tournament, "team": entity_team}


@pytest.fixture
def positions_at_depth(test_session, taxonomy_hierarchy):
    """Create positions at different taxonomy depths."""
    entities = taxonomy_hierarchy

    market_game = Market(
        condition_id="market-game",
        question="CS2 winner?",
        category="eSports",
        active=True,
    )
    market_tournament = Market(
        condition_id="market-tournament",
        question="IEM Katowice winner?",
        category="eSports",
        active=True,
    )
    market_team = Market(
        condition_id="market-team",
        question="NaVi vs FaZe?",
        category="eSports",
        active=True,
    )
    test_session.add_all([market_game, market_tournament, market_team])
    test_session.flush()

    trader_a_positions = [
        Position(
            market_id="market-game",
            trader_address="0xTraderA",
            size=Decimal("100"),
            direction="LONG",
            avg_entry_price=Decimal("0.6"),
            trade_count=10,
            resolved=True,
            outcome="win",
            pnl=Decimal("40"),
            last_trade_timestamp=datetime.now(UTC),
        ),
        Position(
            market_id="market-tournament",
            trader_address="0xTraderA",
            size=Decimal("50"),
            direction="LONG",
            avg_entry_price=Decimal("0.7"),
            trade_count=8,
            resolved=True,
            outcome="win",
            pnl=Decimal("30"),
            last_trade_timestamp=datetime.now(UTC),
        ),
        Position(
            market_id="market-team",
            trader_address="0xTraderA",
            size=Decimal("25"),
            direction="LONG",
            avg_entry_price=Decimal("0.8"),
            trade_count=6,
            resolved=True,
            outcome="win",
            pnl=Decimal("20"),
            last_trade_timestamp=datetime.now(UTC),
        ),
    ]

    trader_b_positions = [
        Position(
            market_id="market-game",
            trader_address="0xTraderB",
            size=Decimal("80"),
            direction="LONG",
            avg_entry_price=Decimal("0.5"),
            trade_count=12,
            resolved=True,
            outcome="win",
            pnl=Decimal("32"),
            last_trade_timestamp=datetime.now(UTC),
        ),
        Position(
            market_id="market-tournament",
            trader_address="0xTraderB",
            size=Decimal("20"),
            direction="LONG",
            avg_entry_price=Decimal("0.4"),
            trade_count=3,
            resolved=True,
            outcome="loss",
            pnl=Decimal("-10"),
            last_trade_timestamp=datetime.now(UTC),
        ),
    ]

    test_session.add_all(trader_a_positions + trader_b_positions)

    perf_a = PerformanceSnapshot(
        trader_address="0xTraderA",
        timeframe="all",
        realized_pnl=Decimal("90"),
        total_volume=Decimal("5000"),
        wins=16,
        losses=4,
        total_resolved=20,
        resolved_markets=20,
        win_rate=Decimal("0.8"),
        consistency_score=Decimal("75"),
        consistency_signal="consistent",
        computed_at=datetime.now(UTC),
    )

    perf_b = PerformanceSnapshot(
        trader_address="0xTraderB",
        timeframe="all",
        realized_pnl=Decimal("22"),
        total_volume=Decimal("3000"),
        wins=7,
        losses=5,
        total_resolved=12,
        resolved_markets=12,
        win_rate=Decimal("0.6"),
        consistency_score=Decimal("50"),
        consistency_signal="insufficient_data",
        computed_at=datetime.now(UTC),
    )

    test_session.add_all([perf_a, perf_b])
    test_session.commit()

    return {"trader_a": trader_a_positions, "trader_b": trader_b_positions}


class TestComputeTaxonomyScores:
    """Tests for compute_taxonomy_scores function."""

    def test_function_signature(self, test_session):
        """Verify function can be called with expected parameters."""
        leaderboard = compute_taxonomy_scores(
            test_session, "IEM Katowice", taxonomy_depth=2
        )
        assert isinstance(leaderboard, list)

    def test_function_signature_with_team_depth(self, test_session):
        """Verify function can be called at team depth."""
        leaderboard = compute_taxonomy_scores(test_session, "NaVi", taxonomy_depth=3)
        assert isinstance(leaderboard, list)


class TestComputeAllTaxonomyScores:
    """Tests for compute_all_taxonomy_scores function."""

    def test_discovers_all_slugs_at_depth(
        self, test_session, taxonomy_hierarchy, positions_at_depth
    ):
        """Verify all slugs at a depth are discovered and scored."""
        results = compute_all_taxonomy_scores(test_session, depth=2)

        assert "IEM Katowice" in results


class TestIdentifyHiddenSpecialists:
    """Tests for identify_hidden_specialists function."""

    def test_finds_hidden_specialist(self, test_session):
        """Verify hidden specialist found: low game score, high tournament score."""
        # Create MarketEntity linking tournament to game
        entity = MarketEntity(
            condition_id="market1",
            game="CS2",
            tournament="IEM Katowice",
            team_a=None,
            team_b=None,
            market_type="match",
        )
        test_session.add(entity)
        test_session.commit()

        game_score = ExpertiseScore(
            trader_address="0xHidden",
            game_slug="CS2",
            taxonomy_depth=1,
            raw_score=Decimal("50"),
            win_rate_component=Decimal("0.5"),
            concentration_component=Decimal("0.3"),
            recency_component=Decimal("0.2"),
            sample_size_component=Decimal("0.2"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="generalist",
            resolved_market_count=10,
            computed_at=datetime.now(UTC),
        )

        deep_score = ExpertiseScore(
            trader_address="0xHidden",
            game_slug="IEM Katowice",
            taxonomy_depth=2,
            raw_score=Decimal("80"),
            win_rate_component=Decimal("0.8"),
            concentration_component=Decimal("0.7"),
            recency_component=Decimal("0.5"),
            sample_size_component=Decimal("0.4"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=8,
            computed_at=datetime.now(UTC),
        )

        test_session.add_all([game_score, deep_score])
        test_session.commit()

        specialists = identify_hidden_specialists(
            test_session,
            game_slug="CS2",
            game_score_threshold=Decimal("60"),
            deep_score_threshold=Decimal("75"),
        )

        assert len(specialists) >= 1
        assert specialists[0]["trader_address"] == "0xHidden"
        assert specialists[0]["game_score"] == Decimal("50")
        assert specialists[0]["deep_score"] == Decimal("80")

    def test_excludes_non_specialist(self, test_session):
        """Verify non-specialist excluded: trader with game_score above threshold."""
        score = ExpertiseScore(
            trader_address="0xNotHidden",
            game_slug="CS2",
            taxonomy_depth=1,
            raw_score=Decimal("70"),
            win_rate_component=Decimal("0.7"),
            concentration_component=Decimal("0.5"),
            recency_component=Decimal("0.4"),
            sample_size_component=Decimal("0.3"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=15,
            computed_at=datetime.now(UTC),
        )
        test_session.add(score)
        test_session.commit()

        specialists = identify_hidden_specialists(
            test_session,
            game_slug="CS2",
            game_score_threshold=Decimal("60"),
            deep_score_threshold=Decimal("75"),
        )

        assert len(specialists) == 0

    def test_excludes_deep_generalist(self, test_session):
        """Verify deep generalist excluded: both game and deep scores below threshold."""
        game_score = ExpertiseScore(
            trader_address="0xGeneralist",
            game_slug="CS2",
            taxonomy_depth=1,
            raw_score=Decimal("40"),
            win_rate_component=Decimal("0.4"),
            concentration_component=Decimal("0.2"),
            recency_component=Decimal("0.1"),
            sample_size_component=Decimal("0.1"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="generalist",
            resolved_market_count=6,
            computed_at=datetime.now(UTC),
        )

        deep_score = ExpertiseScore(
            trader_address="0xGeneralist",
            game_slug="IEM Katowice",
            taxonomy_depth=2,
            raw_score=Decimal("40"),
            win_rate_component=Decimal("0.4"),
            concentration_component=Decimal("0.3"),
            recency_component=Decimal("0.2"),
            sample_size_component=Decimal("0.2"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="generalist",
            resolved_market_count=5,
            computed_at=datetime.now(UTC),
        )

        test_session.add_all([game_score, deep_score])
        test_session.commit()

        specialists = identify_hidden_specialists(
            test_session,
            game_slug="CS2",
            game_score_threshold=Decimal("60"),
            deep_score_threshold=Decimal("75"),
        )

        assert len(specialists) == 0
