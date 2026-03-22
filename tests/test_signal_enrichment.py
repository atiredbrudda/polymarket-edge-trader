"""Tests for signal enrichment: LiftScore Q5 rewire + expert_avg_entry price context.

Test coverage:
- get_expert_positions_for_market uses LiftScore Q5 (not ExpertiseScore raw_score>70)
- get_markets_by_expert_activity uses LiftScore Q5
- ConsensusResult includes expert_avg_entry
- detect_consensus includes all traders in expert_scores dict (no >70 threshold)
- SignalResult includes expert_avg_entry from pipeline
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, Position, LiftScore, Market, Trader, SignalSnapshot


@pytest.fixture
def session():
    """Create in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def now():
    return datetime.now(UTC)


@pytest.fixture
def base_data(session, now):
    """Set up markets, traders, positions, and LiftScore rows.

    Traders:
    - 0xQ5Expert1: quintile=5 (Q5)
    - 0xQ5Expert2: quintile=5 (Q5)
    - 0xQ5Expert3: quintile=5 (Q5)
    - 0xQ3Trader: quintile=3 (should be excluded)

    Market: market1
    Positions: all 4 traders have positions in market1
    """
    # Markets
    session.add(Market(condition_id="market1", question="CS2: NaVi vs FaZe", category="esports", active=True))
    session.add(Market(condition_id="market2", question="Dota2: OG vs Liquid", category="esports", active=True))

    # Traders
    for addr in ["0xQ5Expert1", "0xQ5Expert2", "0xQ5Expert3", "0xQ3Trader"]:
        session.add(Trader(address=addr, first_seen=now - timedelta(days=90)))

    # Positions in market1 for all traders
    positions = [
        Position(
            market_id="market1",
            trader_address="0xQ5Expert1",
            direction="LONG",
            size=Decimal("100"),
            avg_entry_price=Decimal("0.30"),
            last_trade_timestamp=now - timedelta(hours=2),
            resolved=False,
        ),
        Position(
            market_id="market1",
            trader_address="0xQ5Expert2",
            direction="LONG",
            size=Decimal("200"),
            avg_entry_price=Decimal("0.35"),
            last_trade_timestamp=now - timedelta(hours=3),
            resolved=False,
        ),
        Position(
            market_id="market1",
            trader_address="0xQ5Expert3",
            direction="LONG",
            size=Decimal("150"),
            avg_entry_price=Decimal("0.40"),
            last_trade_timestamp=now - timedelta(hours=1),
            resolved=False,
        ),
        Position(
            market_id="market1",
            trader_address="0xQ3Trader",
            direction="LONG",
            size=Decimal("50"),
            avg_entry_price=Decimal("0.60"),
            last_trade_timestamp=now - timedelta(hours=5),
            resolved=False,
        ),
    ]
    session.add_all(positions)

    # LiftScore rows
    window_start = now - timedelta(days=30)
    lift_scores = [
        LiftScore(
            trader_address="0xQ5Expert1",
            category="esports",
            composite_score=Decimal("2.500"),
            clv_raw=Decimal("0.05"),
            clv_zscore=Decimal("1.5"),
            roi_raw=Decimal("0.12"),
            roi_zscore=Decimal("1.0"),
            sharpe_raw=Decimal("2.1"),
            sharpe_zscore=Decimal("1.0"),
            quintile=5,
            position_count=50,
            total_pnl=Decimal("500"),
            capital_deployed=Decimal("5000"),
            window_start=window_start,
            window_end=now,
            computed_at=now,
        ),
        LiftScore(
            trader_address="0xQ5Expert2",
            category="esports",
            composite_score=Decimal("2.100"),
            clv_raw=Decimal("0.04"),
            clv_zscore=Decimal("1.2"),
            roi_raw=Decimal("0.10"),
            roi_zscore=Decimal("0.9"),
            sharpe_raw=Decimal("1.8"),
            sharpe_zscore=Decimal("0.9"),
            quintile=5,
            position_count=40,
            total_pnl=Decimal("400"),
            capital_deployed=Decimal("4000"),
            window_start=window_start,
            window_end=now,
            computed_at=now,
        ),
        LiftScore(
            trader_address="0xQ5Expert3",
            category="esports",
            composite_score=Decimal("1.900"),
            clv_raw=Decimal("0.03"),
            clv_zscore=Decimal("1.0"),
            roi_raw=Decimal("0.08"),
            roi_zscore=Decimal("0.7"),
            sharpe_raw=Decimal("1.5"),
            sharpe_zscore=Decimal("0.8"),
            quintile=5,
            position_count=35,
            total_pnl=Decimal("300"),
            capital_deployed=Decimal("3000"),
            window_start=window_start,
            window_end=now,
            computed_at=now,
        ),
        LiftScore(
            trader_address="0xQ3Trader",
            category="esports",
            composite_score=Decimal("0.200"),
            clv_raw=Decimal("0.01"),
            clv_zscore=Decimal("0.1"),
            roi_raw=Decimal("0.02"),
            roi_zscore=Decimal("0.1"),
            sharpe_raw=Decimal("0.3"),
            sharpe_zscore=Decimal("0.1"),
            quintile=3,
            position_count=15,
            total_pnl=Decimal("50"),
            capital_deployed=Decimal("1000"),
            window_start=window_start,
            window_end=now,
            computed_at=now,
        ),
    ]
    session.add_all(lift_scores)
    session.commit()
    return session


class TestGetExpertPositionsForMarket:
    """Tests for get_expert_positions_for_market using LiftScore Q5."""

    def test_returns_only_q5_positions(self, base_data):
        """Q3 trader position must be excluded; only Q5 positions returned."""
        from src.signals.queries import get_expert_positions_for_market

        positions = get_expert_positions_for_market(base_data, "market1")

        trader_addresses = {p.trader_address for p in positions}
        assert "0xQ3Trader" not in trader_addresses
        assert "0xQ5Expert1" in trader_addresses
        assert "0xQ5Expert2" in trader_addresses
        assert "0xQ5Expert3" in trader_addresses

    def test_returns_three_q5_positions(self, base_data):
        """Exactly 3 Q5 expert positions returned for market1."""
        from src.signals.queries import get_expert_positions_for_market

        positions = get_expert_positions_for_market(base_data, "market1")
        assert len(positions) == 3

    def test_excludes_flat_positions(self, session, now):
        """FLAT direction positions are excluded even if trader is Q5."""
        window_start = now - timedelta(days=30)
        session.add(Market(condition_id="mflat", question="Test", category="esports", active=True))
        session.add(Trader(address="0xFlatQ5", first_seen=now))
        session.add(Position(
            market_id="mflat",
            trader_address="0xFlatQ5",
            direction="FLAT",
            size=Decimal("0"),
            avg_entry_price=None,
            last_trade_timestamp=now,
            resolved=False,
        ))
        session.add(LiftScore(
            trader_address="0xFlatQ5",
            category="esports",
            composite_score=Decimal("2.0"),
            clv_raw=Decimal("0.05"), clv_zscore=Decimal("1.0"),
            roi_raw=Decimal("0.10"), roi_zscore=Decimal("1.0"),
            sharpe_raw=Decimal("2.0"), sharpe_zscore=Decimal("1.0"),
            quintile=5,
            position_count=20,
            total_pnl=Decimal("200"),
            capital_deployed=Decimal("2000"),
            window_start=window_start, window_end=now, computed_at=now,
        ))
        session.commit()

        from src.signals.queries import get_expert_positions_for_market
        positions = get_expert_positions_for_market(session, "mflat")
        assert len(positions) == 0

    def test_no_lift_scores_returns_empty(self, session):
        """Returns empty list when no LiftScore rows exist."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Market(condition_id="m1", question="Test", category="esports", active=True))
            s.add(Trader(address="0xNoScore", first_seen=datetime.now(UTC)))
            s.add(Position(
                market_id="m1",
                trader_address="0xNoScore",
                direction="LONG",
                size=Decimal("100"),
                avg_entry_price=Decimal("0.5"),
                last_trade_timestamp=datetime.now(UTC),
                resolved=False,
            ))
            s.commit()

            from src.signals.queries import get_expert_positions_for_market
            positions = get_expert_positions_for_market(s, "m1")
            assert positions == []


class TestGetMarketsByExpertActivity:
    """Tests for get_markets_by_expert_activity using LiftScore Q5."""

    def test_returns_markets_with_q5_activity(self, base_data, now):
        """Market1 has Q5 activity; should be returned."""
        from src.signals.queries import get_markets_by_expert_activity

        results = get_markets_by_expert_activity(base_data, window_hours=24)
        market_ids = [r[0] for r in results]
        assert "market1" in market_ids

    def test_excludes_q3_only_markets(self, session, now):
        """Market with only Q3 traders should NOT be returned."""
        window_start = now - timedelta(days=30)
        session.add(Market(condition_id="q3only", question="Q3 only market", category="esports", active=True))
        session.add(Trader(address="0xQ3Only", first_seen=now))
        session.add(Position(
            market_id="q3only",
            trader_address="0xQ3Only",
            direction="LONG",
            size=Decimal("100"),
            avg_entry_price=Decimal("0.5"),
            last_trade_timestamp=now - timedelta(hours=1),
            resolved=False,
        ))
        session.add(LiftScore(
            trader_address="0xQ3Only",
            category="esports",
            composite_score=Decimal("0.2"),
            clv_raw=Decimal("0.01"), clv_zscore=Decimal("0.1"),
            roi_raw=Decimal("0.02"), roi_zscore=Decimal("0.1"),
            sharpe_raw=Decimal("0.3"), sharpe_zscore=Decimal("0.1"),
            quintile=3,
            position_count=5,
            total_pnl=Decimal("10"),
            capital_deployed=Decimal("500"),
            window_start=window_start, window_end=now, computed_at=now,
        ))
        session.commit()

        from src.signals.queries import get_markets_by_expert_activity
        results = get_markets_by_expert_activity(session, window_hours=24)
        market_ids = [r[0] for r in results]
        assert "q3only" not in market_ids

    def test_respects_time_window(self, session, now):
        """Positions outside window are excluded."""
        window_start = now - timedelta(days=30)
        session.add(Market(condition_id="old_market", question="Old", category="esports", active=True))
        session.add(Trader(address="0xOldQ5", first_seen=now))
        # Position with last_trade_timestamp > 48h ago
        session.add(Position(
            market_id="old_market",
            trader_address="0xOldQ5",
            direction="LONG",
            size=Decimal("100"),
            avg_entry_price=Decimal("0.5"),
            last_trade_timestamp=now - timedelta(hours=72),
            resolved=False,
        ))
        session.add(LiftScore(
            trader_address="0xOldQ5",
            category="esports",
            composite_score=Decimal("2.0"),
            clv_raw=Decimal("0.05"), clv_zscore=Decimal("1.0"),
            roi_raw=Decimal("0.10"), roi_zscore=Decimal("1.0"),
            sharpe_raw=Decimal("2.0"), sharpe_zscore=Decimal("1.0"),
            quintile=5,
            position_count=20,
            total_pnl=Decimal("200"),
            capital_deployed=Decimal("2000"),
            window_start=window_start, window_end=now, computed_at=now,
        ))
        session.commit()

        from src.signals.queries import get_markets_by_expert_activity
        results = get_markets_by_expert_activity(session, window_hours=24)
        market_ids = [r[0] for r in results]
        assert "old_market" not in market_ids

    def test_result_includes_expert_count(self, base_data, now):
        """Result tuple includes (market_id, expert_count, latest_activity)."""
        from src.signals.queries import get_markets_by_expert_activity

        results = get_markets_by_expert_activity(base_data, window_hours=24)
        assert len(results) > 0
        market_id, expert_count, latest_activity = results[0]
        assert isinstance(market_id, str)
        assert isinstance(expert_count, int)
        assert expert_count >= 1


class TestConsensusResultExpertAvgEntry:
    """Tests for expert_avg_entry in ConsensusResult."""

    def test_expert_avg_entry_computed_correctly(self):
        """3 experts with avg_entry 0.30, 0.35, 0.40 -> expert_avg_entry ≈ 0.35."""
        from src.signals.detection import detect_consensus, ConsensusResult

        class MockPos:
            def __init__(self, addr, direction, price):
                self.market_id = "market1"
                self.trader_address = addr
                self.direction = direction
                self.size = Decimal("100")
                self.avg_entry_price = Decimal(str(price))
                self.entry_timestamp = None

        positions = [
            MockPos("trader1", "LONG", "0.30"),
            MockPos("trader2", "LONG", "0.35"),
            MockPos("trader3", "LONG", "0.40"),
        ]
        # All traders in expert_scores = Q5 pre-filtered
        expert_scores = {
            "trader1": Decimal("2.5"),
            "trader2": Decimal("2.0"),
            "trader3": Decimal("1.9"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))
        assert len(results) == 1
        result = results[0]

        assert hasattr(result, "expert_avg_entry")
        assert result.expert_avg_entry is not None
        # Expected: (0.30 + 0.35 + 0.40) / 3 = 0.35
        expected = Decimal("0.35")
        assert abs(result.expert_avg_entry - expected) < Decimal("0.001")

    def test_expert_avg_entry_none_when_no_entry_prices(self):
        """expert_avg_entry is None when all avg_entry_price are None."""
        from src.signals.detection import detect_consensus

        class MockPos:
            def __init__(self, addr, direction):
                self.market_id = "market1"
                self.trader_address = addr
                self.direction = direction
                self.size = Decimal("100")
                self.avg_entry_price = None
                self.entry_timestamp = None

        positions = [MockPos("t1", "LONG"), MockPos("t2", "LONG"), MockPos("t3", "LONG")]
        expert_scores = {"t1": Decimal("2.5"), "t2": Decimal("2.0"), "t3": Decimal("1.9")}

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))
        assert len(results) == 1
        assert results[0].expert_avg_entry is None

    def test_expert_avg_entry_partial_prices(self):
        """expert_avg_entry averages only positions with non-None prices."""
        from src.signals.detection import detect_consensus

        class MockPos:
            def __init__(self, addr, direction, price):
                self.market_id = "market1"
                self.trader_address = addr
                self.direction = direction
                self.size = Decimal("100")
                self.avg_entry_price = Decimal(str(price)) if price is not None else None
                self.entry_timestamp = None

        positions = [
            MockPos("t1", "LONG", "0.30"),
            MockPos("t2", "LONG", None),
            MockPos("t3", "LONG", "0.40"),
        ]
        expert_scores = {"t1": Decimal("2.5"), "t2": Decimal("2.0"), "t3": Decimal("1.9")}

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))
        assert len(results) == 1
        # Average of 0.30 and 0.40 = 0.35
        assert results[0].expert_avg_entry is not None
        expected = Decimal("0.35")
        assert abs(results[0].expert_avg_entry - expected) < Decimal("0.001")


class TestDetectConsensusNoThreshold:
    """Tests for detect_consensus using caller-pre-filtered expert_scores dict."""

    def test_all_traders_in_dict_are_counted(self):
        """Traders in expert_scores dict are counted; no >70 threshold applied."""
        from src.signals.detection import detect_consensus

        class MockPos:
            def __init__(self, addr, direction, price=None):
                self.market_id = "market1"
                self.trader_address = addr
                self.direction = direction
                self.size = Decimal("100")
                self.avg_entry_price = Decimal(str(price)) if price else None
                self.entry_timestamp = None

        # Use very low composite scores (formerly would be < 70, excluded)
        # Now: all traders in dict should be counted as experts
        positions = [
            MockPos("t1", "LONG", "0.5"),
            MockPos("t2", "LONG", "0.5"),
            MockPos("t3", "LONG", "0.5"),
        ]
        expert_scores = {
            "t1": Decimal("0.5"),   # low composite but Q5 pre-filtered
            "t2": Decimal("0.3"),
            "t3": Decimal("0.2"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))
        assert len(results) == 1
        assert results[0].expert_count == 3

    def test_traders_not_in_dict_excluded(self):
        """Traders NOT in expert_scores dict are excluded from consensus."""
        from src.signals.detection import detect_consensus

        class MockPos:
            def __init__(self, addr, direction):
                self.market_id = "market1"
                self.trader_address = addr
                self.direction = direction
                self.size = Decimal("100")
                self.avg_entry_price = None
                self.entry_timestamp = None

        positions = [
            MockPos("t1", "LONG"),
            MockPos("t2", "LONG"),
            MockPos("t3", "LONG"),
            MockPos("nonexpert", "LONG"),  # not in expert_scores
        ]
        expert_scores = {"t1": Decimal("2.5"), "t2": Decimal("2.0"), "t3": Decimal("1.9")}

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))
        assert len(results) == 1
        # Only 3 experts in market, nonexpert excluded
        assert results[0].expert_count == 3
        assert results[0].total_experts_in_market == 3


class TestSignalResultExpertAvgEntry:
    """Tests for expert_avg_entry in SignalResult from pipeline."""

    def test_signal_result_has_expert_avg_entry_field(self, base_data, now):
        """SignalResult dataclass has expert_avg_entry field."""
        from src.signals.pipeline import SignalResult
        import dataclasses

        fields = {f.name for f in dataclasses.fields(SignalResult)}
        assert "expert_avg_entry" in fields

    def test_refresh_market_signal_populates_expert_avg_entry(self, base_data, now):
        """refresh_market_signal populates expert_avg_entry from positions."""
        from src.signals.pipeline import refresh_market_signal

        results = refresh_market_signal(base_data, "market1", min_experts=3, min_agreement_pct=Decimal("75"), now=now)

        # With 3 Q5 experts all LONG, should get consensus
        assert len(results) == 1
        result = results[0]
        assert hasattr(result, "expert_avg_entry")
        # All 3 experts have entry prices, so avg should be (0.30+0.35+0.40)/3 = 0.35
        assert result.expert_avg_entry is not None
        expected = Decimal("0.35")
        assert abs(result.expert_avg_entry - expected) < Decimal("0.01")
