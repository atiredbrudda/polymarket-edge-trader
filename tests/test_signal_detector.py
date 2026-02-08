"""Unit tests for signal event detection logic.

Tests all event type transitions and edge cases:
- NEW: First active snapshot or inactive -> active
- STRENGTHENING: Confidence increase >= 5 points
- WEAKENING: Confidence decrease >= 5 points
- LOST: Active -> inactive
- None: Confidence change < 5 points (noise filtering)
"""

from datetime import datetime, UTC
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, SignalSnapshot
from src.alerts.detector import detect_signal_event


@pytest.fixture
def session():
    """Create in-memory database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def create_snapshot(
    session: Session,
    market_id: str,
    direction: str,
    status: str,
    confidence: Decimal,
    computed_at: datetime,
) -> SignalSnapshot:
    """Helper to create a SignalSnapshot for testing."""
    snapshot = SignalSnapshot(
        market_id=market_id,
        direction=direction,
        status=status,
        confidence_score=confidence,
        expert_count=5,
        total_experts_in_market=6,
        agreement_percentage=Decimal("83.33"),
        expert_addresses_json='["0xA", "0xB", "0xC", "0xD", "0xE"]',
        first_mover_address="0xA",
        computed_at=computed_at,
    )
    session.add(snapshot)
    session.commit()
    return snapshot


def test_new_event_first_active_snapshot(session):
    """Test NEW event when first snapshot is active."""
    market_id = "0xMarket1"
    direction = "LONG"

    # Create single active snapshot
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("75"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "NEW"


def test_none_event_first_inactive_snapshot(session):
    """Test None when first snapshot is inactive."""
    market_id = "0xMarket2"
    direction = "LONG"

    # Create single inactive snapshot
    create_snapshot(
        session,
        market_id,
        direction,
        status="inactive",
        confidence=Decimal("0"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result is None


def test_new_event_inactive_to_active(session):
    """Test NEW event when previous inactive becomes active (re-emergence)."""
    market_id = "0xMarket3"
    direction = "LONG"

    # Previous inactive
    create_snapshot(
        session,
        market_id,
        direction,
        status="inactive",
        confidence=Decimal("0"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("76"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "NEW"


def test_lost_event_active_to_inactive(session):
    """Test LOST event when previous active becomes inactive."""
    market_id = "0xMarket4"
    direction = "SHORT"

    # Previous active
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("72"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest inactive
    create_snapshot(
        session,
        market_id,
        direction,
        status="inactive",
        confidence=Decimal("0"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "LOST"


def test_strengthening_event_confidence_increase_above_threshold(session):
    """Test STRENGTHENING event when confidence increases >= 5 points."""
    market_id = "0xMarket5"
    direction = "LONG"

    # Previous active with 60 confidence
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("60"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active with 66 confidence (delta = +6)
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("66"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "STRENGTHENING"


def test_weakening_event_confidence_decrease_above_threshold(session):
    """Test WEAKENING event when confidence decreases >= 5 points."""
    market_id = "0xMarket6"
    direction = "SHORT"

    # Previous active with 60 confidence
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("60"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active with 53 confidence (delta = -7)
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("53"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "WEAKENING"


def test_none_event_confidence_increase_below_threshold(session):
    """Test None when confidence increases < 5 points (noise)."""
    market_id = "0xMarket7"
    direction = "LONG"

    # Previous active with 60 confidence
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("60"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active with 63 confidence (delta = +3, < 5)
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("63"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result is None


def test_none_event_confidence_decrease_below_threshold(session):
    """Test None when confidence decreases < 5 points (noise)."""
    market_id = "0xMarket8"
    direction = "SHORT"

    # Previous active with 60 confidence
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("60"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active with 57 confidence (delta = -3, > -5)
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("57"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result is None


def test_strengthening_event_exactly_threshold(session):
    """Test STRENGTHENING event when confidence increases exactly 5 points."""
    market_id = "0xMarket9"
    direction = "LONG"

    # Previous active with 60 confidence
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("60"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active with 65 confidence (delta = +5, exactly threshold)
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("65"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "STRENGTHENING"


def test_weakening_event_exactly_threshold(session):
    """Test WEAKENING event when confidence decreases exactly 5 points."""
    market_id = "0xMarket10"
    direction = "SHORT"

    # Previous active with 60 confidence
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("60"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest active with 55 confidence (delta = -5, exactly threshold)
    create_snapshot(
        session,
        market_id,
        direction,
        status="active",
        confidence=Decimal("55"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result == "WEAKENING"


def test_none_event_no_history(session):
    """Test None when no signal history exists for market+direction."""
    market_id = "0xMarketNonExistent"
    direction = "LONG"

    result = detect_signal_event(session, market_id, direction)
    assert result is None


def test_none_event_inactive_to_inactive(session):
    """Test None when both snapshots are inactive (no change)."""
    market_id = "0xMarket12"
    direction = "LONG"

    # Previous inactive
    create_snapshot(
        session,
        market_id,
        direction,
        status="inactive",
        confidence=Decimal("0"),
        computed_at=datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC),
    )

    # Latest inactive
    create_snapshot(
        session,
        market_id,
        direction,
        status="inactive",
        confidence=Decimal("0"),
        computed_at=datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )

    result = detect_signal_event(session, market_id, direction)
    assert result is None
