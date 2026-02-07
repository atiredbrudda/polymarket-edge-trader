"""Tests for confidence score calculation.

Test coverage:
- calculate_confidence_score: agreement %, sample size, uniformity components
- Formula: 60% agreement + 30% sample size (asymptotic) + 10% uniformity
- Decimal precision, 0-100 range, capped at 100
"""

from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal

import pytest

from src.signals.confidence import calculate_confidence_score


@dataclass
class MockPosition:
    """Mock position-like object for testing."""

    market_id: str
    trader_address: str
    direction: str
    size: Decimal
    avg_entry_price: Decimal | None
    entry_timestamp: datetime | None


class TestCalculateConfidenceScore:
    """Tests for calculate_confidence_score function."""

    def test_below_min_experts_returns_zero(self):
        """2 experts -> 0 (below min_experts=3)."""
        experts_agreeing = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("200"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
        ]
        experts_total = 2

        confidence = calculate_confidence_score(experts_agreeing, experts_total, min_experts=3)

        assert confidence == Decimal("0")

    def test_exact_min_experts_unanimous(self):
        """3 of 3 experts -> high confidence (100% agreement = 60 pts, sample=0 pts at min, uniformity bonus)."""
        experts_agreeing = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
        ]
        experts_total = 3

        confidence = calculate_confidence_score(experts_agreeing, experts_total, min_experts=3)

        # Agreement: 3/3 * 100 = 100, weighted 60%
        # Sample size: at min_experts, (1 - exp(-0)) = 0, weighted 30%
        # Uniformity: identical volumes -> CV=0 -> uniformity=10
        # Total: 100 * 0.6 + 0 * 0.3 + 10 = 60 + 0 + 10 = 70
        assert confidence == Decimal("70")

    def test_confidence_increases_with_more_experts(self):
        """5 of 5 experts > 3 of 3 experts (sample size component)."""
        experts_3 = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 4)
        ]
        experts_5 = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 6)
        ]

        confidence_3 = calculate_confidence_score(experts_3, experts_total=3, min_experts=3)
        confidence_5 = calculate_confidence_score(experts_5, experts_total=5, min_experts=3)

        # Both have 100% agreement and identical uniformity
        # Difference is sample size: 5 experts > 3 experts
        assert confidence_5 > confidence_3

    def test_confidence_decreases_with_disagreement(self):
        """3 of 5 experts (60% agreement) < 3 of 3 experts (100% agreement)."""
        experts_3_of_3 = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 4)
        ]
        experts_3_of_5 = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 4)
        ]

        confidence_unanimous = calculate_confidence_score(experts_3_of_3, experts_total=3, min_experts=3)
        confidence_partial = calculate_confidence_score(experts_3_of_5, experts_total=5, min_experts=3)

        # 3/3 = 100% agreement vs 3/5 = 60% agreement
        # Agreement component: 100 * 0.6 = 60 vs 60 * 0.6 = 36
        # Difference: 24 points
        assert confidence_unanimous > confidence_partial
        assert confidence_unanimous - confidence_partial == Decimal("24")  # exactly 24 pts difference

    def test_uniform_positions_boost(self):
        """Identical position sizes give higher confidence than wildly different sizes."""
        # Uniform positions
        experts_uniform = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
        ]

        # Varied positions (same total volume, different sizes)
        experts_varied = [
            MockPosition("market1", "trader1", "LONG", Decimal("10"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("190"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
        ]

        confidence_uniform = calculate_confidence_score(experts_uniform, experts_total=3, min_experts=3)
        confidence_varied = calculate_confidence_score(experts_varied, experts_total=3, min_experts=3)

        # Same agreement % and sample size, only uniformity differs
        assert confidence_uniform > confidence_varied

    def test_single_expert_uniformity_zero(self):
        """Only 1 expert position -> uniformity component is 0 (but shouldn't reach this since min_experts=3)."""
        experts = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
        ]

        # With min_experts=1, single expert should work but uniformity is 0
        confidence = calculate_confidence_score(experts, experts_total=1, min_experts=1)

        # Agreement: 1/1 = 100%, weighted 60%
        # Sample size: at min=1, (1 - exp(0)) = 0, weighted 30%
        # Uniformity: single expert -> 0 (can't compute CV)
        # Total: 60 + 0 + 0 = 60
        assert confidence == Decimal("60")

    def test_confidence_capped_at_100(self):
        """Extreme values don't exceed 100."""
        # Many uniform experts (should max out components)
        experts = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 21)  # 20 experts
        ]

        confidence = calculate_confidence_score(experts, experts_total=20, min_experts=3)

        # Agreement: 20/20 = 100%, weighted 60 pts
        # Sample size: (1 - exp(-(20-3)/10)) = (1 - exp(-1.7)) ≈ 0.817, weighted 0.817*100*0.3 ≈ 24.5 pts
        # Uniformity: CV=0 -> 10 pts
        # Total ≈ 60 + 24.5 + 10 = 94.5 (under 100)
        assert confidence <= Decimal("100")

    def test_decimal_precision(self):
        """Result is Decimal, not float."""
        experts = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 4)
        ]

        confidence = calculate_confidence_score(experts, experts_total=3, min_experts=3)

        assert isinstance(confidence, Decimal)

    def test_missing_avg_entry_price_fallback(self):
        """Positions with None avg_entry_price use abs(size) for volume."""
        experts_with_price = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
        ]

        experts_without_price = [
            MockPosition("market1", "trader1", "LONG", Decimal("100"), None, datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("100"), None, datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("100"), None, datetime(2024, 1, 3, tzinfo=UTC)),
        ]

        confidence_with = calculate_confidence_score(experts_with_price, experts_total=3, min_experts=3)
        confidence_without = calculate_confidence_score(experts_without_price, experts_total=3, min_experts=3)

        # Both should be identical in uniformity (uniform sizes)
        assert confidence_with == confidence_without

    def test_zero_volume_uniformity_zero(self):
        """All positions with zero volume -> uniformity component is 0."""
        experts = [
            MockPosition("market1", "trader1", "LONG", Decimal("0"), Decimal("0.5"), datetime(2024, 1, 1, tzinfo=UTC)),
            MockPosition("market1", "trader2", "LONG", Decimal("0"), Decimal("0.5"), datetime(2024, 1, 2, tzinfo=UTC)),
            MockPosition("market1", "trader3", "LONG", Decimal("0"), Decimal("0.5"), datetime(2024, 1, 3, tzinfo=UTC)),
        ]

        confidence = calculate_confidence_score(experts, experts_total=3, min_experts=3)

        # Agreement: 100%, weighted 60 pts
        # Sample size: 0 at min_experts
        # Uniformity: all zero volumes -> 0
        # Total: 60 + 0 + 0 = 60
        assert confidence == Decimal("60")

    def test_sample_size_asymptotic_behavior(self):
        """Sample size component asymptotes to 100 as n increases."""
        # At min_experts=3: sample_size = (1 - exp(-(3-3)/10)) = 0
        # At min+10: sample_size = (1 - exp(-1)) ≈ 63.2
        # At min+20: sample_size = (1 - exp(-2)) ≈ 86.5
        # At large n: sample_size approaches 100

        experts_3 = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 4)  # 3 experts
        ]
        experts_13 = [
            MockPosition("market1", f"trader{i}", "LONG", Decimal("100"), Decimal("0.5"), datetime(2024, 1, i, tzinfo=UTC))
            for i in range(1, 14)  # 13 experts (min+10)
        ]

        confidence_3 = calculate_confidence_score(experts_3, experts_total=3, min_experts=3)
        confidence_13 = calculate_confidence_score(experts_13, experts_total=13, min_experts=3)

        # At 3: agreement=60, sample=0, uniformity=10 -> 70
        # At 13: agreement=60, sample≈18.96 (63.2*0.3), uniformity=10 -> ≈88.96
        assert confidence_3 == Decimal("70")
        # confidence_13 should be ~88-90 range
        assert Decimal("88") <= confidence_13 <= Decimal("91")
