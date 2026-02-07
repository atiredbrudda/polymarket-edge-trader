"""Integration tests for signal query functions.

Test coverage:
- get_latest_signals: latest per market, status filtering, confidence filtering
- get_signal_history: chronological order, direction filtering
- get_expert_positions_for_market: expert filtering, FLAT exclusion
- get_markets_by_expert_activity: time-window filtering, min expert count, ranking
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, SignalSnapshot, Position, ExpertiseScore, Market, Trader
from src.signals.queries import (
    get_latest_signals,
    get_signal_history,
    get_expert_positions_for_market,
    get_markets_by_expert_activity,
)


@pytest.fixture
def session():
    """Create in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_data(session):
    """Create sample test data: markets, traders, positions, scores, signals."""
    now = datetime.now(UTC)

    # Markets
    markets = [
        Market(condition_id="market1", question="CS2: NaVi vs FaZe", category="esports", active=True),
        Market(condition_id="market2", question="Dota2: OG vs Liquid", category="esports", active=True),
        Market(condition_id="market3", question="LoL: T1 vs GenG", category="esports", active=True),
    ]
    session.add_all(markets)

    # Traders
    traders = [
        Trader(address="0xExpert1", first_seen=now - timedelta(days=90)),
        Trader(address="0xExpert2", first_seen=now - timedelta(days=60)),
        Trader(address="0xExpert3", first_seen=now - timedelta(days=30)),
        Trader(address="0xNovice1", first_seen=now - timedelta(days=10)),
    ]
    session.add_all(traders)

    # ExpertiseScores (latest snapshots)
    scores = [
        ExpertiseScore(
            trader_address="0xExpert1",
            game_slug="esports.cs2",
            raw_score=Decimal("85.5"),
            percentile_rank=Decimal("95.0"),
            win_rate_component=Decimal("34.0"),
            concentration_component=Decimal("21.0"),
            recency_component=Decimal("17.0"),
            sample_size_component=Decimal("13.5"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="CS2 Specialist",
            resolved_market_count=20,
            computed_at=now - timedelta(hours=1),
        ),
        ExpertiseScore(
            trader_address="0xExpert2",
            game_slug="esports.dota2",
            raw_score=Decimal("78.2"),
            percentile_rank=Decimal("88.0"),
            win_rate_component=Decimal("31.0"),
            concentration_component=Decimal("19.5"),
            recency_component=Decimal("15.6"),
            sample_size_component=Decimal("12.1"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="Dota2 Specialist",
            resolved_market_count=15,
            computed_at=now - timedelta(hours=2),
        ),
        ExpertiseScore(
            trader_address="0xExpert3",
            game_slug="esports.lol",
            raw_score=Decimal("72.0"),
            percentile_rank=Decimal("80.0"),
            win_rate_component=Decimal("28.8"),
            concentration_component=Decimal("18.0"),
            recency_component=Decimal("14.4"),
            sample_size_component=Decimal("10.8"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="LoL Specialist",
            resolved_market_count=12,
            computed_at=now - timedelta(hours=3),
        ),
        ExpertiseScore(
            trader_address="0xNovice1",
            game_slug="esports.cs2",
            raw_score=Decimal("45.0"),
            percentile_rank=Decimal("30.0"),
            win_rate_component=Decimal("18.0"),
            concentration_component=Decimal("11.25"),
            recency_component=Decimal("9.0"),
            sample_size_component=Decimal("6.75"),
            consistency_multiplier=Decimal("1.0"),
            specialization_label="Generalist",
            resolved_market_count=5,
            computed_at=now - timedelta(hours=4),
        ),
    ]
    session.add_all(scores)

    # Positions
    positions = [
        # Market 1: 2 experts (0xExpert1 LONG, 0xExpert2 LONG), 1 novice (0xNovice1 SHORT)
        Position(
            market_id="market1",
            trader_address="0xExpert1",
            size=Decimal("100.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.55"),
            entry_timestamp=now - timedelta(hours=2),
            first_trade_timestamp=now - timedelta(hours=2),
            last_trade_timestamp=now - timedelta(hours=1),
            trade_count=3,
            resolved=False,
        ),
        Position(
            market_id="market1",
            trader_address="0xExpert2",
            size=Decimal("200.0"),
            direction="LONG",
            avg_entry_price=Decimal("0.52"),
            entry_timestamp=now - timedelta(hours=3),
            first_trade_timestamp=now - timedelta(hours=3),
            last_trade_timestamp=now - timedelta(hours=2, minutes=30),
            trade_count=5,
            resolved=False,
        ),
        Position(
            market_id="market1",
            trader_address="0xNovice1",
            size=Decimal("50.0"),
            direction="SHORT",
            avg_entry_price=Decimal("0.48"),
            entry_timestamp=now - timedelta(minutes=30),
            first_trade_timestamp=now - timedelta(minutes=30),
            last_trade_timestamp=now - timedelta(minutes=30),
            trade_count=1,
            resolved=False,
        ),
        # Market 2: 1 expert (0xExpert2 SHORT) from 25 hours ago (outside 24h window)
        Position(
            market_id="market2",
            trader_address="0xExpert2",
            size=Decimal("150.0"),
            direction="SHORT",
            avg_entry_price=Decimal("0.60"),
            entry_timestamp=now - timedelta(hours=25),
            first_trade_timestamp=now - timedelta(hours=25),
            last_trade_timestamp=now - timedelta(hours=25),
            trade_count=2,
            resolved=False,
        ),
        # Market 3: 2 experts (0xExpert1 SHORT, 0xExpert3 SHORT) from 5 hours ago
        Position(
            market_id="market3",
            trader_address="0xExpert1",
            size=Decimal("120.0"),
            direction="SHORT",
            avg_entry_price=Decimal("0.45"),
            entry_timestamp=now - timedelta(hours=5),
            first_trade_timestamp=now - timedelta(hours=5),
            last_trade_timestamp=now - timedelta(hours=5),
            trade_count=2,
            resolved=False,
        ),
        Position(
            market_id="market3",
            trader_address="0xExpert3",
            size=Decimal("80.0"),
            direction="SHORT",
            avg_entry_price=Decimal("0.47"),
            entry_timestamp=now - timedelta(hours=6),
            first_trade_timestamp=now - timedelta(hours=6),
            last_trade_timestamp=now - timedelta(hours=6),
            trade_count=1,
            resolved=False,
        ),
        # FLAT position (should be excluded from expert positions query)
        Position(
            market_id="market1",
            trader_address="0xExpert3",
            size=Decimal("0.0"),
            direction="FLAT",
            avg_entry_price=None,
            entry_timestamp=None,
            first_trade_timestamp=now - timedelta(hours=10),
            last_trade_timestamp=now - timedelta(hours=8),
            trade_count=4,
            resolved=False,
        ),
    ]
    session.add_all(positions)

    # SignalSnapshots
    signals = [
        # Market 1 LONG: 2 snapshots (older and latest)
        SignalSnapshot(
            market_id="market1",
            direction="LONG",
            confidence_score=Decimal("75.0"),
            expert_count=2,
            total_experts_in_market=2,
            agreement_percentage=Decimal("100.0"),
            expert_addresses_json='["0xExpert1", "0xExpert2"]',
            first_mover_address="0xExpert2",
            status="active",
            computed_at=now - timedelta(hours=4),
        ),
        SignalSnapshot(
            market_id="market1",
            direction="LONG",
            confidence_score=Decimal("82.5"),
            expert_count=2,
            total_experts_in_market=2,
            agreement_percentage=Decimal("100.0"),
            expert_addresses_json='["0xExpert1", "0xExpert2"]',
            first_mover_address="0xExpert2",
            status="active",
            computed_at=now - timedelta(hours=1),
        ),
        # Market 2 SHORT: inactive status
        SignalSnapshot(
            market_id="market2",
            direction="SHORT",
            confidence_score=Decimal("68.0"),
            expert_count=1,
            total_experts_in_market=1,
            agreement_percentage=Decimal("100.0"),
            expert_addresses_json='["0xExpert2"]',
            first_mover_address="0xExpert2",
            status="inactive",
            computed_at=now - timedelta(hours=2),
        ),
        # Market 3 SHORT: below min confidence threshold
        SignalSnapshot(
            market_id="market3",
            direction="SHORT",
            confidence_score=Decimal("65.0"),
            expert_count=2,
            total_experts_in_market=2,
            agreement_percentage=Decimal("100.0"),
            expert_addresses_json='["0xExpert1", "0xExpert3"]',
            first_mover_address="0xExpert3",
            status="active",
            computed_at=now - timedelta(hours=3),
        ),
    ]
    session.add_all(signals)

    session.commit()


class TestGetLatestSignals:
    """Tests for get_latest_signals query function."""

    def test_returns_latest_per_market(self, session, sample_data):
        """Should return only the latest snapshot per market+direction."""
        result = get_latest_signals(session, status=None, limit=10)

        # Should get 3 signals (market1 LONG latest, market2 SHORT, market3 SHORT)
        assert len(result) == 3

        # Market 1 LONG should be the latest snapshot (82.5)
        market1_signal = [s for s in result if s.market_id == "market1" and s.direction == "LONG"][0]
        assert market1_signal.confidence_score == Decimal("82.5")

    def test_filters_by_status(self, session, sample_data):
        """Should filter by status field."""
        # Active only
        active = get_latest_signals(session, status="active", limit=10)
        assert len(active) == 2
        assert all(s.status == "active" for s in active)

        # Inactive only
        inactive = get_latest_signals(session, status="inactive", limit=10)
        assert len(inactive) == 1
        assert inactive[0].status == "inactive"
        assert inactive[0].market_id == "market2"

    def test_min_confidence_filter(self, session, sample_data):
        """Should filter by minimum confidence score."""
        result = get_latest_signals(session, status=None, min_confidence=Decimal("70.0"), limit=10)

        # Should get 2 signals (market1 82.5 active, market2 68.0 inactive excluded, market3 65.0 excluded)
        # Wait, market2 is 68.0 < 70.0, so should be excluded
        assert len(result) == 1
        assert all(s.confidence_score >= Decimal("70.0") for s in result)
        assert result[0].market_id == "market1"

    def test_orders_by_confidence_desc(self, session, sample_data):
        """Should order results by confidence_score DESC."""
        result = get_latest_signals(session, status=None, limit=10)

        # Should be ordered: market1 (82.5), market2 (68.0), market3 (65.0)
        assert result[0].confidence_score == Decimal("82.5")
        assert result[1].confidence_score == Decimal("68.0")
        assert result[2].confidence_score == Decimal("65.0")

    def test_respects_limit(self, session, sample_data):
        """Should respect the limit parameter."""
        result = get_latest_signals(session, status=None, limit=2)

        assert len(result) == 2
        # Should get top 2 by confidence
        assert result[0].confidence_score == Decimal("82.5")
        assert result[1].confidence_score == Decimal("68.0")


class TestGetSignalHistory:
    """Tests for get_signal_history query function."""

    def test_returns_chronological_history(self, session, sample_data):
        """Should return all snapshots for a market ordered by computed_at DESC."""
        result = get_signal_history(session, "market1", limit=10)

        # Should get 2 snapshots for market1
        assert len(result) == 2

        # Should be ordered by computed_at DESC (latest first)
        assert result[0].confidence_score == Decimal("82.5")
        assert result[1].confidence_score == Decimal("75.0")
        assert result[0].computed_at > result[1].computed_at

    def test_filters_by_direction(self, session, sample_data):
        """Should filter by direction when provided."""
        result = get_signal_history(session, "market1", direction="LONG", limit=10)

        assert len(result) == 2
        assert all(s.direction == "LONG" for s in result)

    def test_respects_limit(self, session, sample_data):
        """Should respect the limit parameter."""
        result = get_signal_history(session, "market1", limit=1)

        assert len(result) == 1
        assert result[0].confidence_score == Decimal("82.5")  # Latest only


class TestGetExpertPositionsForMarket:
    """Tests for get_expert_positions_for_market query function."""

    def test_filters_non_experts(self, session, sample_data):
        """Should exclude traders with score <= min_score."""
        result = get_expert_positions_for_market(session, "market1", min_score=Decimal("70"))

        # Should get 2 positions (0xExpert1 and 0xExpert2, exclude 0xNovice1 with score 45)
        assert len(result) == 2
        addresses = {p.trader_address for p in result}
        assert addresses == {"0xExpert1", "0xExpert2"}
        assert "0xNovice1" not in addresses

    def test_excludes_flat_positions(self, session, sample_data):
        """Should exclude FLAT direction positions."""
        result = get_expert_positions_for_market(session, "market1", min_score=Decimal("70"))

        # 0xExpert3 has a FLAT position in market1, should be excluded
        addresses = {p.trader_address for p in result}
        assert "0xExpert3" not in addresses

        # All returned positions should be LONG or SHORT
        assert all(p.direction in ["LONG", "SHORT"] for p in result)

    def test_returns_correct_market_positions(self, session, sample_data):
        """Should return positions only for the specified market."""
        result = get_expert_positions_for_market(session, "market3", min_score=Decimal("70"))

        # Market 3 has 2 expert positions (0xExpert1 and 0xExpert3)
        assert len(result) == 2
        assert all(p.market_id == "market3" for p in result)


class TestGetMarketsByExpertActivity:
    """Tests for get_markets_by_expert_activity query function."""

    def test_filters_by_time_window(self, session, sample_data):
        """Should exclude positions outside the time window."""
        # 24 hour window should exclude market2 (last_trade 25 hours ago)
        result = get_markets_by_expert_activity(session, window_hours=24, min_experts=1)

        market_ids = {r[0] for r in result}
        assert "market1" in market_ids
        assert "market3" in market_ids
        assert "market2" not in market_ids  # 25 hours ago, outside window

    def test_filters_by_min_experts(self, session, sample_data):
        """Should exclude markets with fewer than min_experts."""
        # Require 2 experts minimum
        result = get_markets_by_expert_activity(session, window_hours=24, min_experts=2)

        # Market1 has 2 experts, market3 has 2 experts
        assert len(result) == 2
        market_ids = {r[0] for r in result}
        assert "market1" in market_ids
        assert "market3" in market_ids

    def test_orders_by_expert_count_then_recency(self, session, sample_data):
        """Should order by expert_count DESC, then latest_activity DESC."""
        result = get_markets_by_expert_activity(session, window_hours=24, min_experts=1)

        # All have 2 experts, so should order by recency
        # Market1: latest is 1 hour ago
        # Market3: latest is 5 hours ago
        assert result[0][0] == "market1"  # Most recent
        assert result[1][0] == "market3"

    def test_returns_correct_tuple_format(self, session, sample_data):
        """Should return (market_id, expert_count, latest_activity) tuples."""
        result = get_markets_by_expert_activity(session, window_hours=24, min_experts=1)

        assert len(result) > 0
        for row in result:
            assert len(row) == 3
            assert isinstance(row[0], str)  # market_id
            assert isinstance(row[1], int)  # expert_count
            assert isinstance(row[2], datetime)  # latest_activity
