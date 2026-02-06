"""
Tests for trader profile classification.
"""

import pytest
from dataclasses import dataclass


# Mock position object for testing
@dataclass
class MockPosition:
    market_id: str
    trader_address: str


def test_trader_profile_dataclass():
    """Test TraderProfile dataclass structure."""
    from src.evaluation.profiles import TraderProfile

    profile = TraderProfile(
        trader_address="0xabc",
        profile_type="selective",
        unique_markets=5,
        total_trades=20,
        threshold_used=10,
    )

    assert profile.trader_address == "0xabc"
    assert profile.profile_type == "selective"
    assert profile.unique_markets == 5
    assert profile.total_trades == 20
    assert profile.threshold_used == 10

    # Test frozen (immutable)
    with pytest.raises(Exception):  # FrozenInstanceError in dataclass
        profile.profile_type = "active"


def test_classify_trader_profile_selective():
    """Test classify_trader_profile returns 'selective' for traders below threshold."""
    from src.evaluation.profiles import classify_trader_profile

    positions = [
        MockPosition("market1", "0xabc"),
        MockPosition("market2", "0xabc"),
    ]

    profile = classify_trader_profile(positions, "0xabc", threshold=10)

    assert profile.trader_address == "0xabc"
    assert profile.profile_type == "selective"
    assert profile.unique_markets == 2
    assert profile.total_trades == 2
    assert profile.threshold_used == 10


def test_classify_trader_profile_active():
    """Test classify_trader_profile returns 'active' for traders at or above threshold."""
    from src.evaluation.profiles import classify_trader_profile

    positions = [
        MockPosition(f"market{i}", "0xabc")
        for i in range(15)  # 15 unique markets
    ]

    profile = classify_trader_profile(positions, "0xabc", threshold=10)

    assert profile.trader_address == "0xabc"
    assert profile.profile_type == "active"
    assert profile.unique_markets == 15
    assert profile.total_trades == 15
    assert profile.threshold_used == 10


def test_classify_trader_profile_boundary():
    """Test classify_trader_profile at exact threshold (10 markets = active)."""
    from src.evaluation.profiles import classify_trader_profile

    positions = [
        MockPosition(f"market{i}", "0xabc")
        for i in range(10)  # Exactly 10 unique markets
    ]

    profile = classify_trader_profile(positions, "0xabc", threshold=10)

    assert profile.trader_address == "0xabc"
    assert profile.profile_type == "active"  # At boundary = active
    assert profile.unique_markets == 10
    assert profile.threshold_used == 10


def test_classify_trader_profile_many_trades_few_markets():
    """Test classify_trader_profile uses unique markets, not trade count."""
    from src.evaluation.profiles import classify_trader_profile

    # 50 trades but only 3 unique markets (many trades per market)
    positions = [
        MockPosition("market1", "0xabc"),
        MockPosition("market1", "0xabc"),  # Duplicate
        MockPosition("market1", "0xabc"),  # Duplicate
        MockPosition("market2", "0xabc"),
        MockPosition("market2", "0xabc"),  # Duplicate
        MockPosition("market3", "0xabc"),
    ]

    profile = classify_trader_profile(positions, "0xabc", threshold=10)

    assert profile.profile_type == "selective"  # Only 3 unique markets
    assert profile.unique_markets == 3
    assert profile.total_trades == 6  # Total position count


def test_classify_trader_profile_empty_positions():
    """Test classify_trader_profile with empty positions list."""
    from src.evaluation.profiles import classify_trader_profile

    profile = classify_trader_profile([], "0xabc", threshold=10)

    assert profile.trader_address == "0xabc"
    assert profile.profile_type == "selective"  # 0 < 10 = selective
    assert profile.unique_markets == 0
    assert profile.total_trades == 0
    assert profile.threshold_used == 10


def test_classify_trader_profile_custom_threshold():
    """Test classify_trader_profile with custom threshold."""
    from src.evaluation.profiles import classify_trader_profile

    positions = [
        MockPosition(f"market{i}", "0xabc")
        for i in range(4)
    ]

    # With threshold=5, 4 markets = selective
    profile = classify_trader_profile(positions, "0xabc", threshold=5)
    assert profile.profile_type == "selective"
    assert profile.threshold_used == 5

    # With threshold=3, 4 markets = active
    profile = classify_trader_profile(positions, "0xabc", threshold=3)
    assert profile.profile_type == "active"
    assert profile.threshold_used == 3


def test_classify_trader_profile_default_threshold():
    """Test classify_trader_profile uses default threshold of 10."""
    from src.evaluation.profiles import classify_trader_profile

    positions = [
        MockPosition(f"market{i}", "0xabc")
        for i in range(8)
    ]

    # Should use default threshold=10
    profile = classify_trader_profile(positions, "0xabc")

    assert profile.threshold_used == 10
    assert profile.profile_type == "selective"  # 8 < 10


def test_get_profile_consistency_bar_selective():
    """Test get_profile_consistency_bar for selective traders."""
    from src.evaluation.profiles import get_profile_consistency_bar

    bar = get_profile_consistency_bar("selective")

    assert bar["min_timeframes"] == 2
    assert bar["max_variance"] == 100


def test_get_profile_consistency_bar_active():
    """Test get_profile_consistency_bar for active traders."""
    from src.evaluation.profiles import get_profile_consistency_bar

    bar = get_profile_consistency_bar("active")

    assert bar["min_timeframes"] == 2
    assert bar["max_variance"] == 50  # Tighter bar for active


def test_get_profile_consistency_bar_unknown():
    """Test get_profile_consistency_bar raises error for unknown profile type."""
    from src.evaluation.profiles import get_profile_consistency_bar

    with pytest.raises(ValueError, match="Unknown profile type"):
        get_profile_consistency_bar("unknown")
