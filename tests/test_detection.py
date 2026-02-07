"""Tests for consensus detection and first-mover identification.

Test coverage:
- detect_consensus: min experts, agreement %, FLAT exclusion, denominator logic
- identify_first_mover: earliest entry timestamp selection, None handling
- classify_followers: first-mover, fast-follower, independent classification
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest

from src.signals.detection import (
    detect_consensus,
    identify_first_mover,
    classify_followers,
    ConsensusResult,
)


@dataclass
class MockPosition:
    """Mock position-like object for testing."""

    market_id: str
    trader_address: str
    direction: str
    size: Decimal
    avg_entry_price: Decimal | None
    entry_timestamp: datetime | None


class TestDetectConsensus:
    """Tests for detect_consensus function."""

    def test_detect_consensus_basic(self):
        """3 LONG experts on same market -> consensus detected."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
            "trader3": Decimal("85"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))

        assert len(results) == 1
        result = results[0]
        assert result.market_id == "market1"
        assert result.direction == "LONG"
        assert result.expert_count == 3
        assert result.total_experts_in_market == 3
        assert result.agreement_percentage == Decimal("100")
        assert len(result.expert_positions) == 3
        assert result.first_mover_address == "trader1"  # earliest entry_timestamp

    def test_detect_consensus_below_min_experts(self):
        """2 experts -> no consensus (min is 3)."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3)

        assert len(results) == 0

    def test_detect_consensus_below_agreement(self):
        """3 LONG, 2 SHORT (60% agreement) -> no consensus at 75% threshold."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            MockPosition("market1", "trader4", "SHORT", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 4, tzinfo=UTC)),
            MockPosition("market1", "trader5", "SHORT", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 5, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
            "trader3": Decimal("85"),
            "trader4": Decimal("75"),
            "trader5": Decimal("80"),
        }

        # 3 LONG out of 5 total = 60% < 75% threshold
        results = detect_consensus(positions, expert_scores, min_agreement_pct=Decimal("75"))

        assert len(results) == 0

    def test_detect_consensus_excludes_flat(self):
        """3 LONG, 2 FLAT -> FLAT excluded from both numerator and denominator."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            MockPosition("market1", "trader4", "FLAT", Decimal("0"), None, datetime(2024, 1, 4, tzinfo=UTC)),
            MockPosition("market1", "trader5", "FLAT", Decimal("0"), None, datetime(2024, 1, 5, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
            "trader3": Decimal("85"),
            "trader4": Decimal("75"),
            "trader5": Decimal("80"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3)

        assert len(results) == 1
        result = results[0]
        # Only 3 LONG experts count (FLAT excluded)
        assert result.expert_count == 3
        assert result.total_experts_in_market == 3  # FLAT excluded from denominator
        assert result.agreement_percentage == Decimal("100")

    def test_detect_consensus_agreement_denominator(self):
        """4 LONG, 1 SHORT = 80% agreement for LONG (denominator is 5, not 4)."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            MockPosition("market1", "trader4", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 4, tzinfo=UTC)),
            MockPosition("market1", "trader5", "SHORT", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 5, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
            "trader3": Decimal("85"),
            "trader4": Decimal("75"),
            "trader5": Decimal("80"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3, min_agreement_pct=Decimal("75"))

        assert len(results) == 1
        result = results[0]
        assert result.expert_count == 4
        assert result.total_experts_in_market == 5  # includes SHORT expert
        assert result.agreement_percentage == Decimal("80")  # 4/5 * 100

    def test_detect_consensus_multiple_markets(self):
        """Positions across 2 markets, only one meets threshold."""
        positions = [
            # Market 1: 3 LONG (meets consensus)
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            # Market 2: 2 LONG (doesn't meet min_experts)
            MockPosition("market2", "trader4", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 4, tzinfo=UTC)),
            MockPosition("market2", "trader5", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 5, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
            "trader3": Decimal("85"),
            "trader4": Decimal("75"),
            "trader5": Decimal("80"),
        }

        results = detect_consensus(positions, expert_scores, min_experts=3)

        assert len(results) == 1
        assert results[0].market_id == "market1"

    def test_detect_consensus_filters_non_experts(self):
        """5 positions but only 2 have score >70 -> no consensus."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            MockPosition("market1", "trader4", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 4, tzinfo=UTC)),
            MockPosition("market1", "trader5", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 5, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),  # expert
            "trader2": Decimal("80"),  # expert
            "trader3": Decimal("65"),  # not expert (<=70)
            "trader4": Decimal("50"),  # not expert
            "trader5": Decimal("70"),  # not expert (<=70)
        }

        results = detect_consensus(positions, expert_scores, min_experts=3)

        assert len(results) == 0  # only 2 experts, below min_experts=3

    def test_detect_consensus_includes_first_mover(self):
        """Verify first_mover_address is populated in ConsensusResult."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),  # earliest
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
        ]
        expert_scores = {
            "trader1": Decimal("75"),
            "trader2": Decimal("80"),
            "trader3": Decimal("85"),
        }

        results = detect_consensus(positions, expert_scores)

        assert len(results) == 1
        assert results[0].first_mover_address == "trader2"


class TestIdentifyFirstMover:
    """Tests for identify_first_mover function."""

    def test_identify_first_mover_basic(self):
        """3 positions, earliest entry_timestamp wins."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),  # earliest
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
        ]

        first_mover = identify_first_mover(positions)

        assert first_mover == "trader2"

    def test_identify_first_mover_none_timestamps(self):
        """All None entry_timestamps -> returns None."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), None),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), None),
        ]

        first_mover = identify_first_mover(positions)

        assert first_mover is None

    def test_identify_first_mover_some_none(self):
        """Some None timestamps -> ignore None, pick earliest non-None."""
        positions = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), None),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("150"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),  # earliest
        ]

        first_mover = identify_first_mover(positions)

        assert first_mover == "trader3"

    def test_identify_first_mover_empty_list(self):
        """Empty position list -> returns None."""
        first_mover = identify_first_mover([])

        assert first_mover is None


class TestClassifyFollowers:
    """Tests for classify_followers function."""

    def test_classify_followers(self):
        """First mover + fast follower (within 6h) + independent (after 6h)."""
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        positions = [
            MockPosition("market1", "first", "LONG", Decimal("100"), Decimal("0.5"), base_time),
            MockPosition("market1", "fast", "LONG", Decimal("200"), Decimal("0.5"), base_time + timedelta(hours=3)),  # within 6h
            MockPosition("market1", "independent", "LONG", Decimal("150"), Decimal("0.5"), base_time + timedelta(hours=8)),  # after 6h
        ]

        classifications = classify_followers(positions, "first", fast_follower_hours=6)

        assert classifications["first"] == "first_mover"
        assert classifications["fast"] == "fast_follower"
        assert classifications["independent"] == "independent"

    def test_classify_followers_exactly_at_boundary(self):
        """Position exactly at 6-hour boundary counts as fast follower."""
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        positions = [
            MockPosition("market1", "first", "LONG", Decimal("100"), Decimal("0.5"), base_time),
            MockPosition("market1", "boundary", "LONG", Decimal("200"), Decimal("0.5"), base_time + timedelta(hours=6)),
        ]

        classifications = classify_followers(positions, "first", fast_follower_hours=6)

        assert classifications["boundary"] == "fast_follower"

    def test_classify_followers_no_timestamps(self):
        """Positions with None timestamps -> all classified as independent except first_mover."""
        positions = [
            MockPosition("market1", "first", "LONG", Decimal("100"), Decimal("0.5"), None),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), None),
        ]

        classifications = classify_followers(positions, "first", fast_follower_hours=6)

        assert classifications["first"] == "first_mover"
        assert classifications["trader2"] == "independent"

    def test_classify_followers_custom_window(self):
        """Custom fast_follower_hours=2 -> tighter window."""
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        positions = [
            MockPosition("market1", "first", "LONG", Decimal("100"), Decimal("0.5"), base_time),
            MockPosition("market1", "fast", "LONG", Decimal("200"), Decimal("0.5"), base_time + timedelta(hours=1)),  # within 2h
            MockPosition("market1", "not_fast", "LONG", Decimal("150"), Decimal("0.5"), base_time + timedelta(hours=3)),  # after 2h
        ]

        classifications = classify_followers(positions, "first", fast_follower_hours=2)

        assert classifications["fast"] == "fast_follower"
        assert classifications["not_fast"] == "independent"
