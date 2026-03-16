"""Tests for multi-depth scoring foundations.

Tests for:
- Tournament and team concentration functions
- ExpertiseScore taxonomy_depth column
- Multi-depth position queries and leaderboard
"""

import pytest
from datetime import datetime
from decimal import Decimal
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import (
    Base,
    ExpertiseScore,
    Market,
    MarketEntity,
    Position,
)
from src.evaluation.concentration import (
    calculate_team_concentration,
    calculate_tournament_concentration,
)
from src.pipeline.queries import (
    get_all_slugs_with_positions_at_depth,
    get_positions_for_slug,
    get_taxonomy_leaderboard,
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


class TestTournamentConcentration:
    """Tests for calculate_tournament_concentration."""

    def test_normal_case(self):
        result = calculate_tournament_concentration(Decimal("30"), Decimal("100"))
        assert result == Decimal("0.3")

    def test_zero_denominator_returns_zero(self):
        result = calculate_tournament_concentration(Decimal("30"), Decimal("0"))
        assert result == Decimal("0")

    def test_full_concentration(self):
        result = calculate_tournament_concentration(Decimal("100"), Decimal("100"))
        assert result == Decimal("1")


class TestTeamConcentration:
    """Tests for calculate_team_concentration."""

    def test_normal_case(self):
        result = calculate_team_concentration(Decimal("20"), Decimal("50"))
        assert result == Decimal("0.4")

    def test_zero_denominator_returns_zero(self):
        result = calculate_team_concentration(Decimal("20"), Decimal("0"))
        assert result == Decimal("0")

    def test_full_concentration(self):
        result = calculate_team_concentration(Decimal("50"), Decimal("50"))
        assert result == Decimal("1")


class TestExpertiseScoreTaxonomyDepth:
    """Tests for ExpertiseScore.taxonomy_depth column."""

    def test_expertise_score_has_taxonomy_depth_column(self, test_session):
        """Verify ExpertiseScore has taxonomy_depth column with default=1."""
        inspector = inspect(test_session.bind)
        columns = [col["name"] for col in inspector.get_columns("expertise_scores")]
        assert "taxonomy_depth" in columns

    def test_taxonomy_depth_defaults_to_one(self, test_session):
        """Verify taxonomy_depth defaults to 1 for backward compatibility."""
        score = ExpertiseScore(
            trader_address="0xTestTrader",
            game_slug="esports.cs2",
            raw_score=Decimal("75"),
            percentile_rank=Decimal("80"),
            win_rate_component=Decimal("0.6"),
            concentration_component=Decimal("0.3"),
            recency_component=Decimal("0.1"),
            sample_size_component=Decimal("0.2"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=10,
            computed_at=datetime.utcnow(),
        )
        test_session.add(score)
        test_session.commit()

        test_session.expire_all()
        fetched = test_session.get(ExpertiseScore, score.id)
        assert fetched.taxonomy_depth == 1

    def test_taxonomy_depth_can_be_set(self, test_session):
        """Verify taxonomy_depth can be set to values other than default."""
        score = ExpertiseScore(
            trader_address="0xTestTrader2",
            game_slug="esports.cs2.iem-katowice",
            raw_score=Decimal("80"),
            percentile_rank=Decimal("85"),
            win_rate_component=Decimal("0.7"),
            concentration_component=Decimal("0.4"),
            recency_component=Decimal("0.2"),
            sample_size_component=Decimal("0.3"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=15,
            computed_at=datetime.utcnow(),
            taxonomy_depth=2,
        )
        test_session.add(score)
        test_session.commit()

        test_session.expire_all()
        fetched = test_session.get(ExpertiseScore, score.id)
        assert fetched.taxonomy_depth == 2


class TestGetPositionsForSlug:
    """Tests for get_positions_for_slug function."""

    def test_get_positions_for_tournament_slug(self, test_session):
        """Verify positions can be queried for a tournament entity name."""
        entity = MarketEntity(
            condition_id="test-market-1",
            team_a="NaVi",
            team_b="FaZe",
            tournament="IEM Katowice",
            game="CS2",
            market_type="match",
        )
        test_session.add(entity)

        market = Market(
            condition_id="test-market-1",
            question="Who wins IEM Katowice?",
            category="eSports",
            active=True,
        )
        test_session.add(market)

        position = Position(
            market_id="test-market-1",
            trader_address="0xTrader1",
            size=Decimal("100"),
            direction="LONG",
            trade_count=5,
        )
        test_session.add(position)
        test_session.commit()

        positions = get_positions_for_slug(test_session, "IEM Katowice")
        assert len(positions) == 1
        assert positions[0].trader_address == "0xTrader1"

    def test_get_positions_for_slug_with_trader_filter(self, test_session):
        """Verify trader_address filter works."""
        entity1 = MarketEntity(condition_id="test-market-2", game="CS2", market_type="match")
        entity2 = MarketEntity(condition_id="test-market-3", game="CS2", market_type="match")
        test_session.add_all([entity1, entity2])

        market1 = Market(
            condition_id="test-market-2",
            question="Test 1",
            category="eSports",
            active=True,
        )
        market2 = Market(
            condition_id="test-market-3",
            question="Test 2",
            category="eSports",
            active=True,
        )
        test_session.add_all([market1, market2])

        pos1 = Position(
            market_id="test-market-2",
            trader_address="0xTraderA",
            size=Decimal("50"),
            direction="LONG",
        )
        pos2 = Position(
            market_id="test-market-3",
            trader_address="0xTraderB",
            size=Decimal("75"),
            direction="SHORT",
        )
        test_session.add_all([pos1, pos2])
        test_session.commit()

        positions = get_positions_for_slug(
            test_session, "CS2", trader_address="0xTraderA"
        )
        assert len(positions) == 1
        assert positions[0].trader_address == "0xTraderA"


class TestGetTaxonomyLeaderboard:
    """Tests for get_taxonomy_leaderboard function."""

    def test_get_leaderboard_at_specific_depth(self, test_session):
        """Verify leaderboard filters by taxonomy_depth."""
        score1 = ExpertiseScore(
            trader_address="0xExpert1",
            game_slug="esports.cs2.iem-katowice",
            raw_score=Decimal("90"),
            win_rate_component=Decimal("0.8"),
            concentration_component=Decimal("0.5"),
            recency_component=Decimal("0.3"),
            sample_size_component=Decimal("0.4"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=20,
            taxonomy_depth=2,
            computed_at=datetime.utcnow(),
        )
        score2 = ExpertiseScore(
            trader_address="0xExpert2",
            game_slug="esports.cs2.iem-katowice",
            raw_score=Decimal("80"),
            win_rate_component=Decimal("0.7"),
            concentration_component=Decimal("0.4"),
            recency_component=Decimal("0.2"),
            sample_size_component=Decimal("0.3"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=15,
            taxonomy_depth=2,
            computed_at=datetime.utcnow(),
        )
        score3 = ExpertiseScore(
            trader_address="0xExpert3",
            game_slug="esports.cs2.iem-katowice",
            raw_score=Decimal("85"),
            win_rate_component=Decimal("0.75"),
            concentration_component=Decimal("0.45"),
            recency_component=Decimal("0.25"),
            sample_size_component=Decimal("0.35"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="specialist",
            resolved_market_count=18,
            taxonomy_depth=1,
            computed_at=datetime.utcnow(),
        )
        test_session.add_all([score1, score2, score3])
        test_session.commit()

        leaderboard = get_taxonomy_leaderboard(
            test_session, "esports.cs2.iem-katowice", taxonomy_depth=2, top_n=10
        )
        assert len(leaderboard) == 2

        addresses = [s.trader_address for s in leaderboard]
        assert "0xExpert1" in addresses
        assert "0xExpert2" in addresses
        assert "0xExpert3" not in addresses

    def test_leaderboard_top_n_limit(self, test_session):
        """Verify top_n limit works."""
        for i in range(5):
            score = ExpertiseScore(
                trader_address=f"0xTrader{i}",
                game_slug="esports.cs2",
                raw_score=Decimal(str(70 + i * 5)),
                win_rate_component=Decimal("0.5"),
                concentration_component=Decimal("0.3"),
                recency_component=Decimal("0.2"),
                sample_size_component=Decimal("0.2"),
                consistency_multiplier=Decimal("1.0"),
                specialization_label="specialist",
                resolved_market_count=10,
                taxonomy_depth=1,
                computed_at=datetime.utcnow(),
            )
            test_session.add(score)
        test_session.commit()

        leaderboard = get_taxonomy_leaderboard(
            test_session, "esports.cs2", taxonomy_depth=1, top_n=3
        )
        assert len(leaderboard) == 3


class TestGetAllSlugsWithPositionsAtDepth:
    """Tests for get_all_slugs_with_positions_at_depth function."""

    def test_get_slugs_at_specific_depth(self, test_session):
        """Verify entity names can be queried at specific depth."""
        # MarketEntity with tournament but no game — so depth=1 returns empty
        entity = MarketEntity(
            condition_id="test-market-depth",
            tournament="IEM Katowice",
            game=None,
            market_type="match",
        )
        test_session.add(entity)

        market = Market(
            condition_id="test-market-depth",
            question="Test",
            category="eSports",
            active=True,
        )
        test_session.add(market)

        position = Position(
            market_id="test-market-depth",
            trader_address="0xTest",
            size=Decimal("10"),
            direction="LONG",
        )
        test_session.add(position)
        test_session.commit()

        depth2_slugs = get_all_slugs_with_positions_at_depth(test_session, depth=2)
        assert "IEM Katowice" in depth2_slugs

        depth1_slugs = get_all_slugs_with_positions_at_depth(test_session, depth=1)
        assert len(depth1_slugs) == 0
