"""Integration tests for signal detection pipeline.

Tests end-to-end signal detection flow including:
- Consensus detection from expert positions
- Confidence score calculation
- Signal persistence (append-only)
- Signal lost handling
- First-mover and follower tracking
- Batch processing and time-window filtering
- Herding stub behavior
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Market, Trader, Position, LiftScore, SignalSnapshot
from src.signals.pipeline import (
    refresh_market_signal,
    refresh_all_signals,
    get_ranked_signals,
    assess_herding,
    SignalResult,
)


def make_lift_score(trader_address, now, quintile=5, composite_score=None):
    """Helper to create a LiftScore fixture for a trader."""
    if composite_score is None:
        composite_score = Decimal("2.0") if quintile == 5 else Decimal("0.5")
    window_start = now - timedelta(days=30)
    return LiftScore(
        trader_address=trader_address,
        category="esports",
        composite_score=composite_score,
        clv_raw=Decimal("0.05"),
        clv_zscore=Decimal("1.0"),
        roi_raw=Decimal("0.10"),
        roi_zscore=Decimal("1.0"),
        sharpe_raw=Decimal("2.0"),
        sharpe_zscore=Decimal("1.0"),
        quintile=quintile,
        position_count=20,
        total_pnl=Decimal("200"),
        capital_deployed=Decimal("2000"),
        window_start=window_start,
        window_end=now,
        computed_at=now - timedelta(hours=1),
    )


@pytest.fixture
def session():
    """Create in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_refresh_market_signal_detects_consensus(session):
    """Test that refresh_market_signal detects consensus with 3 LONG experts."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket1",
        question="Test Market 1",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders
    traders = []
    for i in range(4):
        trader = Trader(address=f"0xTrader{i}")
        traders.append(trader)
        session.add(trader)

    # Create positions: 3 LONG experts, 1 SHORT expert
    positions_data = [
        ("0xTrader0", "LONG", Decimal("100"), Decimal("0.5"), now - timedelta(hours=10)),
        ("0xTrader1", "LONG", Decimal("200"), Decimal("0.5"), now - timedelta(hours=8)),
        ("0xTrader2", "LONG", Decimal("150"), Decimal("0.5"), now - timedelta(hours=6)),
        ("0xTrader3", "SHORT", Decimal("100"), Decimal("0.5"), now - timedelta(hours=5)),
    ]

    for trader_address, direction, size, price, entry_time in positions_data:
        position = Position(
            market_id="0xMarket1",
            trader_address=trader_address,
            direction=direction,
            size=size,
            avg_entry_price=price,
            entry_timestamp=entry_time,
            last_trade_timestamp=entry_time,
            resolved=False,
        )
        session.add(position)

    # Create Q5 LiftScore rows for all traders
    for addr in ["0xTrader0", "0xTrader1", "0xTrader2", "0xTrader3"]:
        session.add(make_lift_score(addr, now, quintile=5))

    session.commit()

    # Test refresh_market_signal
    results = refresh_market_signal(session, "0xMarket1", min_experts=3, now=now)

    # Verify result
    assert len(results) == 1
    result = results[0]
    assert result.direction == "LONG"
    assert result.expert_count == 3
    assert result.total_experts_in_market == 4
    assert result.agreement_percentage == Decimal("75")  # 3/4 * 100
    assert result.confidence_score > 0
    assert result.status == "active"
    assert len(result.expert_addresses) == 3
    assert set(result.expert_addresses) == {"0xTrader0", "0xTrader1", "0xTrader2"}

    # Verify SignalSnapshot persisted in DB
    snapshots = session.query(SignalSnapshot).filter_by(market_id="0xMarket1").all()
    assert len(snapshots) == 1
    assert snapshots[0].direction == "LONG"
    assert snapshots[0].expert_count == 3
    assert snapshots[0].status == "active"


def test_refresh_market_signal_no_consensus(session):
    """Test that no consensus is detected when expert count below minimum."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket2",
        question="Test Market 2",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders
    for i in range(2):
        trader = Trader(address=f"0xTrader{i}")
        session.add(trader)

    # Create positions: only 2 LONG experts (below min_experts=3)
    positions_data = [
        ("0xTrader0", "LONG", Decimal("100"), Decimal("0.5"), now - timedelta(hours=10)),
        ("0xTrader1", "LONG", Decimal("200"), Decimal("0.5"), now - timedelta(hours=8)),
    ]

    for trader_address, direction, size, price, entry_time in positions_data:
        position = Position(
            market_id="0xMarket2",
            trader_address=trader_address,
            direction=direction,
            size=size,
            avg_entry_price=price,
            entry_timestamp=entry_time,
            last_trade_timestamp=entry_time,
            resolved=False,
        )
        session.add(position)

    # Create Q5 LiftScore rows for 2 traders
    for i in range(2):
        session.add(make_lift_score(f"0xTrader{i}", now, quintile=5))

    session.commit()

    # Test refresh_market_signal
    results = refresh_market_signal(session, "0xMarket2", min_experts=3, now=now)

    # Verify no consensus
    assert len(results) == 0

    # Verify no active SignalSnapshot created
    snapshots = session.query(SignalSnapshot).filter_by(market_id="0xMarket2", status="active").all()
    assert len(snapshots) == 0


def test_refresh_market_signal_signal_lost(session):
    """Test signal lost detection when experts exit/flip positions."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket3",
        question="Test Market 3",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders
    for i in range(3):
        trader = Trader(address=f"0xTrader{i}")
        session.add(trader)

    # First snapshot: 3 LONG experts
    positions_data = [
        ("0xTrader0", "LONG", Decimal("100"), Decimal("0.5"), now - timedelta(hours=10)),
        ("0xTrader1", "LONG", Decimal("200"), Decimal("0.5"), now - timedelta(hours=8)),
        ("0xTrader2", "LONG", Decimal("150"), Decimal("0.5"), now - timedelta(hours=6)),
    ]

    for trader_address, direction, size, price, entry_time in positions_data:
        position = Position(
            market_id="0xMarket3",
            trader_address=trader_address,
            direction=direction,
            size=size,
            avg_entry_price=price,
            entry_timestamp=entry_time,
            last_trade_timestamp=entry_time,
            resolved=False,
        )
        session.add(position)

    # Create Q5 LiftScore rows for 3 traders
    for i in range(3):
        session.add(make_lift_score(f"0xTrader{i}", now, quintile=5))

    session.commit()

    # First call: create active signal
    results1 = refresh_market_signal(session, "0xMarket3", min_experts=3, now=now - timedelta(hours=1))
    assert len(results1) == 1
    assert results1[0].status == "active"

    # Change positions: experts exit (set to FLAT)
    positions = session.query(Position).filter_by(market_id="0xMarket3").all()
    for position in positions:
        position.direction = "FLAT"
    session.commit()

    # Second call: should create inactive snapshot
    results2 = refresh_market_signal(session, "0xMarket3", min_experts=3, now=now)
    assert len(results2) == 0  # No active signals

    # Verify both snapshots exist in history (append-only)
    snapshots = session.query(SignalSnapshot).filter_by(market_id="0xMarket3").order_by(SignalSnapshot.computed_at).all()
    assert len(snapshots) == 2
    assert snapshots[0].status == "active"
    assert snapshots[0].confidence_score > 0
    assert snapshots[1].status == "inactive"
    assert snapshots[1].confidence_score == Decimal("0")


def test_refresh_market_signal_first_mover_tracked(session):
    """Test first-mover and follower classifications."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket4",
        question="Test Market 4",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders
    for i in range(3):
        trader = Trader(address=f"0xTrader{i}")
        session.add(trader)

    # Create positions with different entry timestamps
    positions_data = [
        ("0xTrader0", "LONG", Decimal("100"), Decimal("0.5"), now - timedelta(hours=10)),  # First
        ("0xTrader1", "LONG", Decimal("200"), Decimal("0.5"), now - timedelta(hours=8)),   # Fast follower
        ("0xTrader2", "LONG", Decimal("150"), Decimal("0.5"), now - timedelta(hours=6)),   # Fast follower
    ]

    for trader_address, direction, size, price, entry_time in positions_data:
        position = Position(
            market_id="0xMarket4",
            trader_address=trader_address,
            direction=direction,
            size=size,
            avg_entry_price=price,
            entry_timestamp=entry_time,
            last_trade_timestamp=entry_time,
            resolved=False,
        )
        session.add(position)

    # Create Q5 LiftScore rows for 3 traders
    for i in range(3):
        session.add(make_lift_score(f"0xTrader{i}", now, quintile=5))

    session.commit()

    # Test refresh_market_signal
    results = refresh_market_signal(session, "0xMarket4", min_experts=3, now=now)

    # Verify first mover
    assert len(results) == 1
    result = results[0]
    assert result.first_mover_address == "0xTrader0"  # Earliest entry

    # Verify follower classifications
    assert result.follower_classifications["0xTrader0"] == "first_mover"
    assert result.follower_classifications["0xTrader1"] == "fast_follower"  # Within 6 hours
    assert result.follower_classifications["0xTrader2"] == "fast_follower"  # Within 6 hours


def test_refresh_market_signal_herding_stub(session):
    """Test that herding_status is always 'not_analyzed'."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket5",
        question="Test Market 5",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders and positions (3 LONG experts)
    for i in range(3):
        trader = Trader(address=f"0xTrader{i}")
        session.add(trader)

        position = Position(
            market_id="0xMarket5",
            trader_address=f"0xTrader{i}",
            direction="LONG",
            size=Decimal("100"),
            avg_entry_price=Decimal("0.5"),
            entry_timestamp=now - timedelta(hours=10 - i),
            last_trade_timestamp=now - timedelta(hours=10 - i),
            resolved=False,
        )
        session.add(position)

        session.add(make_lift_score(f"0xTrader{i}", now, quintile=5))

    session.commit()

    # Test refresh_market_signal
    results = refresh_market_signal(session, "0xMarket5", min_experts=3, now=now)

    # Verify herding_status is stub value
    assert len(results) == 1
    assert results[0].herding_status == "not_analyzed"


def test_refresh_all_signals_batch(session):
    """Test batch processing of multiple markets."""
    now = datetime.now(UTC)

    # Create 3 markets: 2 with expert consensus, 1 without
    markets_data = [
        ("0xMarket6", 3),  # 3 LONG experts -> consensus
        ("0xMarket7", 3),  # 3 SHORT experts -> consensus
        ("0xMarket8", 2),  # 2 LONG experts -> no consensus
    ]

    for market_id, num_experts in markets_data:
        market = Market(
            condition_id=market_id,
            question=f"Test {market_id}",
            end_date=now + timedelta(days=1),
            category="esports",
        )
        session.add(market)

        # Create traders and positions
        direction = "LONG" if market_id != "0xMarket7" else "SHORT"
        for i in range(num_experts):
            trader_address = f"{market_id}_Trader{i}"
            trader = Trader(address=trader_address)
            session.add(trader)

            position = Position(
                market_id=market_id,
                trader_address=trader_address,
                direction=direction,
                size=Decimal("100"),
                avg_entry_price=Decimal("0.5"),
                entry_timestamp=now - timedelta(hours=5),
                last_trade_timestamp=now - timedelta(hours=5),
                resolved=False,
            )
            session.add(position)

            session.add(make_lift_score(trader_address, now, quintile=5))

    session.commit()

    # Test refresh_all_signals
    results = refresh_all_signals(session, window_hours=24, min_experts=3, now=now)

    # Verify: 2 signals (Market6 LONG, Market7 SHORT)
    assert len(results) == 2

    # Verify sorted by confidence DESC
    assert results[0].confidence_score >= results[1].confidence_score

    # Verify both consensus signals present
    market_ids = {r.market_id for r in results}
    assert market_ids == {"0xMarket6", "0xMarket7"}


def test_refresh_all_signals_window_filter(session):
    """Test time-window filtering for expert activity."""
    now = datetime.now(UTC)

    # Create 2 markets: 1 with recent activity, 1 with old activity
    markets_data = [
        ("0xMarket9", now - timedelta(minutes=30)),   # Recent (within 1 hour)
        ("0xMarket10", now - timedelta(hours=5)),     # Old (outside 1 hour)
    ]

    for market_id, last_trade_time in markets_data:
        market = Market(
            condition_id=market_id,
            question=f"Test {market_id}",
            end_date=now + timedelta(days=1),
            category="esports",
        )
        session.add(market)

        # Create 3 LONG experts
        for i in range(3):
            trader_address = f"{market_id}_Trader{i}"
            trader = Trader(address=trader_address)
            session.add(trader)

            position = Position(
                market_id=market_id,
                trader_address=trader_address,
                direction="LONG",
                size=Decimal("100"),
                avg_entry_price=Decimal("0.5"),
                entry_timestamp=last_trade_time,
                last_trade_timestamp=last_trade_time,
                resolved=False,
            )
            session.add(position)

            session.add(make_lift_score(trader_address, now, quintile=5))

    session.commit()

    # Test with 1-hour window
    results = refresh_all_signals(session, window_hours=1, min_experts=3, now=now)

    # Verify only Market9 processed (recent activity)
    assert len(results) == 1
    assert results[0].market_id == "0xMarket9"


def test_get_ranked_signals_returns_active(session):
    """Test that get_ranked_signals returns only active signals."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket11",
        question="Test Market 11",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create active and inactive snapshots
    active_snapshot = SignalSnapshot(
        market_id="0xMarket11",
        direction="LONG",
        confidence_score=Decimal("80"),
        expert_count=3,
        total_experts_in_market=3,
        agreement_percentage=Decimal("100"),
        expert_addresses_json="0xA,0xB,0xC",
        first_mover_address="0xA",
        status="active",
        computed_at=now - timedelta(hours=1),
    )
    session.add(active_snapshot)

    inactive_snapshot = SignalSnapshot(
        market_id="0xMarket11",
        direction="SHORT",
        confidence_score=Decimal("0"),
        expert_count=0,
        total_experts_in_market=0,
        agreement_percentage=Decimal("0"),
        expert_addresses_json="",
        first_mover_address=None,
        status="inactive",
        computed_at=now,
    )
    session.add(inactive_snapshot)

    session.commit()

    # Test get_ranked_signals
    results = get_ranked_signals(session)

    # Verify only active signal returned
    assert len(results) == 1
    assert results[0].status == "active"
    assert results[0].direction == "LONG"


def test_get_ranked_signals_time_window(session):
    """Test time-window filtering for get_ranked_signals."""
    now = datetime.now(UTC)

    # Create 2 markets with signals
    markets_data = [
        ("0xMarket12", now - timedelta(minutes=30)),  # Recent activity
        ("0xMarket13", now - timedelta(hours=5)),     # Old activity
    ]

    for market_id, last_trade_time in markets_data:
        market = Market(
            condition_id=market_id,
            question=f"Test {market_id}",
            end_date=now + timedelta(days=1),
            category="esports",
        )
        session.add(market)

        # Create signal snapshot
        snapshot = SignalSnapshot(
            market_id=market_id,
            direction="LONG",
            confidence_score=Decimal("80"),
            expert_count=3,
            total_experts_in_market=3,
            agreement_percentage=Decimal("100"),
            expert_addresses_json="0xA,0xB,0xC",
            first_mover_address="0xA",
            status="active",
            computed_at=now - timedelta(minutes=10),
        )
        session.add(snapshot)

        # Create positions with appropriate timestamps
        for i in range(3):
            trader_address = f"{market_id}_Trader{i}"
            trader = Trader(address=trader_address)
            session.add(trader)

            position = Position(
                market_id=market_id,
                trader_address=trader_address,
                direction="LONG",
                size=Decimal("100"),
                avg_entry_price=Decimal("0.5"),
                entry_timestamp=last_trade_time,
                last_trade_timestamp=last_trade_time,
                resolved=False,
            )
            session.add(position)

            session.add(make_lift_score(trader_address, now, quintile=5))

    session.commit()

    # Test with 1-hour window
    results = get_ranked_signals(session, window_hours=1)

    # Verify only Market12 returned (recent activity)
    assert len(results) == 1
    assert results[0].market_id == "0xMarket12"


def test_get_ranked_signals_min_confidence(session):
    """Test min_confidence filter for get_ranked_signals."""
    now = datetime.now(UTC)

    # Create 2 markets with different confidence scores
    signals_data = [
        ("0xMarket14", Decimal("85")),  # High confidence
        ("0xMarket15", Decimal("65")),  # Lower confidence
    ]

    for market_id, confidence in signals_data:
        market = Market(
            condition_id=market_id,
            question=f"Test {market_id}",
            end_date=now + timedelta(days=1),
            category="esports",
        )
        session.add(market)

        snapshot = SignalSnapshot(
            market_id=market_id,
            direction="LONG",
            confidence_score=confidence,
            expert_count=3,
            total_experts_in_market=3,
            agreement_percentage=Decimal("100"),
            expert_addresses_json="0xA,0xB,0xC",
            first_mover_address="0xA",
            status="active",
            computed_at=now,
        )
        session.add(snapshot)

    session.commit()

    # Test with min_confidence=80
    results = get_ranked_signals(session, min_confidence=Decimal("80"))

    # Verify only high confidence signal returned
    assert len(results) == 1
    assert results[0].market_id == "0xMarket14"
    assert results[0].confidence_score >= Decimal("80")


def test_signal_snapshot_append_only(session):
    """Test that signal snapshots are append-only (not updated)."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket16",
        question="Test Market 16",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders and positions
    for i in range(3):
        trader = Trader(address=f"0xTrader{i}")
        session.add(trader)

        position = Position(
            market_id="0xMarket16",
            trader_address=f"0xTrader{i}",
            direction="LONG",
            size=Decimal("100"),
            avg_entry_price=Decimal("0.5"),
            entry_timestamp=now - timedelta(hours=10),
            last_trade_timestamp=now - timedelta(hours=10),
            resolved=False,
        )
        session.add(position)

        session.add(make_lift_score(f"0xTrader{i}", now, quintile=5))

    session.commit()

    # Call refresh_market_signal twice
    refresh_market_signal(session, "0xMarket16", min_experts=3, now=now - timedelta(hours=1))
    refresh_market_signal(session, "0xMarket16", min_experts=3, now=now)

    # Verify 2 snapshots exist (not 1 updated)
    snapshots = session.query(SignalSnapshot).filter_by(market_id="0xMarket16").all()
    assert len(snapshots) == 2
    assert snapshots[0].computed_at != snapshots[1].computed_at


def test_excludes_non_expert_positions(session):
    """Test that non-experts (score <70) don't count toward consensus."""
    now = datetime.now(UTC)

    # Create market
    market = Market(
        condition_id="0xMarket17",
        question="Test Market 17",
        end_date=now + timedelta(days=1),
        category="esports",
    )
    session.add(market)

    # Create traders: 3 LONG Q5 experts + 2 LONG non-experts (Q3)
    positions_data = [
        ("0xExpert0", "LONG", 5),    # Q5 expert
        ("0xExpert1", "LONG", 5),    # Q5 expert
        ("0xExpert2", "LONG", 5),    # Q5 expert
        ("0xNonExpert0", "LONG", 3),  # Q3 non-expert
        ("0xNonExpert1", "LONG", 3),  # Q3 non-expert
    ]

    for trader_address, direction, quintile in positions_data:
        trader = Trader(address=trader_address)
        session.add(trader)

        position = Position(
            market_id="0xMarket17",
            trader_address=trader_address,
            direction=direction,
            size=Decimal("100"),
            avg_entry_price=Decimal("0.5"),
            entry_timestamp=now - timedelta(hours=10),
            last_trade_timestamp=now - timedelta(hours=10),
            resolved=False,
        )
        session.add(position)

        session.add(make_lift_score(trader_address, now, quintile=quintile))

    session.commit()

    # Test refresh_market_signal
    results = refresh_market_signal(session, "0xMarket17", min_experts=3, now=now)

    # Verify only experts counted
    assert len(results) == 1
    assert results[0].expert_count == 3
    assert results[0].total_experts_in_market == 3  # Only experts count in denominator
    assert len(results[0].expert_addresses) == 3
    assert all("Expert" in addr for addr in results[0].expert_addresses)


def test_assess_herding_returns_not_analyzed(session):
    """Test that assess_herding always returns 'not_analyzed'."""
    now = datetime.now(UTC)

    # Create dummy SignalResult
    signal = SignalResult(
        market_id="0xMarket18",
        direction="LONG",
        confidence_score=Decimal("80"),
        expert_count=3,
        total_experts_in_market=3,
        agreement_percentage=Decimal("100"),
        expert_addresses=["0xA", "0xB", "0xC"],
        first_mover_address="0xA",
        follower_classifications={"0xA": "first_mover", "0xB": "fast_follower"},
        herding_status="not_analyzed",
        status="active",
        computed_at=now,
        expert_avg_entry=None,
    )

    # Test assess_herding
    result = assess_herding(signal)

    # Verify stub behavior
    assert result == "not_analyzed"
