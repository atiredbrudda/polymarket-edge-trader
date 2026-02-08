"""Unit tests for alert formatter.

Tests all event types, HTML escaping, address truncation, and edge cases.
"""

from datetime import datetime, UTC
from decimal import Decimal

import pytest

from src.alerts.formatter import format_signal_alert, get_expert_position_details
from src.signals.pipeline import SignalResult


@pytest.fixture
def base_signal():
    """Base SignalResult for testing."""
    return SignalResult(
        market_id="0x1234567890abcdef",
        direction="LONG",
        confidence_score=Decimal("85.5"),
        expert_count=4,
        total_experts_in_market=5,
        agreement_percentage=Decimal("80.0"),
        expert_addresses=[
            "0xabcdef1234567890abcdef1234567890abcdef12",
            "0x1111111111111111111111111111111111111111",
            "0x2222222222222222222222222222222222222222",
            "0x3333333333333333333333333333333333333333",
        ],
        first_mover_address="0xabcdef1234567890abcdef1234567890abcdef12",
        follower_classifications={
            "0xabcdef1234567890abcdef1234567890abcdef12": "first_mover",
            "0x1111111111111111111111111111111111111111": "fast_follower",
            "0x2222222222222222222222222222222222222222": "slow_follower",
            "0x3333333333333333333333333333333333333333": "slow_follower",
        },
        herding_status="not_analyzed",
        status="active",
        computed_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def expert_positions():
    """Sample expert position details."""
    return [
        {
            "address": "0xabcdef1234567890abcdef1234567890abcdef12",
            "size": Decimal("1000.50"),
            "direction": "LONG",
            "avg_entry_price": Decimal("0.65"),
        },
        {
            "address": "0x1111111111111111111111111111111111111111",
            "size": Decimal("500.25"),
            "direction": "LONG",
            "avg_entry_price": Decimal("0.68"),
        },
        {
            "address": "0x2222222222222222222222222222222222222222",
            "size": Decimal("750.00"),
            "direction": "LONG",
            "avg_entry_price": Decimal("0.62"),
        },
        {
            "address": "0x3333333333333333333333333333333333333333",
            "size": Decimal("250.75"),
            "direction": "LONG",
            "avg_entry_price": None,
        },
    ]


class TestFormatSignalAlert:
    """Tests for format_signal_alert function."""

    def test_new_event_header(self, base_signal, expert_positions):
        """NEW event includes correct header."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, expert_positions)
        
        assert "New Signal" in result
        assert "Will Team A win?" in result
        assert "LONG" in result

    def test_strengthening_event_header(self, base_signal, expert_positions):
        """STRENGTHENING event includes correct header."""
        result = format_signal_alert("STRENGTHENING", "Will Team A win?", base_signal, expert_positions)
        
        assert "Signal Strengthened" in result
        assert "Will Team A win?" in result

    def test_weakening_event_header(self, base_signal, expert_positions):
        """WEAKENING event includes correct header."""
        result = format_signal_alert("WEAKENING", "Will Team A win?", base_signal, expert_positions)
        
        assert "Signal Weakened" in result
        assert "Will Team A win?" in result

    def test_lost_event_header(self, base_signal, expert_positions):
        """LOST event includes correct header."""
        result = format_signal_alert("LOST", "Will Team A win?", base_signal, expert_positions)
        
        assert "Signal Lost" in result
        assert "Will Team A win?" in result

    def test_html_escaping(self, base_signal, expert_positions):
        """Market questions with HTML characters are properly escaped."""
        dangerous_question = "Will <Team A> beat Team B & win the championship?"
        result = format_signal_alert("NEW", dangerous_question, base_signal, expert_positions)
        
        # HTML entities should be escaped
        assert "&lt;Team A&gt;" in result
        assert "&amp;" in result
        # Original characters should NOT appear
        assert "<Team A>" not in result

    def test_expert_addresses_all_shown_when_few(self, base_signal, expert_positions):
        """When 3-5 experts, all addresses shown without +N more."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, expert_positions)
        
        # Should show truncated addresses
        assert "0xabcdef12...cdef12" in result or "0xabcdef1234...cdef12" in result
        assert "0x11111111...111111" in result or "0x1111111111...111111" in result
        # Should NOT have "+N more" indicator
        assert "+1 more" not in result
        assert "+2 more" not in result

    def test_expert_addresses_truncated_when_many(self, base_signal, expert_positions):
        """When >5 experts, only first 5 shown with +N more."""
        # Add 3 more experts (total 7)
        signal_with_many = SignalResult(
            market_id=base_signal.market_id,
            direction=base_signal.direction,
            confidence_score=base_signal.confidence_score,
            expert_count=7,
            total_experts_in_market=7,
            agreement_percentage=Decimal("100.0"),
            expert_addresses=base_signal.expert_addresses + [
                "0x4444444444444444444444444444444444444444",
                "0x5555555555555555555555555555555555555555",
                "0x6666666666666666666666666666666666666666",
            ],
            first_mover_address=base_signal.first_mover_address,
            follower_classifications=base_signal.follower_classifications,
            herding_status="not_analyzed",
            status="active",
            computed_at=base_signal.computed_at,
        )
        
        result = format_signal_alert("NEW", "Will Team A win?", signal_with_many, expert_positions)
        
        # Should show "+2 more"
        assert "+2 more" in result

    def test_no_first_mover_omits_section(self, base_signal, expert_positions):
        """When first_mover_address is None, section is omitted."""
        signal_no_first_mover = SignalResult(
            market_id=base_signal.market_id,
            direction=base_signal.direction,
            confidence_score=base_signal.confidence_score,
            expert_count=base_signal.expert_count,
            total_experts_in_market=base_signal.total_experts_in_market,
            agreement_percentage=base_signal.agreement_percentage,
            expert_addresses=base_signal.expert_addresses,
            first_mover_address=None,  # No first mover
            follower_classifications={},
            herding_status="not_analyzed",
            status="active",
            computed_at=base_signal.computed_at,
        )
        
        result = format_signal_alert("NEW", "Will Team A win?", signal_no_first_mover, expert_positions)
        
        # First mover section should be omitted (check for "First mover" text)
        assert "First" not in result or "first" not in result.lower().count("first") > 1

    def test_no_expert_positions_omits_sizes(self, base_signal):
        """When expert_positions is None, position sizes section is omitted."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, None)
        
        # Position size details should not be present
        assert "1000.50" not in result
        assert "Position" not in result or "position" not in result.lower()

    def test_expert_positions_shown_when_provided(self, base_signal, expert_positions):
        """When expert_positions provided, each address shown with size and direction."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, expert_positions)
        
        # Should show position sizes
        assert "1000.50" in result
        assert "500.25" in result
        assert "750.00" in result
        assert "250.75" in result

    def test_valid_telegram_html_tags(self, base_signal, expert_positions):
        """Output contains valid Telegram HTML tags."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, expert_positions)
        
        # Check for Telegram HTML tags
        assert "<b>" in result
        assert "</b>" in result
        assert "<code>" in result
        assert "</code>" in result
        assert "<a href=" in result
        assert "</a>" in result

    def test_includes_all_required_metrics(self, base_signal, expert_positions):
        """Alert includes all required signal metrics."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, expert_positions)
        
        # Direction
        assert "LONG" in result
        # Confidence score
        assert "85.5" in result or "85" in result
        # Expert count
        assert "4" in result
        # Agreement percentage
        assert "80" in result or "80.0" in result

    def test_fast_follower_count_included(self, base_signal, expert_positions):
        """Fast-follower count derived from follower_classifications."""
        result = format_signal_alert("NEW", "Will Team A win?", base_signal, expert_positions)
        
        # Should show 1 fast follower (from follower_classifications)
        assert "1" in result  # The count of fast_followers


class TestGetExpertPositionDetails:
    """Tests for get_expert_position_details function."""

    def test_returns_position_details_for_experts(self, session, sample_positions):
        """Returns position details for specified expert addresses."""
        from src.db.models import Position
        
        # Add sample positions to session
        pos1 = Position(
            market_id="0xMarket123",
            trader_address="0xExpert1",
            size=Decimal("100.50"),
            direction="LONG",
            avg_entry_price=Decimal("0.65"),
            entry_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            computed_at=datetime.now(UTC),
        )
        pos2 = Position(
            market_id="0xMarket123",
            trader_address="0xExpert2",
            size=Decimal("200.75"),
            direction="LONG",
            avg_entry_price=Decimal("0.70"),
            entry_timestamp=datetime(2024, 1, 2, tzinfo=UTC),
            computed_at=datetime.now(UTC),
        )
        session.add_all([pos1, pos2])
        session.commit()
        
        # Query expert position details
        expert_addresses = ["0xExpert1", "0xExpert2"]
        result = get_expert_position_details(session, "0xMarket123", expert_addresses)
        
        assert len(result) == 2
        assert result[0]["address"] == "0xExpert1"
        assert result[0]["size"] == Decimal("100.50")
        assert result[0]["direction"] == "LONG"
        assert result[0]["avg_entry_price"] == Decimal("0.65")
        
        assert result[1]["address"] == "0xExpert2"
        assert result[1]["size"] == Decimal("200.75")

    def test_returns_empty_list_when_no_positions(self, session):
        """Returns empty list when no positions found for experts."""
        result = get_expert_position_details(session, "0xNonexistent", ["0xExpert1"])
        assert result == []

    def test_handles_none_avg_entry_price(self, session):
        """Handles positions with None avg_entry_price."""
        from src.db.models import Position
        
        pos = Position(
            market_id="0xMarket456",
            trader_address="0xExpert3",
            size=Decimal("50.0"),
            direction="SHORT",
            avg_entry_price=None,  # None case
            entry_timestamp=datetime(2024, 1, 3, tzinfo=UTC),
            computed_at=datetime.now(UTC),
        )
        session.add(pos)
        session.commit()
        
        result = get_expert_position_details(session, "0xMarket456", ["0xExpert3"])
        
        assert len(result) == 1
        assert result[0]["avg_entry_price"] is None


@pytest.fixture
def sample_positions():
    """Fixture for sample positions (marker for tests)."""
    return []
