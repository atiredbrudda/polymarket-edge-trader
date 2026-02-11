"""Integration tests for alert delivery pipeline with mocked Telegram bot.

Tests cover:
- End-to-end delivery pipeline orchestration
- In-memory TTL-based deduplication
- Failure handling (log and continue, don't block pipeline)
- Integration with detector, formatter, and signal pipeline
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Market, Trader, Position, Trade, ExpertiseScore, SignalSnapshot
from src.alerts.delivery import (
    deliver_signal_alerts,
    AlertDeliveryResult,
    AlertDeduplicator,
)
from src.alerts.telegram import TelegramAlerter


@pytest.fixture
def engine():
    """Create in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create database session for testing."""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def mock_alerter():
    """Create mocked TelegramAlerter."""
    alerter = MagicMock(spec=TelegramAlerter)
    alerter.send = MagicMock()
    return alerter


@pytest.fixture
def sample_market(session):
    """Create a sample market for testing."""
    market = Market(
        condition_id="0xmarket1",
        question="Will Team A beat Team B?",
        category="eSports",
        active=True,
        end_date=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(market)
    session.commit()
    return market


@pytest.fixture
def sample_trader(session):
    """Create a sample expert trader."""
    trader = Trader(address="0xexpert1")
    session.add(trader)
    session.commit()
    return trader


@pytest.fixture
def sample_expertise_score(session, sample_trader):
    """Create expertise score for trader (makes them an expert)."""
    score = ExpertiseScore(
        trader_address=sample_trader.address,
        game_slug="esports",
        raw_score=Decimal("75.0"),  # > 70 threshold
        percentile_rank=Decimal("85.0"),
        win_rate_component=Decimal("30.0"),
        concentration_component=Decimal("20.0"),
        recency_component=Decimal("15.0"),
        sample_size_component=Decimal("10.0"),
        consistency_multiplier=Decimal("1.0"),
        specialization_label="specialist",
        resolved_market_count=10,
        computed_at=datetime.now(UTC),
    )
    session.add(score)
    session.commit()
    return score


@pytest.fixture
def sample_position(session, sample_market, sample_trader):
    """Create a sample position."""
    position = Position(
        trader_address=sample_trader.address,
        market_id=sample_market.condition_id,
        direction="LONG",
        size=Decimal("100.0"),
        avg_entry_price=Decimal("0.55"),
        last_trade_timestamp=datetime.now(UTC),
    )
    session.add(position)
    session.commit()
    return position


@pytest.fixture
def sample_signal(session, sample_market, sample_trader, sample_position):
    """Create a NEW signal snapshot (no previous snapshot exists)."""
    signal = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        total_experts_in_market=4,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address="0xexpert1",
        expert_addresses_json="0xexpert1,0xexpert2,0xexpert3",
        computed_at=datetime.now(UTC),
        status="active",
    )
    session.add(signal)
    session.commit()
    return signal


def test_deliver_signal_alerts_returns_empty_list_when_no_signals(session, mock_alerter):
    """Test that deliver_signal_alerts returns empty list when no signals exist."""
    results = deliver_signal_alerts(session, mock_alerter, window_hours=24)

    assert results == []
    mock_alerter.send.assert_not_called()


def test_deliver_signal_alerts_sends_alert_for_new_signal_event(
    session, mock_alerter, sample_market, sample_trader, sample_expertise_score, sample_position
):
    """Test that deliver_signal_alerts sends alert for NEW signal event."""
    # Create a NEW signal (no previous snapshot)
    signal = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=datetime.now(UTC),
        status="active",
    )
    session.add(signal)
    session.commit()

    results = deliver_signal_alerts(session, mock_alerter, window_hours=24)

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].market_id == sample_market.condition_id
    assert results[0].direction == "LONG"
    assert results[0].event_type == "NEW"
    assert results[0].error is None
    mock_alerter.send.assert_called_once()


def test_deliver_signal_alerts_skips_when_no_event_detected(
    session, mock_alerter, sample_market, sample_trader, sample_expertise_score, sample_position
):
    """Test that deliver_signal_alerts skips when detect_signal_event returns None."""
    # Create two identical signals (no change = no event)
    now = datetime.now(UTC)
    signal1 = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=now - timedelta(hours=2),
        status="active",
    )
    signal2 = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=now,
        status="active",
    )
    session.add_all([signal1, signal2])
    session.commit()

    results = deliver_signal_alerts(session, mock_alerter, window_hours=24)

    assert results == []
    mock_alerter.send.assert_not_called()


def test_deliver_signal_alerts_continues_on_send_failure(
    session, mock_alerter, sample_market, sample_trader, sample_expertise_score, sample_position
):
    """Test that deliver_signal_alerts logs failure and continues on send error."""
    # Setup: Two NEW signals for different markets
    market2 = Market(
        condition_id="0xmarket2",
        question="Will Team C beat Team D?",
        category="eSports",
        active=True,
        end_date=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(market2)

    position2 = Position(
        trader_address=sample_trader.address,
        market_id=market2.condition_id,
        direction="LONG",
        size=Decimal("100.0"),
        avg_entry_price=Decimal("0.55"),
        last_trade_timestamp=datetime.now(UTC),
    )
    session.add(position2)
    session.commit()

    signal1 = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=datetime.now(UTC),
        status="active",
    )
    signal2 = SignalSnapshot(
        market_id=market2.condition_id,
        direction="LONG",
        expert_count=4,
        agreement_percentage=Decimal("90.0"),
        confidence_score=Decimal("82.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=5,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3,0xexpert4",
        computed_at=datetime.now(UTC),
        status="active",
    )
    session.add_all([signal1, signal2])
    session.commit()

    # Mock send to fail on first call, succeed on second
    mock_alerter.send.side_effect = [Exception("Network error"), None]

    results = deliver_signal_alerts(session, mock_alerter, window_hours=24)

    # Both signals processed, first failed, second succeeded
    assert len(results) == 2
    assert results[0].success is False
    assert results[0].error == "Network error"
    assert results[1].success is True
    assert results[1].error is None
    assert mock_alerter.send.call_count == 2


def test_alert_deduplicator_prevents_duplicate_sends(session, mock_alerter):
    """Test that AlertDeduplicator prevents duplicate sends within TTL."""
    dedup = AlertDeduplicator(ttl_minutes=60)

    market_id = "0xmarket1"
    direction = "LONG"
    event_type = "NEW"
    computed_at = datetime.now(UTC)

    # First check: should send
    assert dedup.should_send(market_id, direction, event_type, computed_at) is True

    # Second check (same parameters): should NOT send
    assert dedup.should_send(market_id, direction, event_type, computed_at) is False

    # Third check (same parameters): still should NOT send
    assert dedup.should_send(market_id, direction, event_type, computed_at) is False


def test_alert_deduplicator_allows_different_event_types(session, mock_alerter):
    """Test that AlertDeduplicator allows same market with different event types."""
    dedup = AlertDeduplicator(ttl_minutes=60)

    market_id = "0xmarket1"
    direction = "LONG"
    computed_at = datetime.now(UTC)

    # NEW event
    assert dedup.should_send(market_id, direction, "NEW", computed_at) is True
    assert dedup.should_send(market_id, direction, "NEW", computed_at) is False

    # STRENGTHENING event (different event type)
    assert dedup.should_send(market_id, direction, "STRENGTHENING", computed_at) is True
    assert dedup.should_send(market_id, direction, "STRENGTHENING", computed_at) is False


def test_alert_deduplicator_cleans_expired_entries(session, mock_alerter):
    """Test that AlertDeduplicator cleans expired entries after TTL."""
    dedup = AlertDeduplicator(ttl_minutes=1)  # 1 minute TTL

    market_id = "0xmarket1"
    direction = "LONG"
    event_type = "NEW"
    computed_at = datetime.now(UTC)

    # First check: should send
    assert dedup.should_send(market_id, direction, event_type, computed_at) is True
    assert dedup.should_send(market_id, direction, event_type, computed_at) is False

    # Simulate TTL expiration by manipulating cache timestamps
    # Set timestamp to 2 minutes ago
    key = (market_id, direction, event_type, computed_at.replace(second=0, microsecond=0))
    dedup._cache[key] = datetime.now(UTC) - timedelta(minutes=2)

    # After TTL expired: should send again
    assert dedup.should_send(market_id, direction, event_type, computed_at) is True


def test_deliver_signal_alerts_respects_deduplicator(
    session, mock_alerter, sample_market, sample_trader, sample_expertise_score, sample_position
):
    """Test that deliver_signal_alerts respects deduplicator."""
    dedup = AlertDeduplicator(ttl_minutes=60)

    signal = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=datetime.now(UTC),
        status="active",
    )
    session.add(signal)
    session.commit()

    # First delivery: should send
    results1 = deliver_signal_alerts(session, mock_alerter, deduplicator=dedup, window_hours=24)
    assert len(results1) == 1
    assert results1[0].success is True
    assert mock_alerter.send.call_count == 1

    # Second delivery (same signal): should skip due to deduplication
    results2 = deliver_signal_alerts(session, mock_alerter, deduplicator=dedup, window_hours=24)
    assert len(results2) == 0
    assert mock_alerter.send.call_count == 1  # No additional calls


def test_alert_delivery_result_captures_success_state(session, mock_alerter):
    """Test that AlertDeliveryResult captures success/failure state correctly."""
    result_success = AlertDeliveryResult(
        success=True,
        market_id="0xmarket1",
        direction="LONG",
        event_type="NEW",
        error=None,
    )

    result_failure = AlertDeliveryResult(
        success=False,
        market_id="0xmarket2",
        direction="SHORT",
        event_type="STRENGTHENING",
        error="Network timeout",
    )

    assert result_success.success is True
    assert result_success.error is None
    assert result_failure.success is False
    assert result_failure.error == "Network timeout"


def test_full_pipeline_signal_refresh_to_delivery(
    session, mock_alerter, sample_market, sample_trader, sample_expertise_score, sample_position
):
    """Test full pipeline: signal refresh -> event detection -> format -> mock send."""
    # Create a NEW signal (simulating signal refresh)
    signal = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=datetime.now(UTC),
        status="active",
    )
    session.add(signal)
    session.commit()

    # Deliver alerts
    results = deliver_signal_alerts(session, mock_alerter, window_hours=24)

    # Verify end-to-end flow
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].event_type == "NEW"
    assert mock_alerter.send.call_count == 1

    # Verify message was formatted correctly (HTML content)
    call_args = mock_alerter.send.call_args
    message = call_args[0][0]
    assert "New Signal" in message
    assert sample_market.question in message
    assert "LONG" in message
    assert "85.000000%" in message  # agreement_percentage


def test_deliver_signal_alerts_handles_missing_market(
    session, mock_alerter, sample_market, sample_trader, sample_expertise_score, sample_position
):
    """Test that deliver_signal_alerts handles missing market gracefully."""
    # Create signal with market that exists, then delete it
    signal = SignalSnapshot(
        market_id=sample_market.condition_id,
        direction="LONG",
        expert_count=3,
        agreement_percentage=Decimal("85.0"),
        confidence_score=Decimal("78.0"),
        first_mover_address=sample_trader.address,
        total_experts_in_market=4,
        expert_addresses_json=f"{sample_trader.address},0xexpert2,0xexpert3",
        computed_at=datetime.now(UTC),
        status="active",
    )
    session.add(signal)
    session.commit()

    # Delete the market to simulate missing market condition
    session.delete(sample_market)
    session.commit()

    results = deliver_signal_alerts(session, mock_alerter, window_hours=24)

    # Should return failure result, not crash
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "Market not found"
    mock_alerter.send.assert_not_called()
